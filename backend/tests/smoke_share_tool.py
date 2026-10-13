# 冒烟：智能体工具 share_conversation（分享当前对话为网页）。模拟模型（不打真接口），无迁移。
# 对话里说“把这段对话分享出去” → 模型调 share(action=share) → 回复里出现 page 卡、公开页能打开、内容到用户这句为止；
# 与 REST /share 是同一个链接（客户端分享面板看到 shared）；status 报告已分享；unshare → 链接 404；
# 再 share → 原链接复活；没有当前对话（如工具测试上下文）时工具不提供；schemas 只在有 conversation_id 时带它。
# 运行：python tests/smoke_share_tool.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, PUBLIC_URL="https://me.example",
  TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from app import llm
from app.agent import runner
from app.agent.tools import REGISTRY, ToolContext, load_builtin, schemas
from app.auth import require_user
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message
from app.routes import conversations as rc, pages as rp

script: list = []   # 每次模型调用弹出一项：dict = 调 share_conversation，str = 文字
seen_tools: list = []

def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)

async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen_tools.append([t["function"]["name"] for t in (tools or [])]
                      + [n for t in (tools or []) if t["function"]["name"] == "deferred_tool"   # v2.05：按需工具在目录里
                         for n in ("share_conversation",) if f"- {n}：" in t["function"]["description"]])
    step = script.pop(0)
    async def gen():
        if isinstance(step, dict):
            yield chunk(tool=[NS(index=0, id=f"c{len(seen_tools)}", function=NS(name="share_conversation", arguments=json.dumps(step)))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()

app = FastAPI(); app.include_router(rc.router); app.include_router(rp.router); app.include_router(rp.public)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)


async def turn(cid, text, *steps):
    script.extend(steps)
    async with SessionLocal() as db:
        conv = await db.get(Conversation, cid)
        if conv is None:
            conv = Conversation(id=cid, title="去杭州的计划"); db.add(conv); await db.commit()
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks(text)))
        await db.commit()
        reply = await runner.run_turn(db, conv)
        return reply.blocks

# 先聊一轮（不调工具）
turn_blocks = asyncio.run(turn("c1", "周末去杭州，西湖骑行怎么安排", "早上九点从断桥出发，沿白堤骑到孤山。"))
assert "share_conversation" in seen_tools[-1], seen_tools  # 有当前对话 → 提供工具

# 要求分享 → 调工具 → page 卡
blocks = asyncio.run(turn("c1", "把这段对话分享给我朋友", {"action": "share"}, "好了，链接发给朋友就能看。"))
pages = [b for b in blocks if b["type"] == "page"]
assert len(pages) == 1, blocks
slug, url = pages[0]["slug"], pages[0]["url"]
assert url == f"https://me.example/p/{slug}/" and pages[0]["title"] == "去杭州的计划", pages
html = c.get(f"/p/{slug}/").text
assert "断桥出发" in html and "把这段对话分享给我朋友" in html, html
assert "链接发给朋友" not in html  # 快照到用户这句为止，本轮回复不在里面

# 与客户端分享面板同一个链接
st = c.get("/api/conversations/c1/share").json()
assert st["shared"] is True and st["slug"] == slug, st

# status / unshare / 再 share
async def call(action, cid="c1"):
    async with SessionLocal() as db:
        return await REGISTRY["share_conversation"].run(ToolContext(db=db, conversation_id=cid), action=action)
r = asyncio.run(call("status"))
assert r.content.startswith("已分享") and url in r.content and not r.blocks, r
r = asyncio.run(call("unshare"))
assert "已停止分享" in r.content, r
assert c.get(f"/p/{slug}/").status_code == 404
assert c.get("/api/conversations/c1/share").json()["shared"] is False
assert "已停止" in asyncio.run(call("status")).content
r = asyncio.run(call("share"))
assert r.blocks[0]["slug"] == slug and c.get(f"/p/{slug}/").status_code == 200, r

# 没有分享过的对话：status / unshare
async def fresh():
    async with SessionLocal() as db:
        db.add(Conversation(id="c2", title="别的")); await db.commit()
asyncio.run(fresh())
assert "没有公开分享。" in asyncio.run(call("status", "c2")).content
assert "本来就没有分享过" in asyncio.run(call("unshare", "c2")).content
assert "没有可分享的对话" in asyncio.run(call("share", "nope")).content

# 没有当前对话的上下文不提供这个工具
async def names(ctx_cid):
    async with SessionLocal() as db:
        ss = schemas(ToolContext(db=db, conversation_id=ctx_cid))
        return [s["function"]["name"] for s in ss] + [n for s in ss if s["function"]["name"] == "deferred_tool"
                                                      for n in ("share_conversation",) if f"- {n}：" in s["function"]["description"]]
assert "share_conversation" not in asyncio.run(names(None))
assert "share_conversation" in asyncio.run(names("c1"))
print("ok: share_conversation tool")
