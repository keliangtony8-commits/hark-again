# 冒烟：v2.64 反馈（app/feedback.py + routes/feedback.py，不打真模型）。
# 👍 / 👎 打在回复上 → 快照（提问、回复、步骤、轨迹、模型）+ messages.feedback 随 to_wire 下发；再点 = 覆盖；取消 = 删报告清标记；
# 用户消息 / 不认识的评价 / 不存在的回复被拒；问题报告必填；列表新的在前 + 未解决数（👍 不算）；标已解决 / 重开；
# 复制报告的 Markdown 含各段且环境变量值被打码；删报告清回复标记；对话删了报告还在；迁移 0060 往返。
# 运行：python tests/smoke_feedback.py
import os, sys, asyncio, subprocess, tempfile, time
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
alembic = lambda *a: subprocess.run([sys.executable, "-m", "alembic", *a], cwd=root, check=True, capture_output=True)
alembic("upgrade", "head")

from datetime import datetime, timedelta, timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import command_env, feedback as fbm
from app.auth import require_user
from app.db import SessionLocal
from app.models import Conversation, Feedback, Message
from app.routes import feedback

T0 = datetime(2026, 10, 14, 1, 0, tzinfo=timezone.utc)
command_env.remember("SHOP_TOKEN", "sk-live-abcdef123456")

async def seed():
    async with SessionLocal() as db:
        c = Conversation(title="查快递", model="smart", reasoning="high")
        db.add(c); await db.flush()
        q = Message(conversation_id=c.id, role="user", blocks=[{"type": "text", "text": "帮我查一下顺丰 SF123 到哪了"}], created_at=T0)
        a = Message(conversation_id=c.id, role="assistant", status="looped", created_at=T0 + timedelta(seconds=30),
                    blocks=[{"type": "text", "text": "我没查到。"}],
                    steps=[{"id": "1", "tool": "web_fetch", "title": "打开网页", "detail": "https://sf-express.com", "state": "error", "ms": 2100, "note": "403"},
                           {"id": "2", "tool": "run_command", "title": "运行命令", "detail": "curl x", "state": "done", "ms": 300}],
                    trace=[{"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "run_command", "arguments": "{\"command\": \"curl -H 'X: sk-live-abcdef123456' x\"}"}}]},
                           {"role": "tool", "tool_call_id": "c1", "content": "```\nforbidden\n```"}])
        u2 = Message(conversation_id=c.id, role="user", blocks=[{"type": "text", "text": "再试试"}], created_at=T0 + timedelta(minutes=1))
        a2 = Message(conversation_id=c.id, role="assistant", blocks=[{"type": "text", "text": "到上海了"}], created_at=T0 + timedelta(minutes=2))
        db.add_all([q, a, u2, a2]); await db.commit()
        return c.id, q.id, a.id, a2.id

cid, qid, aid, a2id = asyncio.run(seed())

app = FastAPI(); app.include_router(feedback.router)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)

# —— 打评价 ——
r = c.post(f"/api/messages/{aid}/feedback", json={"kind": "wrong", "note": "顺丰官网要验证码，应该换个查法"})
assert r.status_code == 200, r.text
s = r.json(); assert s["kind"] == "wrong" and s["kind_label"] == "答错了" and s["status"] == "open" and s["message_id"] == aid
fid = s["id"]
d = c.get(f"/api/feedback/{fid}").json()
snap = d["snapshot"]
assert snap["question"] == "帮我查一下顺丰 SF123 到哪了", snap   # 最近的前一条用户消息，不是后面的“再试试”
assert snap["answer"] == "我没查到。" and snap["status"] == "looped" and snap["model"] == "smart" and snap["reasoning"] == "high"
assert [x["title"] for x in snap["steps"]] == ["打开网页", "运行命令"] and snap["steps"][0]["note"] == "403" and "id" not in snap["steps"][0]
assert "→ run_command(" in snap["trace"] and "← ```" in snap["trace"]
assert "sk-live-abcdef123456" not in snap["trace"], snap["trace"]  # 环境变量值打码
md = d["markdown"]
for part in ("# 反馈：答错了", "## 补充说明", "顺丰官网要验证码", "## 提问", "## 回复", "## 步骤", "1. 打开网页 `https://sf-express.com` — ✗ · 2.1s（403）", "## 工具轨迹", "````", "回复结束方式：looped", "模型：smart", "- 时间：20"):
    assert part in md, (part, md)
assert "sk-live-abcdef123456" not in md
assert "+00:00" not in md.split("\n")[2], md.split("\n")[2]  # 本地时间，不是 ISO

async def wire(mid):
    async with SessionLocal() as db:
        return (await db.get(Message, mid)).to_wire()
assert asyncio.run(wire(aid))["feedback"] == "wrong"
assert "feedback" not in asyncio.run(wire(a2id))

# 再点 = 覆盖（还是同一份，换原因、清掉旧补充）
r = c.post(f"/api/messages/{aid}/feedback", json={"kind": "stuck"}); assert r.json()["id"] == fid and r.json()["kind"] == "stuck"
assert c.get(f"/api/feedback/{fid}").json()["note"] == ""
assert asyncio.run(wire(aid))["feedback"] == "stuck"

# 拒绝的
assert c.post(f"/api/messages/{qid}/feedback", json={"kind": "good"}).status_code == 400
assert c.post(f"/api/messages/{aid}/feedback", json={"kind": "meh"}).status_code == 400
assert c.post("/api/messages/nope/feedback", json={"kind": "good"}).status_code == 404
assert c.post("/api/feedback", json={"note": "   "}).status_code == 400
# 补充太长截断
r = c.post(f"/api/messages/{a2id}/feedback", json={"kind": "good", "note": "好" * 3000})
assert len(c.get(f"/api/feedback/{r.json()['id']}").json()["note"]) == fbm.NOTE_MAX + 1
good_id = r.json()["id"]

# 问题报告
r = c.post("/api/feedback", json={"note": "  安卓上语音输入按了没反应  "})
assert r.status_code == 200 and r.json()["kind"] == "problem" and r.json()["note"] == "安卓上语音输入按了没反应" and r.json()["message_id"] is None
pid = r.json()["id"]
assert "# 反馈：问题报告" in r.json()["markdown"] and "## 提问" not in r.json()["markdown"]

# 列表：新的在前；未解决数不算 👍
L = c.get("/api/feedback").json()
assert [x["id"] for x in L["items"]][0] == pid and len(L["items"]) == 3, L
assert L["open"] == 2, L
assert next(x for x in L["items"] if x["id"] == fid)["excerpt"].startswith("帮我查一下顺丰")

# 标已解决 / 重开
r = c.patch(f"/api/feedback/{pid}", json={"status": "resolved"}); assert r.json()["status"] == "resolved" and r.json()["resolved_at"]
assert c.get("/api/feedback").json()["open"] == 1
assert [x["id"] for x in c.get("/api/feedback?status=resolved").json()["items"]] == [pid]
assert c.patch(f"/api/feedback/{pid}", json={"status": "done"}).status_code == 400
r = c.patch(f"/api/feedback/{pid}", json={"status": "open"}); assert r.json()["status"] == "open" and r.json()["resolved_at"] is None

# 取消评价
r = c.delete(f"/api/messages/{a2id}/feedback"); assert r.json()["removed"] is True
assert "feedback" not in asyncio.run(wire(a2id)) and c.get(f"/api/feedback/{good_id}").status_code == 404
assert c.delete(f"/api/messages/{a2id}/feedback").json()["removed"] is False

# 删报告 → 回复标记一起清
r = c.post(f"/api/messages/{a2id}/feedback", json={"kind": "incomplete"}); rid = r.json()["id"]
assert c.delete(f"/api/feedback/{rid}").status_code == 200
assert "feedback" not in asyncio.run(wire(a2id))
assert c.delete(f"/api/feedback/{rid}").status_code == 404

# 对话删了，报告还在（快照）
async def drop():
    async with SessionLocal() as db:
        await db.delete(await db.get(Conversation, cid)); await db.commit()
asyncio.run(drop())
d = c.get(f"/api/feedback/{fid}").json()
assert d["snapshot"]["answer"] == "我没查到。" and d["kind"] == "stuck"
assert c.delete(f"/api/feedback/{fid}").status_code == 200  # 回复不在了也能删

# 迁移往返
alembic("downgrade", "0059"); alembic("upgrade", "head")
print("smoke_feedback OK")
