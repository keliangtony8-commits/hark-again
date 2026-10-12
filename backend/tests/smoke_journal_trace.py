# 冒烟：v1.57 崩溃检查点也存工具轨迹（app/turn_journal.py + app/agent/tool_trace.py）。模拟模型。
# 1) 规则：缺结果按步骤状态补（running → 结果未知；done/error → 做完了但结果没存下）；默认补法不变；
# 2) 第一条命令做完、第二条卡住时进程被杀 → 检查点里有两次调用（第一条真实结果）→ 恢复的 interrupted 消息带 trace、不上协议；
# 3) 下一轮给模型的历史里重放这些调用（配对完整）+ <turn_aborted>；
# 4) 做完但结果没进消息列表 → “结果丢了”；轨迹算不出来不影响检查点；5) 老行/坏轨迹 → trace 空；6) 迁移 0034。
# 运行：python tests/smoke_journal_trace.py
import os, sys, asyncio, subprocess, tempfile, json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', LLM_MAX_RETRIES="0")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from sqlalchemy import select
from app import llm, sandbox_client, turn_journal as tj
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.auth import require_user
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message, TurnJournal
from app.routes import conversations as rc
from fastapi import FastAPI
from fastapi.testclient import TestClient

script: list = []
sent: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    sent.append([dict(m) for m in messages])
    step = script.pop(0)
    if isinstance(step, Exception):
        raise step
    async def gen():
        if isinstance(step, tuple):  # (文字, [工具调用])
            text, calls = step
            yield chunk(text)
            yield chunk(tool=[NS(index=i, id=f"c{len(script)}-{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(calls)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()

seen_mid: dict = {}
async def fake_stream(project_id, command, timeout=60, stdin=None):
    yield {"type": "out", "data": "装到一半…\n"}
    if command.startswith("pip"):
        await asyncio.sleep(0.4)  # 心跳间隔调到 0.1 s：这段时间里至少跳两次
        async with SessionLocal() as db:
            row = (await db.scalars(select(TurnJournal))).one()
            seen_mid.update(blocks=row.blocks, steps=row.steps, owner=row.owner, started=row.started_at, beat=row.beat_at)
        if command.endswith("hang"):
            await asyncio.sleep(3600)
    yield {"type": "exit", "exit_code": 0, "timed_out": False, "output": "ok\n"}
sandbox_client.stream = fake_stream
tj.BEAT_S = 0.1

async def seed(text="装个包"):
    async with SessionLocal() as db:
        conv = Conversation(title="恢复"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks(text)))
        await db.commit()
        return conv.id
async def turn(cid, **kw):
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), **kw)
async def journals():
    async with SessionLocal() as db:
        return (await db.scalars(select(TurnJournal))).all()
async def messages(cid):
    async with SessionLocal() as db:
        return (await db.scalars(select(Message).where(Message.conversation_id == cid).order_by(Message.created_at))).all()


from app.agent import tool_trace

# ---- 规则 ----
miss = tj.trace_missing([{"id": "a", "state": "done"}, {"id": "b", "state": "error"}, {"id": "c", "state": "running"}])
assert miss("a") == tj.TRACE_LOST.format(state="做完了") and "失败了" in miss("b"), (miss("a"), miss("b"))
assert miss("c") == tj.TRACE_UNKNOWN and miss("zzz") == tj.TRACE_UNKNOWN
msgs_ = [{"role": "user", "content": "q"},
         {"role": "assistant", "content": None, "tool_calls": [
             {"id": "a", "type": "function", "function": {"name": "run_command", "arguments": "{}"}},
             {"id": "c", "type": "function", "function": {"name": "run_command", "arguments": "{}"}}]}]
tr = tool_trace.record(msgs_, 1, missing=miss)
assert [m.get("content") for m in tr[1:]] == [miss("a"), tj.TRACE_UNKNOWN] and tool_trace.valid(tr), tr
assert tool_trace.record(msgs_, 1)[1]["content"] == tool_trace.ABORTED  # 默认不变（正常落库 / 用户停止）

# ---- 1. 正常一轮：检查点中途带轨迹，结束后删掉 ----
cid = asyncio.run(seed())
async def journal_rows():
    async with SessionLocal() as db:
        return (await db.scalars(select(TurnJournal))).all()
mid_trace: dict = {}
orig_stream = sandbox_client.stream
async def spy_stream(project_id, command, timeout=60, stdin=None):
    async for ev in orig_stream(project_id, command, timeout, stdin):
        if command.endswith("hang") and not mid_trace:
            async with SessionLocal() as db:
                row = (await db.scalars(select(TurnJournal))).one()
                mid_trace.update(trace=row.trace, steps=row.steps, blocks=row.blocks, started=row.started_at)
        yield ev
sandbox_client.stream = spy_stream

# ---- 2. 第一条命令做完、第二条卡住时进程被杀 ----
async def crash(cid, first_cmd):
    stop = asyncio.Event()
    t = asyncio.create_task(turn(cid, stop=stop))
    for _ in range(400):
        await asyncio.sleep(0.02)
        if mid_trace:
            break
    else:
        raise AssertionError("never reached the hanging command")
    stop.set(); t.cancel(); await t
    async with SessionLocal() as db:  # 停止落的消息删掉，换成“被杀”留下的检查点
        last = (await db.scalars(select(Message).where(Message.conversation_id == cid).order_by(Message.created_at.desc()))).first()
        await db.delete(last)
        db.add(TurnJournal(conversation_id=cid, owner="backend:deadboot0000", blocks=mid_trace["blocks"],
                           steps=mid_trace["steps"], trace=mid_trace["trace"], started_at=mid_trace["started"],
                           beat_at=datetime.now(timezone.utc)))
        await db.commit()
script.extend([("先装 a。", [("run_command", {"command": "pip install aaa"})]),
               ("再装 b。", [("run_command", {"command": "pip install hang"})])])
asyncio.run(crash(cid, "pip install aaa"))
tr = mid_trace["trace"]
assert tool_trace.valid(tr), tr
calls = [json.loads(m["tool_calls"][0]["function"]["arguments"])["command"] for m in tr if m.get("tool_calls")]
assert calls == ["pip install aaa", "pip install hang"], calls
outs = [m["content"] for m in tr if m["role"] == "tool"]
assert "ok" in outs[0] and outs[1] == tj.TRACE_UNKNOWN, outs  # 第一条真实结果，第二条结果未知
assert asyncio.run(tj.recover_all("backend")) == 1
bad = asyncio.run(messages(cid))[-1]
assert bad.status == "interrupted" and bad.trace == tr, bad.trace
assert "trace" not in bad.to_wire()  # 不上协议

# ---- 3. 下一轮：模型看到被打断前的调用和结果（重放），回复后面附 <turn_aborted> ----
async def say(cid, text):
    async with SessionLocal() as db:
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks(text))); await db.commit()
asyncio.run(say(cid, "继续"))
sent.clear(); script.extend(["刚才被打断了，a 装好了，我看看 b。"])
asyncio.run(turn(cid))
hist = sent[-1]
i = next(k for k, m in enumerate(hist) if m.get("tool_calls"))
assert hist[i]["tool_calls"][0]["function"]["name"] == "run_command"
tools = [m for m in hist if m["role"] == "tool"]
assert len(tools) == 2 and tools[1]["content"] == tj.TRACE_UNKNOWN, tools
pending = set()
for m in hist:  # 配对完整：每个调用后面紧跟它的结果
    if m.get("tool_calls"):
        assert not pending; pending = {c["id"] for c in m["tool_calls"]}
    elif m["role"] == "tool":
        pending.discard(m["tool_call_id"])
    else:
        assert not pending, hist
after = [m for m in hist if m["role"] == "assistant" and m.get("content")][-1]["content"]
assert "<turn_aborted>" in after and "pip install hang" in after, after
assert hist[-1] == {"role": "user", "content": "继续"}

# ---- 4. 做完了但结果没来得及进消息列表：补“结果丢了”而不是“结果未知” ----
from app.agent.loop import MessageBuilder
b = MessageBuilder()
b.transcript, b.base = list(msgs_), 1
b.timeline.steps = [{"id": "a", "state": "done"}, {"id": "c", "state": "running"}]
got = tj._trace(b, b.steps())
assert [m["content"] for m in got[1:]] == [tj.TRACE_LOST.format(state="做完了"), tj.TRACE_UNKNOWN], got
class Broken:
    def trace(self, missing=None): raise RuntimeError("x")
assert tj._trace(Broken(), []) == []  # 算不出来就不存，不影响这一轮

# ---- 5. 老行（没有轨迹）/ 坏轨迹：恢复照常，trace 为空 ----
cid5 = asyncio.run(seed("老行"))
async def plant(trace):
    async with SessionLocal() as db:
        db.add(TurnJournal(conversation_id=cid5, owner="backend:deadboot0001", blocks=[{"type": "text", "text": "半截"}],
                           steps=[], trace=trace)); await db.commit()
asyncio.run(plant([{"role": "tool", "tool_call_id": "x", "content": "孤儿"}]))
assert asyncio.run(tj.recover_all("backend")) == 1
assert asyncio.run(messages(cid5))[-1].trace == []
assert asyncio.run(journal_rows()) == []

# ---- 6. 迁移 0034 可降可升 ----
for args in (["downgrade", "0033"], ["upgrade", "head"]):
    r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
print("smoke_journal_trace ok")
