# 冒烟：v2.04 前台命令到点没跑完 → 转后台接着跑（不杀）。移植 deepseek-harness tool-bash promoteOnTimeout 的语义（MIT）。
# 1) 真 sandbox/runner.py（docker 换成本机 bash）：
#    到点前结束 → 普通结果、不留 .jobs；到点没完 → promoted=<id>、exit_code None、output = 到目前的输出，
#    .jobs/<id>/{cmd.sh,pid,log} 现场登记，之后的输出追加进 log（不重复不丢），结束原子写 exit；
#    超长输出到点 → log 是全文（spill 文件并进去后删掉），结果里 spill 指向 job 日志；pid 是进程组组长、oom_score_adj 调高；
#    整组杀能停掉它（写出 exit）；/exec/stream 的最后一行带 promoted；不带 promote 的照旧到点杀；坏任务 id 400。
# 2) 后端：run_command 先问 admission，能收就带 promote 给沙盒；结果 promoted → jobs.adopt 建行（promoted、读游标在日志末尾、
#    开始时间往前推）、任务卡带 promoted、给模型的话说清楚；之后写 exit → refresh 结算 + 通知；describe 标“前台命令转入后台”；
#    后台任务满了 → 不带 promote，到点照旧杀，提示里说明原因；用户自己 ! 跑的命令不转后台。模拟模型（无真实模型调用）。
# 运行：python tests/smoke_promote.py
import os, sys, asyncio, subprocess, tempfile, json, time, types, signal
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

# ---- 1. 真 runner：docker 换成本机 bash ----
procs = {}
class FakeApi:
    def exec_create(self, cid_, argv, workdir=None, environment=None):
        eid = f"e{len(procs)}"
        procs[eid] = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      env={**os.environ, **(environment or {})}, cwd=tmp)
        return {"Id": eid}
    def exec_start(self, eid, stream=False):
        p = procs[eid]
        while (b := p.stdout.read1(64)):
            yield b
    def exec_inspect(self, eid):
        return {"ExitCode": procs[eid].wait()}
class FakeContainer:
    id, status = "c1", "running"
    image = NS(id="img")
    def exec_run(self, cmd, workdir=None, detach=False, **kw):
        r = subprocess.run(cmd, capture_output=True, cwd=tmp)
        return NS(exit_code=r.returncode, output=r.stdout)
fake_client = NS(api=FakeApi(), containers=NS(get=lambda name: FakeContainer(), list=lambda **kw: []),
                 images=NS(get=lambda name: NS(id="img")))
docker_mod = types.ModuleType("docker"); docker_mod.from_env = lambda: fake_client
errors_mod = types.ModuleType("docker.errors"); errors_mod.NotFound = type("NotFound", (Exception,), {})
docker_mod.errors = errors_mod
sys.modules.update({"docker": docker_mod, "docker.errors": errors_mod})
os.environ.update(SANDBOX_TOKEN="t", HOST_PROJECTS_DIR=tmp)
sys.path.insert(0, os.path.join(root, "..", "sandbox"))
import runner
runner.FLUSH_S = 0.05
runner.PROJECTS_ROOT = os.path.join(tmp, "sbx")
runner.os.chown = lambda *a, **k: None
J = lambda jid: os.path.join(runner.PROJECTS_ROOT, "p1", ".jobs", jid)
def wait_for(path, s=8.0):
    end = time.time() + s
    while time.time() < end and not os.path.exists(path):
        time.sleep(0.05)
    assert os.path.exists(path), path

# 到点前结束：普通结果，什么都不留
r = runner._exec("p1", "echo a; sleep 0.3; echo b", 3, promote=("j00000a", 60))
assert r == {"exit_code": 0, "timed_out": False, "output": "a\nb\n"}, r
assert not os.path.exists(J("j00000a"))

# 到点没完：转后台
t0 = time.time()
r = runner._exec("p1", "echo early; sleep 1.5; echo late; exit 3", 1, promote=("j00000b", 60))
assert time.time() - t0 < 1.4, "到点就返回，不等命令结束"
assert r["promoted"] == "j00000b" and r["exit_code"] is None and r["timed_out"] is False and r["output"] == "early\n", r
assert r["waited"] == 1 and "_log" not in r
d = J("j00000b")
assert open(f"{d}/cmd.sh").read() == "echo early; sleep 1.5; echo late; exit 3\n"
group = int(open(f"{d}/pid").read())
assert os.getpgid(group) == group, "pid 文件记的是进程组组长（timeout）"
assert open(f"/proc/{group}/oom_score_adj").read().strip() == str(runner.PROMOTE_OOM_ADJ)
assert not os.path.exists(f"{d}/exit")
wait_for(f"{d}/exit")
assert open(f"{d}/exit").read().strip() == "3" and not os.path.exists(f"{d}/exit.tmp")
assert open(f"{d}/log").read() == "early\nlate\n", open(f"{d}/log").read()  # 不丢不重复
assert not os.path.exists(f"{d}/oom")
time.sleep(0.2)
assert not any(f.startswith(".exec-") and os.path.getmtime(f"/tmp/{f}") > t0 for f in os.listdir("/tmp")), "pid 文件应被清掉"
print("promote basic ok")

# 超长输出到点：log 是全文，spill 文件并进去后删掉
spill_dir = os.path.join(runner.PROJECTS_ROOT, "p1", ".spill")
cmd = "python3 -c \"print('x'*30000)\"; sleep 1.5; echo tail-line"
r = runner._exec("p1", cmd, 1, promote=("j00000c", 60))
assert r["promoted"] == "j00000c" and runner.SPILL_MARK in r["output"] and r["omitted"] > 0, {k: v for k, v in r.items() if k != "output"}
assert r["spill"] == ".jobs/j00000c/log", r
assert not os.listdir(spill_dir) if os.path.isdir(spill_dir) else True, os.listdir(spill_dir)
wait_for(f"{J('j00000c')}/exit")
log = open(f"{J('j00000c')}/log").read()
assert log == "x" * 30000 + "\ntail-line\n", (len(log), log[-30:])
print("promote long output ok")

# 整组杀（沙盒 /jobs/cancel 的做法）能停掉它，照样写出 exit
r = runner._exec("p1", "echo up; sleep 30", 1, promote=("j00000d", 60))
g = int(open(f"{J('j00000d')}/pid").read())
os.killpg(g, signal.SIGTERM)
wait_for(f"{J('j00000d')}/exit")
assert open(f"{J('j00000d')}/exit").read().strip() in ("124", "143", "-15"), open(f"{J('j00000d')}/exit").read()

# 转后台后的上限是 promote 给的秒数（包装脚本的 timeout 换掉了）
r = runner._exec("p1", "sleep 5", 1, promote=("j00000e", 2))
wait_for(f"{J('j00000e')}/exit")
assert open(f"{J('j00000e')}/exit").read().strip() == "124"

# 不带 promote：照旧到点杀
r = runner._exec("p1", "sleep 5", 1)
assert r["timed_out"] is True and "promoted" not in r

# /exec/stream：最后一行带 promoted；坏任务 id 400
async def collect(body):
    resp = await runner.exec_stream(runner.ExecIn(**body))
    return [json.loads(line) async for line in resp.body_iterator]
lines = asyncio.run(collect({"project_id": "p1", "command": "echo s1; sleep 1.5", "timeout": 1,
                             "promote_job": "j00000f", "promote_max": 60}))
assert lines[-1]["type"] == "exit" and lines[-1]["promoted"] == "j00000f" and lines[-1]["output"] == "s1\n", lines
assert "".join(l["data"] for l in lines if l["type"] == "out") == "s1\n", lines
wait_for(f"{J('j00000f')}/exit")
try:
    asyncio.run(collect({"project_id": "p1", "command": "true", "promote_job": "../x"}))
    raise AssertionError("坏任务 id 应 400")
except runner.HTTPException as e:
    assert e.status_code == 400
print("promote runner ok")

# ---- 2. 后端 ----
from app import jobs, llm, sandbox_client, storage
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.blocks import Block, text_to_blocks
from app.config import settings
from app.db import SessionLocal
from app.models import Conversation, Job, Message, Project
from pydantic import TypeAdapter
from sqlalchemy import select
load_builtin()

async def seed():
    async with SessionLocal() as db:
        p = Project(name="实验", emoji="🧪"); db.add(p); await db.flush()
        conv = Conversation(title="装依赖", project_id=p.id); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("装一下")))
        await db.commit()
        return p.id, conv.id
pid, cid = asyncio.run(seed())

calls = []
async def fake_stream(project_id, command, timeout=60, stdin=None, env=None, promote=None):
    calls.append((command, timeout, promote))
    yield {"type": "out", "data": "Collecting torch\n"}
    if promote and command.startswith("pip"):
        jid = promote[0]
        d = storage.project_dir(project_id) / ".jobs" / jid
        d.mkdir(parents=True)
        (d / "cmd.sh").write_text(command + "\n")
        (d / "log").write_text("Collecting torch\n")
        (d / "pid").write_text("4242\n")
        yield {"type": "exit", "exit_code": None, "timed_out": False, "promoted": jid, "waited": timeout,
               "output": "Collecting torch\n"}
        return
    yield {"type": "exit", "exit_code": 124, "timed_out": True, "output": "Collecting torch\n"}
sandbox_client.stream = fake_stream

async def tool(name, **args):
    async with SessionLocal() as db:
        return await REGISTRY[name].run(ToolContext(db=db, project_id=pid, conversation_id=cid), **args)

res = asyncio.run(tool("run_command", command="pip install torch", timeout=30))
jid = calls[-1][2][0]
assert calls[-1][1] == 30 and calls[-1][2] == (jid, settings.job_max_seconds), calls
assert not res.failed, res.failed
assert jid in res.content and "没有被杀" in res.content and "Collecting torch" in res.content and "cancel_job" in res.content, res.content
assert len(res.blocks) == 1 and res.blocks[0]["type"] == "job" and res.blocks[0]["promoted"] is True, res.blocks
assert res.blocks[0]["state"] == "running" and res.blocks[0]["command"] == "pip install torch"
TypeAdapter(Block).validate_python(res.blocks[0])

async def get(jid):
    async with SessionLocal() as db:
        return await db.get(Job, jid)
job = asyncio.run(get(jid))
assert job.promoted and job.state == "running" and job.conversation_id == cid and job.project_id == pid
assert job.read_offset == len("Collecting torch\n"), job.read_offset  # 到目前的输出已给过模型
assert job.timeout == settings.job_max_seconds and job.idle_timeout == jobs.idle_limit(None, settings.job_max_seconds)
assert jobs.wire(job)["promoted"] is True and "前台命令转入后台" in jobs.describe(job)
async def adopt_back():  # 开始时间往前推（它已经跑了这么久）
    async with SessionLocal() as db:
        j = await jobs.adopt(db, job_id="j0000ab12", project_id=pid, command="make\nall", seconds=90)
        return jobs.elapsed(j), j.title
el, ttl = asyncio.run(adopt_back())
assert 90 <= el <= 92 and ttl == "make", (el, ttl)

# 之后：命令写完 → refresh 结算 + 等着通知
d = storage.project_dir(pid) / ".jobs" / jid
with open(d / "log", "a") as f:
    f.write("Successfully installed torch\n")
(d / "exit").write_text("0\n")
async def settle():
    async with SessionLocal() as db:
        j = await db.get(Job, jid)
        await jobs.refresh(db, j)
        return j.state, j.followup, j.tail, jobs.block(j)
state, followup, tail, blk = asyncio.run(settle())
assert state == "done" and followup == "pending" and "Successfully installed torch" in tail, (state, followup, tail)
assert blk["promoted"] is True and blk["state"] == "done"
print("adopt + settle ok")

# job_status 只给转后台之后的新输出
async def status():
    async with SessionLocal() as db:
        return await REGISTRY["job_status"].run(ToolContext(db=db, project_id=pid, conversation_id=cid), job_id=jid)
st = asyncio.run(status())
assert "Successfully installed torch" in st.content and st.content.count("Collecting torch") == 0, st.content

# 后台任务满了：不带 promote，到点照旧杀，提示里说原因
async def fill():
    async with SessionLocal() as db:
        for i in range(settings.job_max_running):
            db.add(Job(id=f"jfull{i:02d}aa", project_id=pid, title="x", command="sleep", timeout=60, state="running"))
        await db.commit()
asyncio.run(fill())
res = asyncio.run(tool("run_command", command="pip install big", timeout=10))
assert calls[-1][2] is None, calls[-1]
assert res.failed and "没能转入后台" in res.content and "上限" in res.content, res.content
assert res.blocks[0]["type"] == "code"

# 用户自己 ! 跑的命令：不转后台
from app import user_shell
assert "promote" not in open(user_shell.__file__).read()
print("smoke_promote ok")
