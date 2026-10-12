# 冒烟：v1.92 后台任务内存（app/job_memory.py；jobs.script 的 oom_score_adj、memcap 标记；sandbox GROUPS_PY 的 box）。
# 1) parse / reason / note / box_note / box_usage 规则；2) run.sh 普通任务调高 oom_score_adj，常驻不调；
# 3) 真任务吃 200 MB、上限 100 MB → worker tick 结束它：失败 + 原因 + 峰值 + 通知；小任务只记峰值；
# 4) 采样节奏；5) 沙盒连不上 → 撤回标记下轮再来；6) 常驻服务超限 → 排队重启、重启日志写明原因；
# 7) 模拟模型 run_command memory_limit（好 / 坏 / 前台拒绝）、job_status 上限与“整台快满了”、GET /api/jobs/{id} box；8) 迁移。
# 运行：python tests/smoke_job_memory.py
import os, sys, asyncio, subprocess, tempfile, json, signal, time, types, re
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, JOB_MAX_RUNNING="6",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

# ---- 假 docker：exec_run 在本机执行（GROUPS_PY 真读本机 /proc）----
class NotFound(Exception):
    pass
containers: dict = {}
execs: list = []
class FakeContainer:
    def __init__(self, name, status="running"):
        self.name, self.status, self.id = name, status, name
    def exec_run(self, cmd, **kw):
        execs.append(cmd)
        p = subprocess.run(cmd, capture_output=True)
        return NS(exit_code=p.returncode, output=p.stdout)
def get(name):
    if name not in containers:
        raise NotFound(name)
    return containers[name]
fake_client = NS(containers=NS(get=get, list=lambda **kw: [], run=None), images=NS(get=lambda name: NS(id="img")),
                 networks=NS(get=lambda name: (_ for _ in ()).throw(NotFound(name))), api=NS())
docker_mod = types.ModuleType("docker"); docker_mod.from_env = lambda: fake_client
errors_mod = types.ModuleType("docker.errors"); errors_mod.NotFound = NotFound
docker_mod.errors = errors_mod
sys.modules.update({"docker": docker_mod, "docker.errors": errors_mod})
os.environ.update(SANDBOX_TOKEN="t", HOST_PROJECTS_DIR=tmp, SANDBOX_CPUS="1")
sys.path.insert(0, os.path.join(root, "..", "sandbox"))
import runner
runner.STATE_FILE = os.path.join(tmp, "state", "stopped.json")


# ---- 1. 纯规则 ----
from datetime import datetime, timezone, timedelta
import httpx
from app import jobs, job_usage, job_memory, llm, preview, sandbox_client, storage, quota
from app.models import Job
P = job_memory.parse
M, G = 1 << 20, 1 << 30
for v, want in [("512m", 512 * M), ("2g", 2 * G), ("1.5GB", int(1.5 * G)), ("800MiB", 800 * M), (" 256 M ", 256 * M),
                ("300", 300 * M), (300, 300 * M), ("65536k", 64 * M), (None, None), ("", None), (0, None), ("0m", None)]:
    assert P(v) == want, (v, P(v))
for bad in ("abc", "12x", "-5m", "1e3m", True, "10m", "65g", [1]):
    try:
        P(bad)
    except (ValueError, TypeError) as e:
        assert isinstance(e, ValueError) or bad == [1], bad
        continue
    raise AssertionError(bad)
r = job_memory.reason(512 * M, 530 * M)
assert r.startswith(jobs.MEMCAP_PREFIX) and "512 MB" in r and "530 MB" in r and len(r) <= 120, r
j0 = Job(id="jx", project_id="w", title="大任务", command="x", state="running", memory_max=100 * M)
assert job_memory.note(j0, {"memory": 85 * M}) == "（上限 100 MB，已到 85%，再涨会被结束）"
assert job_memory.note(j0, {"memory": 10 * M}) == "（上限 100 MB）"
assert job_memory.note(Job(id="jy", project_id="w", title="t", command="x"), {"memory": 1}) == ""
assert job_memory.over(j0, {"memory": 101 * M}) and not job_memory.over(j0, {"memory": 100 * M}) and not job_memory.over(j0, None)
assert not job_memory.tight(None) and not job_memory.tight({"used": 89, "limit": 100}) and job_memory.tight({"used": 90, "limit": 100})
n = job_memory.box_note({"used": 3800 * M, "limit": 4 * G}, (j0, {"memory": 2 * G}))
assert "93%" in n and "jx「大任务」约 2 GB" in n and "memory_limit" in n, n
assert job_memory.box_note({"used": 1, "limit": 4 * G}) == ""
# 沙盒侧 box 解析
bu = runner.box_usage
assert bu(json.dumps({"box": {"used": 5, "limit": 10}})) == {"used": 5, "limit": 10}
assert bu(json.dumps({"box": {"used": 50, "limit": 10}})) == {"used": 10, "limit": 10}
for bad in ("", "x", json.dumps({"box": None}), json.dumps({"box": {"used": 1, "limit": None}}),
            json.dumps({"box": {"used": 1, "limit": 1 << 62}}), json.dumps({"box": {"used": -1, "limit": 9}}),
            json.dumps({"box": {"used": True, "limit": 9}})):
    assert bu(bad) is None, bad
p = subprocess.run(["python3", "-c", runner.GROUPS_PY, "0.05", "1"], capture_output=True, text=True)
assert "box" in json.loads(p.stdout), p.stdout  # 本机读不到 cgroup 也要有这个键（None）
assert job_usage.box_wire({"used": 3, "limit": 2}) == {"used": 2, "limit": 2} and job_usage.box_wire({"used": 1}) is None
print("1 rules ok")

# ---- 2. run.sh：普通任务调高 oom_score_adj，常驻不调 ----
assert "oom_score_adj" in jobs.script("j1", 60) and "oom_score_adj" not in jobs.script("j1", 0, keep_alive=True)
print("2 script ok")

# ---- 3. 真后台任务 ----
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.auth import require_user
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message, Project
from app.routes import jobs as rj
gcalls: list = []
gmode = {"box": None, "fail_cancel": False}
async def fake_groups(ws, pgids):
    gcalls.append((ws, tuple(pgids)))
    p = await asyncio.to_thread(subprocess.run, ["python3", "-c", runner.GROUPS_PY, "0.1", *map(str, pgids)],
                                capture_output=True, text=True)
    return {"state": "running", "groups": runner.group_usage(p.stdout), "box": gmode["box"]}
sandbox_client.groups = fake_groups
procs: dict[str, subprocess.Popen] = {}
async def start_job(pid, jid, env=None):
    procs[jid] = subprocess.Popen(["bash", f".jobs/{jid}/run.sh"], cwd=storage.project_dir(pid), start_new_session=True)
def _pid(pid, jid):
    try:
        return int((storage.project_dir(pid) / ".jobs" / jid / "pid").read_text())
    except (FileNotFoundError, ValueError):
        return None
async def cancel_job(pid, jid):
    if (p := _pid(pid, jid)) is not None:
        try:
            os.killpg(p, signal.SIGTERM)
        except ProcessLookupError:
            pass
    procs[jid].wait(10)
async def job_alive(pid, jid):
    p = _pid(pid, jid)
    if p is None:
        return False
    try:
        os.kill(p, 0); return True
    except ProcessLookupError:
        return False
async def status(ws):
    return {"state": "running"}
async def listening(ws):
    return {"ports": []}
sandbox_client.start_job, sandbox_client.cancel_job, sandbox_client.job_alive = start_job, cancel_job, job_alive
sandbox_client.status, preview.listening = status, listening

script: list = []
seen: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append([dict(m) for m in messages])
    step = script.pop(0)
    async def gen():
        if isinstance(step, tuple):
            yield chunk(tool=[NS(index=0, id=f"c{len(script)}", function=NS(name=step[0], arguments=json.dumps(step[1])))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()


_real_cancel = cancel_job
async def maybe_cancel(pid, jid):
    if gmode["fail_cancel"]:
        raise httpx.ConnectError("down")
    await _real_cancel(pid, jid)
sandbox_client.cancel_job = maybe_cancel

app = FastAPI(); app.include_router(rj.router)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
async def seed():
    async with SessionLocal() as db:
        p = Project(name="数据", emoji="🧪"); db.add(p); await db.flush()
        conv = Conversation(title="跑", project_id=p.id); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("处理数据")))
        await db.commit()
        return p.id, conv.id
pid, cid = asyncio.run(seed())
async def start(cmd, **kw):
    async with SessionLocal() as db:
        return (await jobs.start(db, project_id=pid, command=cmd, conversation_id=cid, **kw)).id
async def get(jid):
    async with SessionLocal() as db:
        return await db.get(Job, jid)
async def mtick():
    async with SessionLocal() as db:
        return await job_memory.tick(db)
async def jtick():
    async with SessionLocal() as db:
        return await jobs.tick(db)
def wait_pid(*ids):
    end = time.time() + 5
    while any(_pid(pid, i) is None for i in ids) and time.time() < end:
        time.sleep(0.05)
    time.sleep(0.4)
HOG = "python3 -c \"import time; b = bytearray(200 * 1024 * 1024); b[::4096] = b'x' * len(b[::4096]); print('hog', flush=True); time.sleep(60)\""
hog = asyncio.run(start(HOG, title="吃内存", memory_max=100 * M))
small = asyncio.run(start("sleep 60", title="小任务"))
wait_pid(hog, small)
# oom_score_adj：普通任务的进程组都调高了
adj = int(open(f"/proc/{_pid(pid, small)}/oom_score_adj").read())
assert adj >= jobs.OOM_ADJ, adj  # 调高（调低要特权：父进程已经更高时保持原值）
job_memory.forget(); job_usage.forget()
killed = asyncio.run(mtick())
assert killed == [hog], killed
h = asyncio.run(get(hog))
assert h.state == "failed" and h.stop_reason.startswith(jobs.MEMCAP_PREFIX) and "100 MB" in h.stop_reason, (h.state, h.stop_reason)
assert h.memory_peak and h.memory_peak > 150 * M, h.memory_peak
d = jobs.describe(h)
assert "失败：内存超过给它定的上限" in d and "内存峰值约" in d and "memory_limit" in d, d
blk = jobs.block(h)
assert blk["memory_max"] == 100 * M and blk["memory_peak"] == h.memory_peak and blk["stop_reason"] == h.stop_reason
assert h.followup == "pending"  # 助手会在原对话接着说
s = asyncio.run(get(small))
assert s.state == "running" and s.memory_peak and s.memory_peak < 50 * M, s.memory_peak
print("3 cap kill ok")

# ---- 4. 节奏：没设上限的工作区 PEAK_EVERY_S 才采；峰值没涨 5% 不写 ----
gcalls.clear(); job_usage.forget()
asyncio.run(mtick())
assert gcalls == [], gcalls  # 刚采过
job_memory._sampled.clear(); job_usage.forget()
before = asyncio.run(get(small)).memory_peak
asyncio.run(mtick())
assert len(gcalls) == 1 and asyncio.run(get(small)).memory_peak == before
print("4 rhythm ok")

# ---- 5. 杀不成：撤回标记，下一轮再来 ----
hog2 = asyncio.run(start(HOG, title="又吃内存", memory_max=64 * M))
wait_pid(hog2)
gmode["fail_cancel"] = True
job_usage.forget()
assert asyncio.run(mtick()) == []
h2 = asyncio.run(get(hog2))
assert h2.state == "running" and not (jobs.job_dir(h2) / jobs.MEMCAP).exists()
gmode["fail_cancel"] = False
job_usage.forget()
assert asyncio.run(mtick()) == [hog2] and asyncio.run(get(hog2)).state == "failed"
print("5 sandbox down ok")

# ---- 6. 常驻服务超限：照崩溃处理，排队重启；重启日志写明上次原因 ----
svc = asyncio.run(start(HOG, title="服务", keep_alive=True, memory_max=64 * M))
wait_pid(svc)
base_adj = int(open("/proc/self/oom_score_adj").read())
assert int(open(f"/proc/{_pid(pid, svc)}/oom_score_adj").read()) == base_adj  # 常驻不调高（沿用父进程的）
job_usage.forget()
assert asyncio.run(mtick()) == [svc]
v = asyncio.run(get(svc))
assert v.state == "running" and v.restart_at is not None and v.crash_streak == 1, (v.state, v.restart_at)
async def due_now():
    async with SessionLocal() as db:
        x = await db.get(Job, svc); x.restart_at = datetime.now(timezone.utc); await db.commit()
asyncio.run(due_now())
asyncio.run(jtick())
v = asyncio.run(get(svc))
assert v.restarts == 1 and v.restart_at is None, (v.restarts, v.restart_at)
log = (jobs.job_dir(v) / "log").read_text()
assert "第 1 次重启（上次：内存超过给它定的上限" in log, log
assert not (jobs.job_dir(v) / jobs.MEMCAP).exists()
c.post(f"/api/jobs/{svc}/cancel")
print("6 keep-alive ok")

# ---- 7. 工具 + REST ----
script: list = []
seen: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append([dict(m) for m in messages])
    step = script.pop(0)
    async def gen():
        if isinstance(step, tuple):
            yield chunk(tool=[NS(index=0, id=f"c{len(script)}", function=NS(name=step[0], arguments=json.dumps(step[1])))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid))
def last_tool():
    return [m for m in seen[-1] if m["role"] == "tool"][-1]["content"]
script[:] = [("run_command", {"command": "sleep 30", "background": True, "memory_limit": "128m", "title": "限内存"}), "好。"]
asyncio.run(turn())
assert "内存上限 128 MB" in last_tool(), last_tool()
async def newest():
    from sqlalchemy import select
    async with SessionLocal() as db:
        return (await db.scalars(select(Job).where(Job.title == "限内存"))).one()
tj = asyncio.run(newest())
assert tj.memory_max == 128 * M
script[:] = [("run_command", {"command": "sleep 1", "background": True, "memory_limit": "abc"}), "好。"]
asyncio.run(turn())
assert last_tool().startswith("没有启动：memory_limit 要写成"), last_tool()
script[:] = [("run_command", {"command": "echo hi", "memory_limit": "1g"}), "好。"]
asyncio.run(turn())
assert "memory_limit 只对后台任务有效" in last_tool(), last_tool()
wait_pid(tj.id)
gmode["box"] = {"used": 3900 * M, "limit": 4 * G}
job_usage.forget()
script[:] = [("job_status", {"job_id": tj.id}), "好。"]
asyncio.run(turn())
t = last_tool()
assert "（上限 128 MB）" in t and "这台电脑内存已用 95%" in t, t
job_usage.forget()
script[:] = [("job_status", {}), "好。"]
asyncio.run(turn())
t = last_tool()
assert "这台电脑内存已用 95%" in t and "最大的是后台任务" in t, t
job_usage.forget()
r = c.get(f"/api/jobs/{tj.id}").json()
assert r["memory_max"] == 128 * M and r["box"] == {"used": 3900 * M, "limit": 4 * G} and r["usage"], r
gmode["box"] = None
job_usage.forget()
assert c.get(f"/api/jobs/{tj.id}").json()["box"] is None
for x in (small, tj.id):
    c.post(f"/api/jobs/{x}/cancel")
r = c.get(f"/api/jobs/{small}").json()
assert r["box"] is None and r["usage"] is None and r["memory_peak"]
print("7 tool + REST ok")

# ---- 8. 迁移 ----
for args in (["downgrade", "0042"], ["upgrade", "head"]):
    r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
print("8 migration ok")
print("smoke_job_memory OK")
