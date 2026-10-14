# 冒烟：v2.87 引用回复（home-redesign §J 用户侧 / §C 同一列；规则在 app/reply_quote.py）。模拟模型，不打真接口：
# user.message 带 reply_to → 进库、GET 对话带 quote{id, role, text}；模型这一轮看到被引原文前缀（≤300 字），
# 下一轮那句只剩一行短记录；跨对话 / 不存在 / 乱写的 reply_to 被当成没引用（照常回答，不报错）；
# 原消息删了 → quote.missing、模型看到“已经删掉”；正在回答时带 reply_to 的话不插进这一轮（排成下一轮）；迁移 0063 往返。
# 运行：python tests/smoke_reply_quote.py
import os, sys, asyncio, subprocess, tempfile
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
alembic = lambda *a: subprocess.run([sys.executable, "-m", "alembic", *a], cwd=root, check=True, capture_output=True)
alembic("upgrade", "head")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import reply_quote
from app.agent import loop
from app.auth import issue_token
from app.db import SessionLocal
from app.llm import Turn
from app.models import Message
from app.routes import conversations as rconv, ws as rws

seen: list[list[dict]] = []
LONG = "第一步先备份数据库。" + "，".join(f"第{i}条注意事项编号{i * 7919 % 1000}" for i in range(60))

async def fake_stream_turn(messages, tools=None, model=None, effort=None):
    seen.append([dict(m) for m in messages])
    text = LONG if len(seen) == 1 else f"第{len(seen)}次回答"
    yield text
    yield Turn(text=text)
loop.stream_turn = fake_stream_turn

app = FastAPI(); app.include_router(rws.router); app.include_router(rconv.router)
c = TestClient(app)
token = issue_token()
H = {"Authorization": f"Bearer {token}"}

def until(ws, *types):
    out = []
    while True:
        e = ws.receive_json(); out.append(e)
        if e["type"] in types:
            return out

def last_user(msgs):
    return [m for m in msgs if m["role"] == "user"][-1]["content"]

def text(content):
    return content if isinstance(content, str) else " ".join(p.get("text", "") for p in content if isinstance(p, dict))

with c.websocket_connect(f"/ws?token={token}") as ws:
    ws.send_json({"type": "user.message", "text": "怎么迁移服务器？", "reply_to": "nope"})  # 新对话里乱写的 reply_to：忽略
    ev = until(ws, "message.done", "error"); assert ev[-1]["type"] == "message.done", ev
    cid = ev[0]["conversation_id"]; a1 = ev[-1]["message"]["id"]
    ws.send_json({"type": "user.message", "conversation_id": cid, "text": "这一步具体怎么做", "reply_to": a1})
    ev = until(ws, "message.done", "error"); assert ev[-1]["type"] == "message.done", ev
    u2 = ev[0]["user_message_id"]
    ws.send_json({"type": "user.message", "conversation_id": cid, "text": "好的谢谢"})
    ev = until(ws, "message.done", "error"); assert ev[-1]["type"] == "message.done", ev
    # 别的对话里的 id：忽略
    ws.send_json({"type": "user.message", "text": "另一件事", "reply_to": a1})
    ev = until(ws, "message.done", "error"); cid2 = ev[0]["conversation_id"]; assert cid2 != cid

import time; time.sleep(1.5)  # 后台起标题的写入先落完（SQLite 单写）
# 第一轮：没有引用前缀
assert "回复" not in text(last_user(seen[0])), last_user(seen[0])
# 第二轮：当前这一问带被引原文，截断到 PREFIX
cur = text(last_user(seen[1]))
assert cur.startswith("（用户在回复你之前说的：「第一步先备份数据库。"), cur[:80]
assert "这一步具体怎么做" in cur and "…」）" in cur and len(cur) < reply_quote.PREFIX + 80, len(cur)
# 第三轮：那句只剩短记录，当前这一问没有前缀
hist = [text(m["content"]) for m in seen[2] if m["role"] == "user"]
assert any(h.startswith("（回复你之前说的「第一步先备份数据库。") and len(h) < 80 for h in hist), hist
assert "回复" not in hist[-1], hist[-1]
# 另一个对话：引用被丢掉
assert "回复" not in text(last_user(seen[3]))

msgs = c.get(f"/api/conversations/{cid}", headers=H).json()["messages"]
q = [m for m in msgs if m["id"] == u2][0]
assert q["reply_to"] == a1 and q["quote"]["id"] == a1 and q["quote"]["role"] == "assistant", q
assert q["quote"]["text"].startswith("第一步先备份数据库。") and len(q["quote"]["text"]) <= reply_quote.SNIPPET, q["quote"]
assert all("quote" not in m for m in msgs if m["id"] != u2)
other = c.get(f"/api/conversations/{cid2}", headers=H).json()["messages"]
assert all("reply_to" not in m for m in other), other

# 原消息删掉 → missing；模型看到“已经删掉”
async def drop():
    async with SessionLocal() as db:
        await db.delete(await db.get(Message, a1)); await db.commit()
asyncio.run(drop())
msgs = c.get(f"/api/conversations/{cid}", headers=H).json()["messages"]
q = [m for m in msgs if m["id"] == u2][0]
assert q["quote"] == {"id": a1, "missing": True}, q
async def hist_now():
    from app.agent.context import build_history
    async with SessionLocal() as db:
        return await build_history(db, cid)
h = asyncio.run(hist_now())
assert any("已经删掉" in text(m["content"]) for m in h.messages if m["role"] == "user"), h.messages

# 附件当正文
assert reply_quote.text_of([{"type": "file", "id": "f", "name": "报表.xlsx"}]) == "[附件] 报表.xlsx"
assert reply_quote.cut("一二三四五", 3) == "一二…"

# 正在回答时带 reply_to：不插进这一轮
from app import steering
steering.active = lambda cid: True
assert asyncio.run(rws._steer({"conversation_id": cid, "text": "这个呢", "reply_to": u2})) is False

alembic("downgrade", "0062"); alembic("upgrade", "head")
print("ok: reply quote")
