# 冒烟：断线后回答继续写 + 重连续传（app/live_turns.py，v1.61）。模拟模型（不打真接口）。
# 断线后这一轮照常跑完并落库 → 新连接带 turn_id + after 续传：只补 seq > after、连续不重复、拿到 message.done →
# 只带 conversation_id 的“旁观”能接上正在跑的轮次（从 message.start 起），已结束的不重放 → 未知轮次 live=false →
# 日志被截断时发 turn.snapshot（折叠好的全文 + 步骤）→ 没人看着超时按停止收尾、重连则取消计时 →
# 别的连接能按 conversation_id 停 → 同一对话排队、不同对话并行 → 慢客户端积压超限被断开 → WebSocket 上 ping/pong 与 resume。
# 运行：python tests/smoke_live_turns.py
import os, sys, asyncio, subprocess, tempfile
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from sqlalchemy import select
from app import live_turns
from app.agent import loop
from app.config import settings
from app.db import SessionLocal
from app.llm import Turn
from app.models import Message
from app.routes import ws as rws

gate: dict[str, asyncio.Event] = {}
script = {"parts": ["第一段", "第二段"], "hang": False}


async def fake_stream_turn(messages, tools=None, model=None, effort=None):
    parts = list(script["parts"])
    yield parts[0]
    if "g" in gate:
        await gate["g"].wait()
    for p in parts[1:]:
        yield p
    if script["hang"]:
        await asyncio.sleep(3600)
    yield Turn(text="".join(parts))
loop.stream_turn = fake_stream_turn


class Client:
    def __init__(self, block=False):
        self.events: list[dict] = []
        self.block = block
        self.conn = live_turns.Conn(self.send, self.overflow)
        self.overflowed = False

    async def send(self, e):
        if self.block:
            await asyncio.sleep(3600)
        self.events.append(e)

    async def overflow(self):
        self.overflowed = True

    async def until(self, *types, timeout=5):
        async with asyncio.timeout(timeout):
            while not any(e["type"] in types for e in self.events):
                await asyncio.sleep(0.01)
        return self.events


async def rows(cid):
    async with SessionLocal() as db:
        return [(m.role, m.status, "".join(b.get("text", "") for b in m.blocks)) for m in
                (await db.scalars(select(Message).where(Message.conversation_id == cid).order_by(Message.created_at))).all()]


async def main():
    settings.turn_offline_minutes = 30

    # 1) 断线后继续写，重连续传
    gate["g"] = asyncio.Event()
    a = Client()
    t = live_turns.enqueue(rws._handle_user_message, {"type": "user.message", "text": "写两段"}, a.conn)
    await a.until("block.delta")
    seen = max(e["seq"] for e in a.events)
    assert [e["seq"] for e in a.events] == list(range(1, seen + 1)), a.events   # 连续编号
    assert all(e["turn_id"] == t.id for e in a.events)
    cid = a.events[0]["conversation_id"]
    a.conn.close()                                          # 断线：不停
    await asyncio.sleep(0.05)
    assert t.running and not t.stop.is_set()
    gate["g"].set()
    await asyncio.wait_for(asyncio.shield(t.task), 5)
    assert await rows(cid) == [("user", "done", "写两段"), ("assistant", "done", "第一段第二段")], await rows(cid)
    b = Client()
    live_turns.resume(b.conn, {"turn_id": t.id, "conversation_id": cid, "after": seen})
    await b.until("message.done")
    head = b.events[0]
    assert head["type"] == "turn.resumed" and head["live"] and head["ended"] and not head["gap"], head
    replay = b.events[1:]
    assert [e["seq"] for e in replay] == list(range(seen + 1, t.seq + 1)), replay
    assert "".join(e.get("text", "") for e in replay if e["type"] == "block.delta") == "第二段", replay
    assert replay[-1]["message"]["blocks"][0]["text"] == "第一段第二段"
    print("ok: 断线后继续写 + 续传")

    # 2) 旁观：只带 conversation_id 接正在跑的轮次；已结束的不重放
    c = Client()
    live_turns.resume(c.conn, {"conversation_id": cid})
    await c.until("turn.resumed")
    assert c.events == [{"type": "turn.resumed", "turn_id": None, "conversation_id": cid, "live": False}], c.events
    gate["g"] = asyncio.Event()
    a2 = Client()
    t2 = live_turns.enqueue(rws._handle_user_message, {"type": "user.message", "conversation_id": cid, "text": "再来"}, a2.conn)
    await a2.until("block.delta")
    w = Client()
    live_turns.resume(w.conn, {"conversation_id": cid})
    await w.until("block.delta")
    assert w.events[0]["live"] and not w.events[0]["ended"] and w.events[1]["type"] == "message.start", w.events
    gate["g"].set()
    await w.until("message.done")
    await a2.until("message.done")
    assert [e["seq"] for e in w.events[1:]] == [e["seq"] for e in a2.events], (w.events, a2.events)
    print("ok: 旁观接上正在跑的轮次")

    # 3) 未知轮次
    u = Client()
    live_turns.resume(u.conn, {"turn_id": "nope", "after": 3})
    await u.until("turn.resumed")
    assert u.events[0]["live"] is False
    # 对话对不上：不给别的对话的轮次
    live_turns.resume(u.conn, {"turn_id": t2.id, "conversation_id": "别的对话"})
    await asyncio.sleep(0.05)
    assert u.events[-1]["live"] is False, u.events
    print("ok: 未知轮次 live=false")

    # 4) 日志截断 → 快照
    old_max = live_turns.LOG_MAX
    live_turns.LOG_MAX = 3
    script["parts"] = ["甲", "乙", "丙", "丁", "戊", "己"]
    gate["g"] = asyncio.Event()
    s1 = Client()
    t4 = live_turns.enqueue(rws._handle_user_message, {"type": "user.message", "text": "长一点"}, s1.conn)
    await s1.until("block.delta")
    gate["g"].set()
    await s1.until("message.done")
    s2 = Client()
    live_turns.resume(s2.conn, {"turn_id": t4.id, "after": 1})
    await s2.until("message.done")
    head, snap = s2.events[0], s2.events[1]
    assert head["gap"] and snap["type"] == "turn.snapshot", s2.events
    assert snap["message"]["blocks"] == [{"type": "text", "text": "甲乙丙丁戊己"}], snap
    assert snap["seq"] == t4.seq - 1 and s2.events[2]["type"] == "message.done" and len(s2.events) == 3, s2.events
    live_turns.LOG_MAX = old_max
    script["parts"] = ["第一段", "第二段"]
    print("ok: 截断后快照")

    # 5) 没人看着超时 → 按停止收尾；重连会取消计时
    settings.turn_offline_minutes = 0.002   # ≈0.12 秒
    script["hang"] = True
    gate.pop("g", None)
    o = Client()
    t5 = live_turns.enqueue(rws._handle_user_message, {"type": "user.message", "text": "孤儿"}, o.conn)
    await o.until("block.delta")
    cid5 = o.events[0]["conversation_id"]
    o.conn.close()
    r = Client()
    live_turns.resume(r.conn, {"turn_id": t5.id, "after": max(e["seq"] for e in o.events)})   # 马上回来：计时取消
    await asyncio.sleep(0.3)
    assert t5.running, "reattached turn must keep running"
    r.conn.close()
    await asyncio.wait_for(asyncio.shield(t5.task), 5)
    assert (await rows(cid5))[-1][:2] == ("assistant", "stopped"), await rows(cid5)
    print("ok: 离线超时按停止收尾")

    # 6) 别的连接按 conversation_id 停；同一对话排队、不同对话并行
    settings.turn_offline_minutes = 30
    p = Client()
    t6 = live_turns.enqueue(rws._handle_user_message, {"type": "user.message", "conversation_id": cid, "text": "第一"}, p.conn)
    t7 = live_turns.enqueue(rws._handle_user_message, {"type": "user.message", "conversation_id": cid, "text": "第二"}, p.conn)
    t8 = live_turns.enqueue(rws._handle_user_message, {"type": "user.message", "text": "另一个对话"}, p.conn)
    await asyncio.sleep(0.3)
    assert t6.running and not t7.running and t8.running, (t6.running, t7.running, t8.running)
    other = Client()
    live_turns.stop(other.conn, "不是这个对话")
    await asyncio.sleep(0.05)
    assert t6.running
    live_turns.stop(other.conn, cid)
    await asyncio.wait_for(asyncio.shield(t6.task), 5)
    await asyncio.sleep(0.2)
    assert t7.running, "queued turn of the same conversation starts after the stopped one"
    live_turns.stop(other.conn, cid)
    live_turns.stop(p.conn, None)        # 不带 id：停这条连接订阅的、在跑的
    await asyncio.wait_for(asyncio.gather(t7.task, t8.task), 5)
    script["hang"] = False
    print("ok: 跨连接停止 + 同对话排队 + 不同对话并行")

    # 7) 慢客户端积压超限 → 断开（不拖住这一轮）
    old_out = live_turns.OUTBOX_MAX
    live_turns.OUTBOX_MAX = 2
    slow = Client(block=True)
    t9 = live_turns.enqueue(rws._handle_user_message, {"type": "user.message", "text": "慢"}, slow.conn)
    await asyncio.wait_for(asyncio.shield(t9.task), 5)
    await asyncio.sleep(0.05)
    assert slow.overflowed and slow.conn.closed and slow.conn not in t9.subs
    live_turns.OUTBOX_MAX = old_out
    print("ok: 积压超限断开")


asyncio.run(main())

# 8) WebSocket 路由：ping/pong、turn.resume 对未知轮次
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth import issue_token
app = FastAPI(); app.include_router(rws.router)
with TestClient(app).websocket_connect(f"/ws?token={issue_token()}") as ws:
    ws.send_json({"type": "ping"})
    assert ws.receive_json() == {"type": "pong"}
    ws.send_json({"type": "turn.resume", "turn_id": "x", "conversation_id": "y", "after": "bad"})
    assert ws.receive_json() == {"type": "turn.resumed", "turn_id": "x", "conversation_id": "y", "live": False}
print("live turns smoke OK")
