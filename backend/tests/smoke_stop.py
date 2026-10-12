# 冒烟：停止生成（WebSocket message.cancel）。模拟模型（不打真接口）：
# 说到一半停止 → message.done 带 status=stopped、半截内容落库、GET 对话也带 status →
# 同一连接下一轮照常 → 对不上的 conversation_id 不误停 → 还没吐字就停 → message.stopped、不存空回复 →
# 停止后“重新生成”会替换半截回复 → 断线时半截回复也落库。
# 运行：python tests/smoke_stop.py
import os, sys, asyncio, subprocess, tempfile
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.agent import loop
from app.auth import issue_token
from app.db import SessionLocal
from app.llm import Turn
from app.models import Message
from app.routes import conversations as rconv, ws as rws

mode = {"m": "hang"}   # hang = 吐一段后卡住；silent = 一个字没吐就卡住；ok = 正常说完

async def fake_stream_turn(messages, tools=None, model=None, effort=None):
    if mode["m"] == "ok":
        yield "完整回答"
        yield Turn(text="完整回答")
        return
    if mode["m"] == "hang":
        yield "说到一半"
    await asyncio.sleep(3600)
    yield Turn(text="")
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

async def rows(cid):
    async with SessionLocal() as db:
        return [(m.role, m.status, m.blocks[0]["text"] if m.blocks else "") for m in
                (await db.scalars(select(Message).where(Message.conversation_id == cid).order_by(Message.created_at))).all()]

with c.websocket_connect(f"/ws?token={token}") as ws:
    ws.send_json({"type": "user.message", "text": "写首长诗"})
    ev = until(ws, "block.delta")
    cid = ev[0]["conversation_id"]
    ws.send_json({"type": "message.cancel", "conversation_id": "别的对话"})   # 对不上：不停
    ws.send_json({"type": "message.cancel", "conversation_id": cid})
    ev = until(ws, "message.done", "message.stopped", "error")
    done = ev[-1]
    assert done["type"] == "message.done" and done["message"]["status"] == "stopped", ev
    assert done["message"]["blocks"] == [{"type": "text", "text": "说到一半"}], done
    assert asyncio.run(rows(cid)) == [("user", "done", "写首长诗"), ("assistant", "stopped", "说到一半")]
    msgs = c.get(f"/api/conversations/{cid}", headers=H).json()["messages"]
    assert msgs[1]["status"] == "stopped" and "status" not in msgs[0], msgs

    # 停止后同一连接照常聊（停止没有把连接/队列弄坏）
    mode["m"] = "ok"
    ws.send_json({"type": "user.message", "conversation_id": cid, "text": "算了，简短点"})
    ev = until(ws, "message.done", "error")
    assert ev[-1]["type"] == "message.done" and "status" not in ev[-1]["message"], ev

    # 一个字都没吐就停 → message.stopped，不存空回复
    mode["m"] = "silent"
    ws.send_json({"type": "user.message", "conversation_id": cid, "text": "再来"})
    until(ws, "message.start")
    ws.send_json({"type": "message.cancel", "conversation_id": cid})
    ev = until(ws, "message.done", "message.stopped", "error")
    assert ev[-1] == {"type": "message.stopped", "conversation_id": cid}, ev
    assert asyncio.run(rows(cid))[-1] == ("user", "done", "再来")

    # 没有在跑的轮次时停止：什么也不发，下一条照常
    ws.send_json({"type": "message.cancel", "conversation_id": cid})
    mode["m"] = "ok"
    ws.send_json({"type": "message.regenerate", "conversation_id": cid})
    ev = until(ws, "message.done", "error")
    assert ev[0]["type"] == "message.start" and ev[-1]["message"]["blocks"][0]["text"] == "完整回答", ev

    # 停下的半截回复可以被“重新生成”替换
    mode["m"] = "hang"
    ws.send_json({"type": "user.message", "conversation_id": cid, "text": "第三问"})
    until(ws, "block.delta"); ws.send_json({"type": "message.cancel"})   # 不带 id = 停当前这轮
    stopped = until(ws, "message.done")[-1]["message"]
    mode["m"] = "ok"
    ws.send_json({"type": "message.regenerate", "conversation_id": cid, "message_id": stopped["id"]})
    ev = until(ws, "message.done", "error")
    assert ev[0]["replaced"] == [stopped["id"]] and ev[-1]["message"]["blocks"][0]["text"] == "完整回答", ev
    assert asyncio.run(rows(cid))[-1] == ("assistant", "done", "完整回答")

# 断线：半截回复照样落库（客户端重连后 GET 能看到）。TestClient 退出时会直接停掉事件循环，
# 测不到真实断线，所以直接驱动 _Turns：等它吐字 → close()（= 收到 WebSocketDisconnect）→ 查库。
mode["m"] = "hang"

async def disconnect_case():
    got = asyncio.Event(); sent = []
    class FakeWS:
        async def send_json(self, e):
            sent.append(e)
            if e["type"] == "block.delta":
                got.set()
    turns = rws._Turns(FakeWS())
    turns.enqueue(rws._handle_user_message, {"type": "user.message", "text": "断线测试"})
    turns.enqueue(rws._handle_user_message, {"type": "user.message", "text": "排队中的下一条"})
    await asyncio.wait_for(got.wait(), 5)
    turns.close()
    await asyncio.gather(*list(turns._all), return_exceptions=True)
    return sent[0]["conversation_id"]

cid2 = asyncio.run(disconnect_case())
assert asyncio.run(rows(cid2)) == [("user", "done", "断线测试"), ("assistant", "stopped", "说到一半")], asyncio.run(rows(cid2))
print("stop smoke OK")
