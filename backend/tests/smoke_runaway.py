# 冒烟：v2.42 E2E B15 前台转后台时“零输出 + 一直满 CPU” → 回执说像死循环、默认停掉（app/runaway.py）。无迁移。
# 1) runaway 规则：零输出 + 累计 CPU/秒 ≥ BUSY_CORES 或这一刻 ≥ BUSY_PERCENT → 像；有输出 / 在 sleep / 拿不到用量 → 不像；
#    idle_cap：默认 20 分钟 → 5 分钟，本来更短不动，0（不判卡住）也收紧；
# 2) 一轮模拟模型：run_command 转后台、job_usage 采到满 CPU → 工具结果带 ⚠ 和 cancel_job，任务行 idle_timeout 收紧，
#    模型照做 cancel_job → 任务停掉、stopped_by=agent；
# 3) 转后台但有输出（pip 装东西）→ 不采用量、不带 ⚠、idle 不动；零输出但在 sleep（CPU 很低）→ 不带 ⚠。
# 运行：python tests/smoke_runaway.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

# 1) 规则
from app import runaway
U = lambda cpu_s, cpu: {"cpu": cpu, "cpu_seconds": cpu_s, "memory": 1 << 20, "processes": 1}
assert runaway.looks_stuck("", 120, U(118.0, 99.5))
assert runaway.looks_stuck("  \n", 120, U(100.0, 40.0))      # 累计够了（这一刻刚好低）
assert runaway.looks_stuck("", 120, U(55.0, 96.0))           # 配额只有半个核：这一刻占满
assert not runaway.looks_stuck("tick 1\n", 120, U(118.0, 99.5))  # 有输出：不是这种
assert not runaway.looks_stuck("", 120, U(0.3, 0.0))         # sleep / 等网络
assert not runaway.looks_stuck("", 120, None)                 # 拿不到用量：不冤枉
assert not runaway.looks_stuck("", 0, U(1.0, 99.0))
assert runaway.idle_cap(1200) == 300 and runaway.idle_cap(0) == 300 and runaway.idle_cap(120) == 120
n = runaway.note("jabc", 120, U(118.0, 99.5), 300)
assert "死循环" in n and "cancel_job" in n and "jabc" in n and "5 分钟" in n and "2 分钟" in n and "还在跑" in n, n
print("rules ok")

# 2) 一轮模拟模型
from app import job_usage, jobs, llm, sandbox_client, storage
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Job, Message, Project
load_builtin()

OUT = {"loop": "", "pip": "Collecting torch\n", "sleepy": ""}
async def fake_stream(project_id, command, timeout=60, stdin=None, env=None, promote=None, **kw):
    out = OUT[command.split()[0]]
    if out:
        yield {"type": "out", "data": out}
    jid = promote[0]
    d = storage.project_dir(project_id) / ".jobs" / jid
    d.mkdir(parents=True)
    (d / "cmd.sh").write_text(command + "\n"); (d / "log").write_text(out); (d / "pid").write_text("4242\n")
    yield {"type": "exit", "exit_code": None, "timed_out": False, "promoted": jid, "waited": timeout, "output": out}
sandbox_client.stream = fake_stream
asked = []
USE = {"loop": U(119.0, 99.8), "sleepy": U(0.2, 0.0), "pip": U(119.0, 99.8)}
async def fake_of(job):
    asked.append(job.command)
    return USE[job.command.split()[0]]
job_usage.of = fake_of
cancelled = []
async def fake_cancel_job(project_id, job_id):
    cancelled.append(job_id)
    return {}
sandbox_client.cancel_job = fake_cancel_job

async def seed(ask):
    async with SessionLocal() as db:
        p = Project(name="跑代码", emoji="🧪"); db.add(p); await db.flush()
        conv = Conversation(title="t", project_id=p.id); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks(ask)))
        await db.commit(); return p.id, conv.id

seen, script = [], []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
ids = iter(range(10_000))
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append([dict(m) for m in messages])
    step = script.pop(0)
    if callable(step):
        step = step(messages)
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"c{next(ids)}", function=NS(name=n, arguments=json.dumps(a)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create

# foreground.run 测的是墙钟秒数：让它看起来跑满了 120 秒
from app import foreground
_run = foreground.run
async def run_120(*a, **k):
    r = await _run(*a, **k)
    r.seconds = 120.0
    return r
foreground.run = run_120

async def turn(cid):
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))
async def job_of(pid):
    async with SessionLocal() as db:
        from sqlalchemy import select
        return (await db.execute(select(Job).where(Job.project_id == pid))).scalars().one()

pid, cid = asyncio.run(seed("运行 python3 -c 'while True: pass' 看会怎样"))
def cancel_step(messages):
    tool_msg = [m for m in messages if m["role"] == "tool"][-1]["content"]
    jid = tool_msg.split("后台任务 ")[1].split(" ")[0]
    return [("cancel_job", {"job_id": jid})]
script.extend([[("run_command", {"command": "loop python3 -c 'while True: pass'", "timeout": 120})],
               cancel_step, "它一直不输出、满 CPU，像死循环，我已经停掉了。"])
reply = asyncio.run(turn(cid))
tool_msg = [m for m in seen[1] if m["role"] == "tool"][-1]["content"]
assert "像死循环" in tool_msg and "cancel_job" in tool_msg and "5 分钟无输出算卡住" in tool_msg, tool_msg
assert "现在简短告诉用户这条命令转到后台在跑" not in tool_msg
j = asyncio.run(job_of(pid))
assert j.idle_timeout == runaway.SILENT_IDLE_S, j.idle_timeout
assert [s["tool"] for s in reply.steps] == ["run_command", "cancel_job"], reply.steps
assert cancelled == [j.id] and (jobs.job_dir(j) / "cancelled").read_text() == "agent", cancelled
print("loop → note + cancel_job ok")

# 3) 有输出 → 不采用量；零输出但在睡 → 不提
for cmd, ask in (("pip install torch", "装 torch"), ("sleepy sleep 600", "等十分钟")):
    asked.clear()
    pid, cid = asyncio.run(seed(ask))
    script.extend([[("run_command", {"command": cmd, "timeout": 120})], "转到后台在跑。"])
    n0 = len(seen)
    asyncio.run(turn(cid))
    tool_msg = [m for m in seen[n0 + 1] if m["role"] == "tool"][-1]["content"]
    assert "死循环" not in tool_msg and "现在简短告诉用户这条命令转到后台在跑" in tool_msg, tool_msg
    j = asyncio.run(job_of(pid))
    assert j.idle_timeout == jobs.idle_limit(None, j.timeout), j.idle_timeout
    assert asked == ([] if cmd.startswith("pip") else [cmd]), asked
print("smoke_runaway OK")
