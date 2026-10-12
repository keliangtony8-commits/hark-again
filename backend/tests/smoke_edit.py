# 冒烟：编辑最后一条用户消息后重答（message.regenerate 带 text）。模拟模型（不打真接口）：
# 正常一轮 → 编辑（用户消息原地改、id 不变、旧回复被删、模型看到新文字、message.start 带 user_message）→
# 过期 message_id 被拒且什么都不改 → 空文字被拒 → 上一轮失败（没回复）时编辑重发 → 带附件的消息编辑后附件保留。
# 运行：python tests/smoke_edit.py
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
    calls["seen"].append([(m["role"], m["content"]) for m in messages if m["role"] != "system"])
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

async def user_blocks(cid):
    async with SessionLocal() as db:
        m = (await db.scalars(select(Message).where(Message.conversation_id == cid, Message.role == "user")
                              .order_by(Message.created_at))).all()[-1]
        return m.id, m.blocks

with c.websocket_connect(f"/ws?token={token}") as ws:
    ev = turn(ws, {"type": "user.message", "text": "讲个笑话"})
    start, done = ev[0], ev[-1]
    cid, uid, first_id = start["conversation_id"], start["user_message_id"], done["message"]["id"]

    ev = turn(ws, {"type": "message.regenerate", "conversation_id": cid, "message_id": first_id, "text": "  讲个冷笑话 "})
    start, done = ev[0], ev[-1]
    assert start["user_message_id"] == uid and start["replaced"] == [first_id], ev
    assert "created_at" in start["user_message"], start
    assert {k: v for k, v in start["user_message"].items() if k != "created_at"} == {"id": uid, "role": "user", "blocks": [{"type": "text", "text": "讲个冷笑话"}]}, start
    assert start["title"] == "讲个笑话"                      # 标题不跟着改
    assert calls["seen"][-1] == [("user", "讲个冷笑话")], calls  # 模型看到的是新文字，没有旧回复
    assert asyncio.run(rows(cid)) == [("user", "讲个冷笑话"), ("assistant", "第2版回答")]
    second_id = done["message"]["id"]

    # 普通重新生成不带 user_message
    ev = turn(ws, {"type": "message.regenerate", "conversation_id": cid, "message_id": second_id})
    assert "user_message" not in ev[0] and ev[-1]["type"] == "message.done", ev
    third_id = ev[-1]["message"]["id"]

    ev = turn(ws, {"type": "message.regenerate", "conversation_id": cid, "message_id": first_id, "text": "别的"})
    assert ev == [{"type": "error", "message": "这条回复已经不是最新的了，刷新后再试"}], ev
    assert asyncio.run(rows(cid)) == [("user", "讲个冷笑话"), ("assistant", "第3版回答")]   # 被拒时什么都不改

    ev = turn(ws, {"type": "message.regenerate", "conversation_id": cid, "message_id": third_id, "text": "   "})
    assert ev == [{"type": "error", "message": "消息不能为空"}], ev
    assert asyncio.run(rows(cid))[-1] == ("assistant", "第3版回答")

    # 上一轮失败（只有用户消息）→ 编辑后重发，不带 message_id
    fail_next["on"] = True
    ev = turn(ws, {"type": "user.message", "conversation_id": cid, "text": "再来一个"})
    assert ev[-1]["type"] == "error"
    ev = turn(ws, {"type": "message.regenerate", "conversation_id": cid, "text": "再来两个"})
    assert ev[0]["replaced"] == [] and ev[-1]["type"] == "message.done", ev
    assert [r for r in asyncio.run(rows(cid))][-2:] == [("user", "再来两个"), ("assistant", "第5版回答")]

    # 带附件的消息：改文字，附件留着；只剩附件（文字清空）也行
    async def with_file():
        async with SessionLocal() as db:
            conv = Conversation(title="图"); db.add(conv); await db.flush()
            f = {"type": "file", "source": "upload", "id": "u1", "name": "a.png", "mime": "image/png", "size": 3}
            db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("看图") + [f]))
            await db.commit(); return conv.id
    fid = asyncio.run(with_file())
    ev = turn(ws, {"type": "message.regenerate", "conversation_id": fid, "text": ""})
    assert ev[-1]["type"] == "message.done", ev
    _, blocks = asyncio.run(user_blocks(fid))
    assert [b["type"] for b in blocks] == ["file"] and ev[0]["user_message"]["blocks"] == blocks, blocks
print("edit smoke OK")
