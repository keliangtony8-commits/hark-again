# 冒烟：v1.25 工作区“电脑”状态 + 重启（app/computer.py、GET/POST /api/projects/{ws}/computer、sandbox/runner.py /sandboxes/{id}/status）。
# 1) 真 runner（docker 换假的）：没开过机 / 休眠 / 运行中（内存 = usage − inactive_file，开机时间解析，镜像过期）、非法 id 400、删容器清 last_used；
# 2) disk_usage：算隐藏目录、不跟随符号链接、数太多标 partial；
# 3) 接口：个人工作区 me + 项目；未知工作区 404；沙盒连不上 → unreachable 但磁盘和任务照给；
# 4) 正在跑的后台任务（本机 bash 真跑 run.sh）出现在状态里；重启 → 任务按用户取消（照常通知）、容器删掉、列表清空；
#    沙盒连不上时重启 503，任务不受影响。
# 运行：python tests/smoke_computer.py
import os, sys, asyncio, subprocess, tempfile, json, signal, time, types
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import computer, jobs, sandbox_client, storage
from app.auth import require_user
from app.db import SessionLocal
from app.models import Conversation, Job, Project
from app.routes import files as rf

# ---- 1. 真 runner：docker 换假的 ----
class NotFound(Exception):
    pass
containers: dict = {}
class FakeContainer:
    def __init__(self, status, image="img", mem=None, started="2026-10-12T05:01:02.123456789Z"):
        self.status, self.image, self.mem = status, NS(id=image), mem
        self.attrs = {"State": {"StartedAt": started}}
        self.removed = False
    def stats(self, stream=False):
        if self.mem is None:
            raise RuntimeError("no stats")
        return {"memory_stats": self.mem}
    def remove(self, force=False):
        self.removed = True
        containers.pop(self.name, None)
def get(name):
    if name not in containers:
        raise NotFound(name)
    return containers[name]
fake_client = NS(api=None, containers=NS(get=get, list=lambda **kw: []), images=NS(get=lambda name: NS(id="img")))
docker_mod = types.ModuleType("docker"); docker_mod.from_env = lambda: fake_client
errors_mod = types.ModuleType("docker.errors"); errors_mod.NotFound = NotFound
docker_mod.errors = errors_mod
sys.modules.update({"docker": docker_mod, "docker.errors": errors_mod})
os.environ.update(SANDBOX_TOKEN="t", HOST_PROJECTS_DIR=tmp)
sys.path.insert(0, os.path.join(root, "..", "sandbox"))
import runner

def put(name, c):
    c.name = name; containers[name] = c

st = asyncio.run(runner.status("me"))
assert st["state"] == "none" and st["memory_used"] is None and st["idle_minutes"] == runner.IDLE_MINUTES, st
put("sbx-me", FakeContainer("exited"))
st = asyncio.run(runner.status("me"))
assert st["state"] == "stopped" and st["memory_used"] is None and st["outdated"] is False, st
put("sbx-me", FakeContainer("running", mem={"usage": 500, "limit": 1000, "stats": {"inactive_file": 120}}))
st = asyncio.run(runner.status("me"))
assert st["state"] == "running" and st["memory_used"] == 380 and st["memory_limit"] == 1000, st
assert st["started_at"] == 1791781262.0, st["started_at"]  # 2026-10-12T05:01:02Z
put("sbx-me", FakeContainer("running", image="old", mem={"usage": 50, "limit": 1000, "stats": {"total_inactive_file": 80}}))
st = asyncio.run(runner.status("me"))
assert st["outdated"] is True and st["memory_used"] == 0, st
put("sbx-me", FakeContainer("running", mem=None, started="garbage"))
st = asyncio.run(runner.status("me"))
assert st["state"] == "running" and st["memory_used"] is None and st["started_at"] is None, st
try:
    asyncio.run(runner.status("../etc"))
    raise AssertionError("bad id accepted")
except runner.HTTPException as e:
    assert e.status_code == 400
runner.last_used["me"] = time.time()
c0 = containers["sbx-me"]
asyncio.run(runner.remove("me"))
assert c0.removed and "me" not in runner.last_used and "sbx-me" not in containers
asyncio.run(runner.remove("me"))  # 没有也不报错
print("runner ok")

# ---- 2. disk_usage ----
d = storage.project_dir("me")
(d / "a.txt").write_bytes(b"x" * 100)
(d / ".home" / ".local").mkdir(parents=True)
(d / ".home" / ".local" / "pkg.py").write_bytes(b"y" * 50)
os.symlink(d / "a.txt", d / "link.txt")
os.symlink(d / ".home", d / "homelink")
used, partial = computer.disk_usage(d)
assert used == 150 and partial is False, (used, partial)
assert computer.disk_usage(d, limit=2)[1] is True
print("disk ok")

# ---- 3/4. 接口 ----
procs: dict[str, subprocess.Popen] = {}
async def start_job(pid, jid):
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
    return _pid(pid, jid) is not None and procs[jid].poll() is None
up = {"ok": True}
restarted: list[str] = []
async def status(ws):
    if not up["ok"]:
        raise httpx.ConnectError("down")
    return {"state": "running", "memory_used": 300 * 2**20, "memory_limit": 2**30, "started_at": 1791781262.0,
            "outdated": False, "idle_minutes": 30, "last_used": 1791781300.0}
async def restart(ws):
    if not up["ok"]:
        raise httpx.ConnectError("down")
    restarted.append(ws)
sandbox_client.start_job, sandbox_client.cancel_job, sandbox_client.job_alive = start_job, cancel_job, job_alive
sandbox_client.status, sandbox_client.restart = status, restart

app = FastAPI()
app.include_router(rf.router)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)

async def seed():
    async with SessionLocal() as db:
        p = Project(name="爬虫", emoji="🕷"); db.add(p); await db.flush()
        conv = Conversation(title="跑爬虫"); db.add(conv); await db.flush()
        await db.commit()
        return p.id, conv.id
pid, cid = asyncio.run(seed())

j = c.get("/api/projects/me/computer").json()
assert j["workspace"] == "me" and j["name"] == "我的文件" and j["running_jobs"] == [], j
sb = j["sandbox"]
assert sb["state"] == "running" and sb["memory_used"] == 300 * 2**20 and sb["memory_limit"] == 2**30, sb
assert sb["started_at"] == "2026-10-12T05:01:02+00:00" and sb["last_used_at"].endswith("+00:00"), sb
assert j["disk_used"] == 150 and j["disk_partial"] is False, j
assert c.get(f"/api/projects/{pid}/computer").json()["name"] == "爬虫"
assert c.get("/api/projects/nope/computer").status_code == 404
assert c.post("/api/projects/nope/computer/restart").status_code == 404
assert not (storage.project_dir("nope")).exists() or not any(storage.project_dir("nope").iterdir())

async def start():
    async with SessionLocal() as db:
        job = await jobs.start(db, project_id="me", command="echo 开始; sleep 30", title="长任务", conversation_id=cid)
        return job.id
jid = asyncio.run(start())
for _ in range(50):
    if (storage.project_dir("me") / ".jobs" / jid / "log").exists() and _pid("me", jid):
        break
    time.sleep(0.1)
time.sleep(0.3)
j = c.get("/api/projects/me/computer").json()
assert [x["id"] for x in j["running_jobs"]] == [jid] and j["running_jobs"][0]["title"] == "长任务", j["running_jobs"]
assert "开始" in j["running_jobs"][0]["tail"]
assert c.get(f"/api/projects/{pid}/computer").json()["running_jobs"] == []  # 别的工作区看不到

up["ok"] = False
j = c.get("/api/projects/me/computer").json()
assert j["sandbox"] == {"state": "unreachable"} and len(j["running_jobs"]) == 1 and j["disk_used"] > 150, j
r = c.post("/api/projects/me/computer/restart")
assert r.status_code == 503 and "连不上" in r.json()["detail"], r.text
assert procs[jid].poll() is None and restarted == []  # 任务没被动
up["ok"] = True

r = c.post("/api/projects/me/computer/restart")
assert r.status_code == 200, r.text
assert restarted == ["me"] and r.json()["running_jobs"] == [], r.json()
assert procs[jid].poll() is not None
async def check():
    async with SessionLocal() as db:
        job = await db.get(Job, jid)
        assert job.state == "cancelled" and job.stop_reason is None and job.followup == "pending", (job.state, job.followup)
asyncio.run(check())
print("api ok")
print("ALL OK")
