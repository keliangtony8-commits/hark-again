# 冒烟：WebSocket 重新生成。模拟模型（不打真接口）：
# 正常一轮 → 重新生成（旧回复被删、message.start 带 replaced、历史里只剩一条回复）→
# 过期的 message_id 被拒 → 上一轮失败（没有回复）时不带 message_id 重试 → 没有用户消息的对话报错。
# 运行：python tests/smoke_regenerate.py
import os, sys, asyncio, subprocess, tempfile
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.agent import loop
from app.auth import issue_token
from app.db import SessionLocal
from app.llm import Turn
from app.models import Conversation, Message
from app.routes import ws as rws
from app.blocks import text_to_blocks
from sqlalchemy import select

calls = {"n": 0, "seen": []}
fail_next = {"on": False}

async def fake_stream_turn(messages, tools=None, model=None, effort=None):
    calls["n"] += 1
    calls["seen"].append([m["role"] for m in messages if m["role"] != "system"])
    if fail_next["on"]:
        fail_next["on"] = False
        raise RuntimeError("网关超时")
    text = f"第{calls['n']}版回答"
    yield text
    yield Turn(text=text)
loop.stream_turn = fake_stream_turn

app = FastAPI(); app.include_router(rws.router)
c = TestClient(app)
token = issue_token()

def turn(ws, event):
    """发一个事件，收到 message.done 或 error 为止。"""
    ws.send_json(event)
    out = []
    while True:
        e = ws.receive_json(); e.pop("turn_id", None); e.pop("seq", None); out.append(e)  # 续传游标（v1.61）不在比较之列
        if e["type"] in ("message.done", "error"):
            return out

async def rows(cid):
    async with SessionLocal() as db:
        return [(m.role, m.blocks[0]["text"] if m.blocks else "") for m in
                (await db.scalars(select(Message).where(Message.conversation_id == cid).order_by(Message.created_at))).all()]

with c.websocket_connect(f"/ws?token={token}") as ws:
    ev = turn(ws, {"type": "user.message", "text": "讲个笑话"})
    start, done = ev[0], ev[-1]
    cid, first_id = start["conversation_id"], done["message"]["id"]
    assert "replaced" not in start and done["message"]["blocks"][0]["text"] == "第1版回答", ev

    ev = turn(ws, {"type": "message.regenerate", "conversation_id": cid, "message_id": first_id})
    start, done = ev[0], ev[-1]
    assert start["type"] == "message.start" and start["replaced"] == [first_id], ev
    assert done["message"]["blocks"][0]["text"] == "第2版回答" and done["message"]["id"] != first_id
    assert calls["seen"][-1] == ["user"], calls          # 旧回复不进历史
    assert asyncio.run(rows(cid)) == [("user", "讲个笑话"), ("assistant", "第2版回答")]

    ev = turn(ws, {"type": "message.regenerate", "conversation_id": cid, "message_id": first_id})
    assert ev == [{"type": "error", "message": "这条回复已经不是最新的了，刷新后再试"}], ev
    assert asyncio.run(rows(cid))[-1] == ("assistant", "第2版回答")   # 被拒时什么都不删

    # 上一轮模型失败 → 只有用户消息 → 不带 message_id 重试
    fail_next["on"] = True
    ev = turn(ws, {"type": "user.message", "conversation_id": cid, "text": "再来一个"})
    assert ev[-1]["type"] == "error"
    ev = turn(ws, {"type": "message.regenerate", "conversation_id": cid})
    assert ev[0]["replaced"] == [] and ev[-1]["message"]["blocks"][0]["text"] == "第4版回答", ev
    assert [r[0] for r in asyncio.run(rows(cid))] == ["user", "assistant", "user", "assistant"]

    async def empty():
        async with SessionLocal() as db:
            conv = Conversation(title="空"); db.add(conv); await db.commit(); return conv.id
    ev = turn(ws, {"type": "message.regenerate", "conversation_id": asyncio.run(empty())})
    assert ev[-1] == {"type": "error", "message": "这个对话里还没有可以重新回答的消息"}, ev
    ev = turn(ws, {"type": "message.regenerate", "conversation_id": "nope"})
    assert ev[-1]["message"] == "对话不存在"
print("regenerate smoke OK")
