# 冒烟：v1.52 一轮回答的崩溃恢复（app/turn_journal.py，思路移植自 deepseek-harness session/repair.ts）。模拟模型。
# 1) 一轮进行中有检查点：块（含实时代码块）和 running 步骤都在，心跳在动；正常结束后检查点删掉、消息照常落库；
# 2) 模拟进程被杀：同类进程换了启动 id → 启动时 recover_all 转成 interrupted 消息（半截文字保留、live 去掉、步骤 stopped + 结果未知）；
# 3) 另一个进程（worker）留下的：心跳没过期不动，过期了打开对话（GET）就恢复；
# 4) 下一轮给模型的历史里有 <turn_aborted> 说明（列出结果未知的操作）；用户停止的回复也附说明；
# 5) 模型出错 / 用户停止：不留检查点；
# 6) 规则单测 + 迁移 0031 可降可升。
# 运行：python tests/smoke_turn_journal.py
import os, sys, asyncio, subprocess, tempfile, json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", NEXT_SPEAKER_CHECK="off", LITELLM_MASTER_KEY="k",
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
async def fake_stream(project_id, command, timeout=60, stdin=None, **kw):
    yield {"type": "out", "data": "装到一半…\n"}
    if command.startswith("pip"):
        await asyncio.sleep(0.4)  # 心跳间隔调到 0.1 s：这段时间里至少跳两次
        async with SessionLocal() as db:
            row = (await db.scalars(select(TurnJournal))).one()
            seen_mid.update(blocks=row.blocks, steps=row.steps, owner=row.owner, started=row.started_at, beat=row.beat_at)
        if command == "pip install hang":
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

# ---- 规则 ----
tj.claim("backend")
now = datetime.now(timezone.utc)
assert tj.owner() == f"backend:{tj.BOOT}"
assert not tj.dead(tj.owner(), now, now)  # 自己、心跳新
assert tj.dead("backend:oldboot", now, now)  # 同类进程换了启动 id
assert not tj.dead("worker:abc", now - timedelta(seconds=30), now)  # 别的进程，心跳还新
assert tj.dead("worker:abc", now - timedelta(seconds=tj.STALE_S + 1), now)
assert tj.dead("worker:abc", (now - timedelta(seconds=tj.STALE_S + 1)).replace(tzinfo=None), now)  # SQLite 无时区 = UTC
assert tj.dead("", None, now)
st = tj.interrupted_steps([{"id": "a", "state": "done"}, {"id": "b", "state": "running", "title": "运行命令", "detail": "pip i x"}])
assert st[0] == {"id": "a", "state": "done"} and st[1]["state"] == "stopped" and st[1]["code"] == tj.TOOL_OUTCOME_UNKNOWN, st
assert tj.history_note("done", st) == ""
n = tj.history_note("interrupted", st)
assert "<turn_aborted>" in n and "- 运行命令：pip i x" in n and "别盲目重试" in n and "不是用户停的" in n, n
assert "接着做" in tj.history_note("interrupted", []) and "运行命令" not in tj.history_note("interrupted", [])
s = tj.history_note("stopped", [{"state": "stopped", "title": "运行命令", "detail": "make"}])
assert "用户中途停止" in s and "- 运行命令：make" in s, s
assert "可能执行了一部分" not in tj.history_note("stopped", [{"state": "done", "title": "x"}])

# ---- 1. 正常一轮：中途有检查点，结束删掉 ----
cid = asyncio.run(seed())
script.extend([("先装依赖。", [("run_command", {"command": "pip install requests"})]), "装好了。"])
reply = asyncio.run(turn(cid))
assert reply.status == "done" and [s["state"] for s in reply.steps] == ["done"], reply.steps
assert seen_mid["owner"] == tj.owner(), seen_mid
assert seen_mid["blocks"][0] == {"type": "text", "text": "先装依赖。"}, seen_mid["blocks"]
live = [b for b in seen_mid["blocks"] if b.get("live")]
assert live and live[0]["type"] == "code" and "装到一半" in live[0]["source"], seen_mid["blocks"]
assert [s["state"] for s in seen_mid["steps"]] == ["running"] and seen_mid["steps"][0]["detail"] == "pip install requests"
started, beat = [t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t for t in (seen_mid["started"], seen_mid["beat"])]
assert beat > started, seen_mid  # 心跳在动
assert asyncio.run(journals()) == []

# ---- 2. 模拟进程被杀：拿到中途的检查点，假装是上一次启动留下的 ----
cid2 = asyncio.run(seed("装个会卡住的包"))
async def crash():
    stop = asyncio.Event()
    t = asyncio.create_task(turn(cid2, stop=stop))
    for _ in range(300):
        await asyncio.sleep(0.02)
        if seen_mid.get("steps") and seen_mid["blocks"][0]["text"] == "开始装。":
            break
    else:
        raise AssertionError(seen_mid)
    stop.set(); t.cancel(); await t  # 用户停止的路径：落库 stopped、检查点删掉
    assert await journals() == []
    msgs = await messages(cid2)
    assert msgs[-1].status == "stopped"
    async with SessionLocal() as db:  # 换成“被杀”：删掉停止落的消息，把中途检查点按旧启动 id 放回去
        await db.delete(await db.get(Message, msgs[-1].id))
        db.add(TurnJournal(conversation_id=cid2, owner="backend:deadboot0000", blocks=seen_mid["blocks"],
                           steps=seen_mid["steps"], started_at=seen_mid["started"], beat_at=datetime.now(timezone.utc)))
        await db.commit()
seen_mid.clear()
script.extend([("开始装。", [("run_command", {"command": "pip install hang"})])])
asyncio.run(crash())
assert asyncio.run(tj.recover_all("backend")) == 1
assert asyncio.run(journals()) == []
msgs = asyncio.run(messages(cid2))
bad = msgs[-1]
assert [m.role for m in msgs] == ["user", "assistant"] and bad.status == "interrupted", [(m.role, m.status) for m in msgs]
assert bad.blocks[0] == {"type": "text", "text": "开始装。"} and not any(b.get("live") for b in bad.blocks), bad.blocks
assert bad.steps[0]["state"] == "stopped" and bad.steps[0]["code"] == tj.TOOL_OUTCOME_UNKNOWN and bad.steps[0]["note"] == tj.UNKNOWN_NOTE
assert bad.to_wire()["status"] == "interrupted"
assert asyncio.run(tj.recover_all("backend")) == 0  # 幂等

# ---- 4. 下一轮：模型看到 <turn_aborted> ----
async def say(cid, text):
    async with SessionLocal() as db:
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks(text))); await db.commit()
asyncio.run(say(cid2, "继续"))
sent.clear(); script.extend(["刚才被打断了，我先看看装没装上。"])
asyncio.run(turn(cid2))
hist = sent[-1]
prev = [m for m in hist if m["role"] == "assistant"][-1]["content"]
assert prev.startswith("开始装。") and "<turn_aborted>" in prev and "pip install hang" in prev, prev
assert hist[-1] == {"role": "user", "content": "继续"}

# ---- 3. 另一个进程留下的：心跳新不动，过期了 GET 打开就恢复 ----
cid3 = asyncio.run(seed("任务"))
async def plant(beat):
    async with SessionLocal() as db:
        db.add(TurnJournal(conversation_id=cid3, owner="worker:livebeat0000", task_id="t1",
                           blocks=[{"type": "text", "text": "查到一半"}], steps=[], started_at=beat, beat_at=beat))
        await db.commit()
asyncio.run(plant(datetime.now(timezone.utc)))
app = FastAPI(); app.include_router(rc.router)
app.dependency_overrides[require_user] = lambda: "u"
client = TestClient(app)
got = client.get(f"/api/conversations/{cid3}").json()["messages"]
assert len(got) == 1 and len(asyncio.run(journals())) == 1  # 那个进程还活着：不动
async def age():
    async with SessionLocal() as db:
        row = (await db.scalars(select(TurnJournal))).one()
        row.beat_at = datetime.now(timezone.utc) - timedelta(seconds=tj.STALE_S + 5); await db.commit()
asyncio.run(age())
got = client.get(f"/api/conversations/{cid3}").json()["messages"]
assert len(got) == 2 and got[1]["status"] == "interrupted" and got[1]["blocks"] == [{"type": "text", "text": "查到一半"}], got
assert "steps" not in got[1] and asyncio.run(journals()) == []

# ---- 4b. 用户停止的回复：下一轮也附说明 ----
cid4 = asyncio.run(seed("跑个长命令"))
async def stop_it():
    stop = asyncio.Event()
    t = asyncio.create_task(turn(cid4, stop=stop))
    for _ in range(300):
        await asyncio.sleep(0.02)
        if seen_mid.get("steps"):
            break
    stop.set(); t.cancel(); await t
seen_mid.clear()
script.extend([("跑起来。", [("run_command", {"command": "pip install hang"})])])
asyncio.run(stop_it())
assert asyncio.run(journals()) == []
asyncio.run(say(cid4, "怎么样了"))
sent.clear(); script.extend(["你停下了它。"])
asyncio.run(turn(cid4))
prev = [m for m in sent[-1] if m["role"] == "assistant"][-1]["content"]
assert "用户中途停止" in prev and "pip install hang" in prev, prev

# ---- 5. 模型出错：不留检查点、不落消息 ----
cid5 = asyncio.run(seed("出错"))
script.extend([RuntimeError("boom")])
errors = []
async def emit(ev):
    errors.append(ev)
assert asyncio.run(turn(cid5, emit=emit)) is None
assert any(e["type"] == "error" for e in errors) and asyncio.run(journals()) == []
assert [m.role for m in asyncio.run(messages(cid5))] == ["user"]

# ---- 6. 迁移 ----
for args in (["downgrade", "0030"], ["upgrade", "head"]):
    r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
print("smoke_turn_journal ok")
