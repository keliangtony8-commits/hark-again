# 冒烟：v1.90 每个后台任务占多少 CPU / 内存（sandbox/runner.py GROUPS_PY + group_usage + GET /sandboxes/{id}/groups，
# backend app/job_usage.py，GET /api/jobs/{id} 的 usage、电脑状态里任务行 / 常驻服务的 usage、job_status 工具的那句话）。
# 1) group_usage 纯函数：CPU 按配额折算并封顶 100、坏输出 → 空、坏行跳过、上限；
# 2) GROUPS_PY 在本机真跑：一个吃满 CPU 的进程组 → cpu 明显 > 0、进程数对、内存 > 0；空闲组 cpu≈0；
#    子进程中途退出（被 wait 收走）不会让 CPU 变负或翻倍；不在要的组里的进程不算；
# 3) 沙盒路由（docker 换假的，exec_run 本机执行）：容器没开 → off 不开机；没给 pgid → 空；坏 pgid 丢掉；
# 4) 后端 job_usage：只问在跑且不在等重启的任务；同工作区合并一次请求；缓存 CACHE_S 内不再问；并发共用一次；
#    沙盒连不上 → 没有 usage（不是 0）；坏数据丢掉；text() 措辞；
# 5) 真后台任务（本机 bash 顶替沙盒，run.sh 真跑）：GET /api/jobs/{id} 带 usage，结束后为 null；电脑状态 running_jobs /
#    services 带 usage；模拟模型调 job_status → 工具结果里有“现在占 CPU”。无新迁移。
# 运行：python tests/smoke_job_usage.py
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

# ---- 1. group_usage ----
gu = runner.group_usage
def out(tck=100, secs=0.5, groups=()):
    return "noise\n" + json.dumps({"tck": tck, "seconds": secs, "groups": list(groups)})
g = {"pgid": 7, "delta": 25, "ticks": 300, "memory": 50 << 20, "processes": 2}
assert gu(out(groups=[g]), cpus=1) == [{"pgid": 7, "cpu": 50.0, "cpu_seconds": 3.0, "memory": 50 << 20, "processes": 2}]
assert gu(out(groups=[g]), cpus=2)[0]["cpu"] == 25.0  # 占配额：两核配额时同样的节拍只算一半
assert gu(out(groups=[{**g, "delta": 500}]), cpus=1)[0]["cpu"] == 100.0  # 封顶
for bad in ("", "not json", json.dumps({"tck": 0, "seconds": 1, "groups": []}), json.dumps({"tck": 100, "seconds": 0, "groups": [g]}),
            json.dumps({"tck": 100, "seconds": 1, "groups": "x"}), json.dumps({"tck": 100})):
    assert gu(bad) == [], bad
rows = gu(out(groups=[{"pgid": "x"}, {**g, "pgid": 0}, {**g, "processes": 0}, {**g, "memory": -1}, {**g, "pgid": 9}]))
assert [r["pgid"] for r in rows] == [9], rows
assert len(gu(out(groups=[{**g, "pgid": i} for i in range(1, 50)]))) == runner.GROUPS_MAX
print("1 group_usage ok")

# ---- 2. GROUPS_PY 本机真跑 ----
def sample(*pgids, gap=0.5):
    p = subprocess.run(["python3", "-c", runner.GROUPS_PY, str(gap), *map(str, pgids)], capture_output=True, text=True)
    return {r["pgid"]: r for r in gu(p.stdout, cpus=1)}
hot = subprocess.Popen(["bash", "-c", 'python3 -c "while 1: pass" & python3 -c "while 1: pass" & sleep 30'], start_new_session=True)
idle = subprocess.Popen(["bash", "-c", "sleep 30"], start_new_session=True)
# 子进程反复起来又退出（被 bash wait 收走 → 节拍进 cutime）：CPU 不能变负、也不能超过它真用的
churn = subprocess.Popen(["bash", "-c", 'for i in $(seq 200); do python3 -c "sum(range(300000))"; done'], start_new_session=True)
time.sleep(0.5)
s = sample(hot.pid, idle.pid, churn.pid)
assert s[hot.pid]["processes"] >= 3 and s[hot.pid]["cpu"] > 30, s[hot.pid]   # 两个死循环（单核机器上至少 30%）
assert s[hot.pid]["memory"] > 0 and s[hot.pid]["cpu_seconds"] > 0
assert s[idle.pid]["cpu"] < 5 and s[idle.pid]["processes"] == 1, s[idle.pid]
assert 0 <= s[churn.pid]["cpu"] <= 100, s[churn.pid]
assert set(s) == {hot.pid, idle.pid, churn.pid}  # 别的进程组（包括这个测试自己）不算
assert sample(999999) == {}  # 不存在的组
for p in (hot, idle, churn):
    os.killpg(p.pid, signal.SIGKILL); p.wait()
print("2 GROUPS_PY ok")

# ---- 3. 沙盒路由 ----
from fastapi.testclient import TestClient as TC
sc = TC(runner.app)
H = {"Authorization": "Bearer t"}
assert sc.get("/sandboxes/abc/groups?pgid=1", headers=H).json() == {"state": "off", "groups": []}
containers["sbx-abc"] = FakeContainer("sbx-abc", status="exited")
n = len(execs)
assert sc.get("/sandboxes/abc/groups?pgid=1", headers=H).json() == {"state": "off", "groups": []}
assert len(execs) == n  # 停着的不开机、不执行
containers["sbx-abc"].status = "running"
assert sc.get("/sandboxes/abc/groups", headers=H).json() == {"state": "running", "groups": []} and len(execs) == n
mine = subprocess.Popen(["bash", "-c", "sleep 20"], start_new_session=True)
time.sleep(0.2)
got = sc.get(f"/sandboxes/abc/groups?pgid={mine.pid}&pgid=-3&pgid=0", headers=H).json()
assert got["state"] == "running" and [r["pgid"] for r in got["groups"]] == [mine.pid], got
assert execs[-1][-1] == str(mine.pid) and "-3" not in execs[-1]
assert sc.get("/sandboxes/abc/groups?pgid=1", headers={"Authorization": "Bearer x"}).status_code == 401
assert sc.get("/sandboxes/abc/groups?pgid=x", headers=H).status_code == 422
os.killpg(mine.pid, signal.SIGKILL); mine.wait()
print("3 sandbox route ok")

# ---- 4. 后端 job_usage ----
from datetime import datetime, timezone
import httpx
from app import jobs, job_usage, llm, sandbox_client, storage
from app.models import Job

calls: list = []
mode = {"fail": False, "delay": 0.0, "junk": False}
async def fake_groups(ws, pgids):
    calls.append((ws, tuple(pgids)))
    if mode["delay"]:
        await asyncio.sleep(mode["delay"])
    if mode["fail"]:
        raise httpx.ConnectError("down")
    if mode["junk"]:
        return {"state": "running", "groups": [{"pgid": pgids[0], "cpu": "x"}, "bad", {"pgid": "1"}]}
    # 用真的采样：本机 /proc（等于沙盒里那段）
    p = await asyncio.to_thread(subprocess.run, ["python3", "-c", runner.GROUPS_PY, "0.2", *map(str, pgids)],
                                capture_output=True, text=True)
    return {"state": "running", "groups": runner.group_usage(p.stdout)}
sandbox_client.groups = fake_groups

def fake_job(jid, ws, pg, state="running", restart_at=None):
    d = storage.project_dir(ws) / ".jobs" / jid
    d.mkdir(parents=True, exist_ok=True)
    if pg is not None:
        (d / "pid").write_text(f"{pg}\n")
    return Job(id=jid, project_id=ws, title=jid, command="x", state=state, restart_at=restart_at)

a = subprocess.Popen(["bash", "-c", 'python3 -c "while 1: pass" & sleep 30'], start_new_session=True)
b = subprocess.Popen(["bash", "-c", "sleep 30"], start_new_session=True)
time.sleep(0.3)
J = [fake_job("j1", "w1", a.pid), fake_job("j2", "w1", b.pid), fake_job("j3", "w2", b.pid),
     fake_job("j4", "w1", a.pid, state="done"), fake_job("j5", "w1", a.pid, restart_at=datetime.now(timezone.utc)),
     fake_job("j6", "w1", None)]
got = asyncio.run(job_usage.for_jobs(J))
assert set(got) == {"j1", "j2", "j3"}, got  # 结束的 / 等重启的 / 没 pid 的不问
assert sorted(calls) == sorted([("w1", tuple(sorted((a.pid, b.pid)))), ("w2", (b.pid,))]), calls  # 每个工作区一次
assert got["j1"]["cpu"] > got["j2"]["cpu"] and got["j1"]["processes"] >= 2, got
assert set(got["j1"]) == set(job_usage.FIELDS)
calls.clear()
again = asyncio.run(job_usage.for_jobs([J[0]]))  # 缓存内、子集 → 不再问
assert calls == [] and again["j1"] == got["j1"]
job_usage.forget()
async def both():
    return await asyncio.gather(job_usage.of(J[0]), job_usage.of(J[0]))
mode["delay"] = 0.2
x, y = asyncio.run(both())
assert len(calls) == 1 and x == y and x is not None, calls  # 并发共用一次
mode["delay"] = 0
job_usage.forget(); calls.clear()
mode["fail"] = True
assert asyncio.run(job_usage.of(J[0])) is None and len(calls) == 1  # 连不上 → 没有（不是 0）
mode["fail"] = False
job_usage.forget()
mode["junk"] = True
assert asyncio.run(job_usage.of(J[0])) is None
mode["junk"] = False
job_usage.forget()
for p in (a, b):
    os.killpg(p.pid, signal.SIGKILL); p.wait()
assert job_usage.wire({"cpu": 1, "cpu_seconds": 2, "memory": 3, "processes": 0}) is None
assert job_usage.wire({"cpu": -1, "cpu_seconds": 2, "memory": 3, "processes": 1}) is None
t = job_usage.text({"cpu": 35.0, "cpu_seconds": 125, "memory": 120 << 20, "processes": 3})
assert t == "现在占 CPU 35%、内存约 120 MB（3 个进程），累计 CPU 2 分 5 秒", t
assert job_usage.text({"cpu": 0.5, "cpu_seconds": 3, "memory": 2 << 30, "processes": 1}) == "现在占 CPU 0.5%、内存约 2.0 GB，累计 CPU 3 秒"
assert job_usage.text(None) == "" and job_usage.size_text(100) == "1 KB"
print("4 job_usage ok")

# ---- 5. 真后台任务 + 路由 + 电脑状态 + 工具 ----
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import computer, preview
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.auth import require_user
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message, Project
from app.routes import jobs as rj

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

app = FastAPI(); app.include_router(rj.router)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)

async def seed():
    async with SessionLocal() as db:
        p = Project(name="训练", emoji="🧪"); db.add(p); await db.flush()
        conv = Conversation(title="跑", project_id=p.id); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("看看后台任务占多少")))
        await db.commit()
        return p.id, conv.id
pid, cid = asyncio.run(seed())
async def start(cmd, **kw):
    async with SessionLocal() as db:
        return (await jobs.start(db, project_id=pid, command=cmd, conversation_id=cid, **kw)).id
burn = asyncio.run(start('python3 -c "while 1: pass"', title="烧 CPU"))
svc = asyncio.run(start("sleep 60", title="服务", keep_alive=True))
end = time.time() + 5
while (_pid(pid, burn) is None or _pid(pid, svc) is None) and time.time() < end:
    time.sleep(0.05)
time.sleep(0.3)
job_usage.forget()
j = c.get(f"/api/jobs/{burn}").json()
assert j["state"] == "running" and j["usage"]["cpu"] > 30 and j["usage"]["processes"] >= 1, j
async def st():
    async with SessionLocal() as db:
        return await computer.status(db, pid)
job_usage.forget(); calls.clear()
s = asyncio.run(st())
assert len(calls) == 1, calls  # 任务行和服务一起一次问齐
rowj = next(x for x in s["running_jobs"] if x["id"] == burn)
assert rowj["usage"]["cpu"] > 30, rowj
rows = [x for x in s["services"] if x["id"] == svc]
assert rows and rows[0]["usage"] is not None and rows[0]["usage"]["cpu"] < 5, rows

script[:] = [("job_status", {"job_id": burn}), "它在吃满 CPU。"]
job_usage.forget()
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid))
asyncio.run(turn())
tool_msg = next(m for m in seen[-1] if m["role"] == "tool")
assert "现在占 CPU" in tool_msg["content"] and "烧 CPU" in tool_msg["content"], tool_msg["content"]
script[:] = [("job_status", {}), "好。"]
asyncio.run(turn())
tool_msg = [m for m in seen[-1] if m["role"] == "tool"][-1]["content"]
assert tool_msg.count("现在占 CPU") == 2, tool_msg  # 列表里两个在跑的都带

c.post(f"/api/jobs/{burn}/cancel")
job_usage.forget()
j = c.get(f"/api/jobs/{burn}").json()
assert j["state"] == "cancelled" and j["usage"] is None, j
c.post(f"/api/jobs/{svc}/cancel")
print("5 real jobs ok")
print("smoke_job_usage OK")
