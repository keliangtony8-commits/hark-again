# 冒烟：分享对话为只读网页快照（/api/conversations/{id}/share）。无模型调用、无迁移（来源记在 Pages 的 meta.json）。
# 未分享 → {shared:false}；分享 → 公开可看、文字/表格/代码/数字卡渲染、审批卡与浏览器画面不出现、附件只留文件名、
# HTML 与非 http 链接被转义/去掉；新消息 → stale；再分享 → 同一 slug、新内容、stale 清零；停止分享 → 公开 404、
# 链接不变、Pages 列表仍在；再分享复活；不存在的对话 404。
# 运行：python tests/smoke_share_conversation.py
import os, sys, asyncio, subprocess, tempfile, time
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, PUBLIC_URL="https://me.example")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth import require_user
from app.db import SessionLocal
from app.models import Conversation, Message
from app.routes import conversations as rc, pages as rp
from app import conversation_share

app = FastAPI(); app.include_router(rc.router); app.include_router(rp.router); app.include_router(rp.public)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)


async def seed():
    async with SessionLocal() as db:
        db.add(Conversation(id="c1", title="周末去杭州 <b>"))
        db.add(Message(id="m1", conversation_id="c1", role="user",
                       blocks=[{"type": "text", "text": "帮我排个行程 <script>alert(1)</script>"},
                               {"type": "file", "source": "upload", "id": "u1", "name": "车票.pdf"}]))
        db.add(Message(id="m2", conversation_id="c1", role="assistant", blocks=[
            {"type": "text", "text": "## 第一天\n- **西湖** 骑行\n- 看 [官网](https://example.com) 和 [坏链](javascript:alert(1))\n\n`代码` 结束"},
            {"type": "table", "columns": ["时间", "地点"], "rows": [["9:00", "断桥"]]},
            {"type": "code", "language": "py", "source": "print('<hi>')"},
            {"type": "stats", "items": [{"label": "预算", "value": "¥800"}]},
            {"type": "approval", "id": "a1", "title": "付款给某某", "detail": "秘密金额", "state": "pending"},
            {"type": "browser", "session": "main"}]))
        await db.commit()

asyncio.run(seed())

assert c.get("/api/conversations/c1/share").json() == {"shared": False}
assert c.get("/api/conversations/nope/share").status_code == 404
assert c.post("/api/conversations/nope/share").status_code == 404

s = c.post("/api/conversations/c1/share").json()
slug = s["slug"]
assert s["shared"] is True and s["stale"] is False and s["url"] == f"https://me.example/p/{slug}/", s
assert s["source"] == "conversation:c1" and s["title"] == "周末去杭州 <b>", s
html = c.get(f"/p/{slug}/").text
for want in ["<h2>第一天</h2>", "<strong>西湖</strong>", 'href="https://example.com"', "<th>时间</th>", "<td>断桥</td>",
             "print(&#x27;&lt;hi&gt;&lt;/code&gt;" if False else "&lt;hi&gt;", "¥800", "附件 · 车票.pdf",
             "<code>代码</code>", "周末去杭州 &lt;b&gt;", '<section class="msg user">', '<section class="msg ai">']:
    assert want in html, (want, html)
for bad in ["<script>", "javascript:", "付款给某某", "秘密金额", "/api/files", "u1"]:
    assert bad not in html, (bad, html)
assert c.get("/api/conversations/c1/share").json()["stale"] is False

# 新消息 → stale；再分享同一 slug、新内容
time.sleep(0.01)
async def more():
    async with SessionLocal() as db:
        db.add(Message(id="m3", conversation_id="c1", role="user", blocks=[{"type": "text", "text": "再加一天"}]))
        await db.commit()
asyncio.run(more())
st = c.get("/api/conversations/c1/share").json()
assert st["stale"] is True and st["shared"] is True, st
s2 = c.post("/api/conversations/c1/share").json()
assert s2["slug"] == slug and s2["stale"] is False, s2
assert "再加一天" in c.get(f"/p/{slug}/").text

# 停止分享 → 下线、链接保留、Pages 列表里仍在
off = c.delete("/api/conversations/c1/share").json()
assert off["shared"] is False and off["published"] is False and off["slug"] == slug, off
assert c.get(f"/p/{slug}/").status_code == 404
assert [p["id"] for p in c.get("/api/pages").json()] == [slug]
# 再分享 → 原链接复活
assert c.post("/api/conversations/c1/share").json()["slug"] == slug
assert c.get(f"/p/{slug}/").status_code == 200

# 智能体改写同一页面不丢来源；Markdown 单元
from app import pages_store
pages_store.save("改名", "<p>x</p>", slug)
assert pages_store.find_by_source("conversation:c1")["slug"] == slug
md = conversation_share.markdown("1. a\n2. b\n\n```js\nx<y\n```\n> 引用 *斜*")
assert "<ol><li>a</li><li>b</li></ol>" in md and "x&lt;y" in md and "<em>斜</em>" in md, md
print("ok: share conversation")
