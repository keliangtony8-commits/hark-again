# 冒烟：回答途中补充（app/steering.py，v1.83，学 Codex steer）。模拟模型（不打真接口）。
# 正在答 → 用户补一句 → 下一次调模型前作为用户消息并进来、本要收尾也再来一圈 → 库里顺序 提问/补充/回复 →
# turn.steered 推给订阅者（带 client_id，快照里也有）→ 没在答 / !命令 / /init / 太长 → 不插（带附件的见 smoke_steer_attachments）（排队，message.start 带回 client_id）→
# 预算到头没读到 → 紧接着另起一轮回答它 → 点了停止不自动接 → 一轮最多插 STEER_MAX 句 → 下一轮历史里有这句。
# 运行：python tests/smoke_steering.py
import os, sys, asyncio, subprocess, tempfile
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from sqlalchemy import select
from app import live_turns, steering
from app.agent import loop
from app.config import settings
from app.db import SessionLocal
from app.llm import Turn
from app.models import Message
from app.routes import ws as rws

calls: list[list[dict]] = []
gate: dict[str, asyncio.Event] = {}


async def fake_stream_turn(messages, tools=None, model=None, effort=None):
    calls.append([dict(m) for m in messages])  # 照抄：loop 之后还会往同一个列表里加
    n = len(calls)
    if f"g{n}" in gate:
        entered.set()
        await gate[f"g{n}"].wait()
    text = f"第{n}次"
    yield text
    yield Turn(text=text)
loop.stream_turn = fake_stream_turn
entered = asyncio.Event()


class Client:
    def __init__(self):
        self.events: list[dict] = []
        self.conn = live_turns.Conn(self.send)

    async def send(self, e):
        self.events.append(e)

    async def until(self, pred, timeout=5):
        async with asyncio.timeout(timeout):
            while not pred(self.events):
                await asyncio.sleep(0.01)
        return self.events


def count(t):
    return lambda es: sum(e["type"] == t for e in es)


async def rows(cid):
    async with SessionLocal() as db:
        return [(m.role, m.status, "".join(b.get("text", "") for b in m.blocks)) for m in
                (await db.scalars(select(Message).where(Message.conversation_id == cid).order_by(Message.created_at))).all()]


def users(msgs):
    return [m["content"] for m in msgs if m["role"] == "user"]


async def main():
    settings.turn_offline_minutes = 30

    # 0) 规则
    assert steering.reason("") == "empty" and steering.reason("x", command=True) == "rich" and steering.reason("", files=1) is None
    assert steering.reason("x" * (steering.STEER_CHARS + 1)) == "long" and steering.reason("对了，用中文") is None
    box = steering.open_inbox("c0")
    assert steering.offer("c0", "早了", "m") is None, "历史还没拼好时不收"
    box.start()
    assert steering.offer("c0", " 收 ", "m1").text == "收" and steering.active("c0")
    assert [i.message_id for i in steering.close(box)] == ["m1"] and not steering.active("c0")
    assert steering.offer("c0", "晚了", "m2") is None
    print("ok: 规则")

    # 1) 正在答时补一句：下一次调模型前并进来；模型本要收尾也再来一圈
    a = Client()
    gate["g1"] = asyncio.Event()
    t = live_turns.enqueue(rws._handle_user_message, {"type": "user.message", "text": "写个计划"}, a.conn)
    await asyncio.wait_for(entered.wait(), 5)
    cid = next(e for e in a.events if e["type"] == "message.start")["conversation_id"]
    ok = await rws._steer({"type": "user.message", "conversation_id": cid, "text": "对了，要按周排", "steer": True, "client_id": "local-1"})
    assert ok
    gate["g1"].set()
    await a.until(count("message.done"))
    await asyncio.wait_for(asyncio.shield(t.task), 5)
    assert len(calls) == 2, len(calls)
    assert users(calls[1])[-2:] == ["写个计划", "对了，要按周排"], users(calls[1])
    assert calls[1][-2] == {"role": "assistant", "content": "第1次"}, calls[1][-3:]
    st = next(e for e in a.events if e["type"] == "turn.steered")
    assert st["client_id"] == "local-1" and st["message"]["status"] == "steer" and st["turn_id"] == t.id, st
    done = next(e for e in a.events if e["type"] == "message.done")["message"]
    assert "第1次" in str(done["blocks"]) and "第2次" in str(done["blocks"]), done
    r = await rows(cid)
    assert [x[:2] for x in r] == [("user", "done"), ("user", "steer"), ("assistant", "done")], r
    assert t.snapshot()["steered"][0]["id"] == st["message"]["id"]
    print("ok: 途中补充并进这一轮 + 库里顺序 + turn.steered")

    # 2) 插不进：没在答 / 附件 / !命令 / $技能 / 太长
    assert not await rws._steer({"conversation_id": cid, "text": "现在没在答", "steer": True})
    gate["g3"] = asyncio.Event()
    entered.clear()
    b = Client()
    t2 = live_turns.enqueue(rws._handle_user_message, {"type": "user.message", "conversation_id": cid, "text": "再来"}, b.conn)
    await asyncio.wait_for(entered.wait(), 5)
    for bad in ({"text": "!ls"}, {"text": "/init"}, {"text": "x" * (steering.STEER_CHARS + 1)}):
        assert not await rws._steer({"conversation_id": cid, "steer": True, **bad}), bad
    # 插不进的照常排队：message.start 带回 client_id
    c = Client()
    t3 = live_turns.enqueue(rws._handle_user_message, {"type": "user.message", "conversation_id": cid, "text": "!echo hi",
                                                       "client_id": "local-2"}, c.conn)
    gate["g3"].set()
    await asyncio.wait_for(asyncio.shield(t2.task), 5)
    await c.until(lambda es: any(e["type"] == "message.start" for e in es))
    assert next(e for e in c.events if e["type"] == "message.start")["client_id"] == "local-2"
    await asyncio.wait_for(asyncio.shield(t3.task), 10)
    print("ok: 插不进的照常排队 + client_id")

    # 3) 预算到头（这一步不能再调工具、也不再来一圈）：没读到的那句紧接着另起一轮回答
    old = settings.agent_max_steps
    settings.agent_max_steps = 1
    calls.clear()
    gate.clear()
    gate["g1"] = asyncio.Event()
    entered.clear()
    d = Client()
    t4 = live_turns.enqueue(rws._handle_user_message, {"type": "user.message", "text": "一步就好"}, d.conn)
    await asyncio.wait_for(entered.wait(), 5)
    cid2 = next(e for e in d.events if e["type"] == "message.start")["conversation_id"]
    assert await rws._steer({"conversation_id": cid2, "text": "顺便说下天气", "steer": True})
    gate["g1"].set()
    await d.until(lambda es: count("message.done")(es) >= 2, timeout=10)
    settings.agent_max_steps = old
    starts = [e for e in d.events if e["type"] == "message.start"]
    assert len(starts) == 2 and starts[1]["turn_id"] != t4.id, starts
    r = await rows(cid2)
    assert [x[:2] for x in r] == [("user", "done"), ("user", "steer"), ("assistant", "done"), ("assistant", "done")], r
    assert starts[1]["user_message_id"] == next(e for e in d.events if e["type"] == "turn.steered")["message"]["id"]
    assert users(calls[-1])[-2:] == ["一步就好", "顺便说下天气"], users(calls[-1])
    print("ok: 没读到的另起一轮")

    # 4) 点了停止：补充留在库里，不自动接
    calls.clear()
    gate.clear()
    gate["g1"] = asyncio.Event()
    entered.clear()
    e5 = Client()
    t5 = live_turns.enqueue(rws._handle_user_message, {"type": "user.message", "text": "慢慢来"}, e5.conn)
    await asyncio.wait_for(entered.wait(), 5)
    cid3 = next(e for e in e5.events if e["type"] == "message.start")["conversation_id"]
    for i in range(steering.STEER_MAX):
        assert await rws._steer({"conversation_id": cid3, "text": f"补{i}", "steer": True})
    assert not await rws._steer({"conversation_id": cid3, "text": "太多了", "steer": True}), "一轮最多 STEER_MAX 句"
    live_turns.stop(e5.conn, cid3)
    await asyncio.wait_for(asyncio.shield(t5.task), 5)
    await asyncio.sleep(0.2)
    r = await rows(cid3)
    assert [x[1] for x in r if x[0] == "user"] == ["done"] + ["steer"] * steering.STEER_MAX, r
    assert not [x for x in r if x[0] == "assistant" and x[1] == "done"], r
    assert not steering.active(cid3)
    assert sum(e["type"] == "message.start" for e in e5.events) == 1
    print("ok: 停止后不自动接 + 上限")

    # 5) 下一轮历史里有这句（普通用户消息）
    calls.clear()
    gate.clear()
    f = Client()
    t6 = live_turns.enqueue(rws._handle_user_message, {"type": "user.message", "conversation_id": cid, "text": "总结"}, f.conn)
    await asyncio.wait_for(asyncio.shield(t6.task), 5)
    assert "对了，要按周排" in users(calls[0]), users(calls[0])
    print("ok: 历史里有补充")

    await live_turns.drain()
    print("ALL OK")


asyncio.run(main())
