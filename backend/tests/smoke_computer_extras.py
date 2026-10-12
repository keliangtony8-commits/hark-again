# 冒烟：v1.27 电脑页补齐 + 内存打满提示（app/computer.py storage_breakdown / installed_tools / cleanup，
# sandbox/runner.py cpu_percent / parse_ps / mem_bytes / status 进程与 OOM 计数 / cleanup，jobs.py run.sh 的 oom 标记，
# run_command 前台 OOM 文案）。
# 1) 真 runner（docker 换假的）：CPU 百分比（按配额归一、封顶 100）、ps 解析（去掉查看命令和占位进程、前 8）、内存规格换算、
#    运行中状态带进程和 OOM 次数、休眠不带、清理只在运行中做；
# 2) 磁盘拆分 + 装过的工具（pip dist-info / npm 含 @scope）+ 清理（存档、已结束任务日志、缓存删掉；运行中任务、文件、装的包不碰）；
# 3) 后台任务 OOM：本机 bash 跑真 run.sh，OOM 计数换成假文件 → failed + stop_reason + 给模型的出路；
# 4) 前台 run_command：沙盒报 oom → 卡片和模型都写明内存超上限 + 出路；普通 137 不说是内存；
# 5) 接口：GET 带 storage/tools/cpu/processes/oom_kills，POST cleanup 返回腾出字节 + 新状态（沙盒连不上也照清工作区）。
# 运行：python tests/smoke_computer_extras.py
import os, sys, asyncio, subprocess, tempfile, json, time, types
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
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.auth import require_user
from app.db import SessionLocal
from app.models import Job
from app.routes import files as rf
load_builtin()

# ---- 1. 真 runner ----
class NotFound(Exception):
    pass
containers: dict = {}
PS = ("    1     1  0.0  1000     99 sleep infinity\n"
      "   42    42 87.5 204800    185 python train.py --epochs 10\n"
      "   43    43  3.0  10240     20 node server.js\n"
      "   77    77  0.0   3000      0 ps -eo pid=,pgid=,pcpu=,rss=,etimes=,args= --sort=-pcpu\n"
      "garbage line\n")
class FakeContainer:
    def __init__(self, status, oom="2"):
        self.status, self.image, self.oom = status, NS(id="img"), oom
        self.attrs = {"State": {"StartedAt": "2026-10-12T05:01:02.123Z"}}
        self.cmds = []
    def stats(self, stream=False):
        return {"memory_stats": {"usage": 600, "limit": 1000, "stats": {"inactive_file": 100}},
                "cpu_stats": {"cpu_usage": {"total_usage": 3_000}, "system_cpu_usage": 20_000, "online_cpus": 4},
                "precpu_stats": {"cpu_usage": {"total_usage": 1_000}, "system_cpu_usage": 10_000}}
    def exec_run(self, cmd, **kw):
        line = cmd[-1]
        self.cmds.append(line)
        if line.startswith("ps "):
            return NS(output=PS.encode())
        if "oom_kill" in line:
            return NS(output=f"{self.oom}\n".encode())
        if "du -sb" in line:
            return NS(output=b"5000\n")
        return NS(output=b"")
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

# CPU：2000/10000 × 4 核 × 100 = 80% 的一台机器；配额 1 核 → 80% 配额；配额 0.5 核 → 封顶 100
st = FakeContainer("running").stats()
assert runner.cpu_percent(st, 1) == 80.0 and runner.cpu_percent(st, 0.5) == 100.0 and runner.cpu_percent(st, 2) == 40.0
assert runner.cpu_percent({}, 1) is None
assert runner.cpu_percent({"cpu_stats": {"cpu_usage": {"total_usage": 5}, "system_cpu_usage": 1},
                           "precpu_stats": {"cpu_usage": {"total_usage": 5}, "system_cpu_usage": 1}}, 1) is None
ps = runner.parse_ps(PS)
assert [p["pid"] for p in ps] == [42, 43], ps
assert ps[0] == {"pid": 42, "pgid": 42, "cpu": 87.5, "memory": 204800 * 1024, "elapsed": 185, "command": "python train.py --epochs 10"}
assert len(runner.parse_ps("\n".join(f"{i} {i} 1.0 10 5 job{i}" for i in range(1, 20)))) == runner.PROCESS_MAX
assert runner.mem_bytes("1g") == 2**30 and runner.mem_bytes("512m") == 512 * 2**20 and runner.mem_bytes("1.5G") == int(1.5 * 2**30)
assert runner.mem_bytes("lots") is None
c = FakeContainer("running"); c.name = "sbx-me"; containers["sbx-me"] = c
s = asyncio.run(runner.status("me"))
assert s["state"] == "running" and s["cpu_percent"] == runner.cpu_percent(c.stats()) and s["memory_used"] == 500, s
assert [p["pid"] for p in s["processes"]] == [42, 43] and s["oom_kills"] == 2, s
assert [p["pid"] for p in s["memory_top"]] == [42, 43], s  # v1.94 按内存排的那份
c.status = "exited"
s = asyncio.run(runner.status("me"))
assert s["state"] == "stopped" and s["processes"] == [] and s["oom_kills"] == 0 and s["cpu_percent"] is None, s
assert asyncio.run(runner.cleanup("me")) == {"freed": 0} and not any("du -sb" in x for x in c.cmds)  # 休眠：不开机清
c.status = "running"
assert asyncio.run(runner.cleanup("me")) == {"freed": 5000}
assert asyncio.run(runner.cleanup("p1")) == {"freed": 0}  # 没有这个容器
print("runner ok")

# ---- 2. 磁盘拆分 / 工具 / 清理 ----
d = storage.project_dir("me")
def w(rel, n):
    p = d / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"x" * n)
w("报告.md", 100); w(".git/HEAD", 10)
w(".home/.local/lib/python3.12/site-packages/requests-2.32.3.dist-info/METADATA", 30)
w(".home/.local/lib/python3.12/site-packages/typing_extensions-4.12.2.dist-info/METADATA", 20)
w(".home/.local/lib/node_modules/pnpm/package.json", 0)
(d / ".home/.local/lib/node_modules/pnpm/package.json").write_text('{"name":"pnpm","version":"9.1.0"}')
w(".home/.local/lib/node_modules/@vue/cli/package.json", 0)
(d / ".home/.local/lib/node_modules/@vue/cli/package.json").write_text('{"name":"@vue/cli","version":"5.0.8"}')
w(".home/.local/lib/node_modules/broken/package.json", 0)
w(".home/.cache/pip/http/blob", 400)
w(".spill/20261012-a.txt", 300)
w(".jobs/jold/log", 200)
w(".jobs/jrun/log", 50)
pnpm = len('{"name":"pnpm","version":"9.1.0"}'); vue = len('{"name":"@vue/cli","version":"5.0.8"}')
b = computer.storage_breakdown(d, {"jrun"})
assert b["files"] == 110 and b["installed"] == 50 + pnpm + vue and b["logs"] == 250 and b["spill"] == 300, b
assert b["cache"] == 400 and b["cleanable"] == 300 + 200 + 400 and b["partial"] is False, b
tools = computer.installed_tools(d)
assert tools == [{"kind": "npm", "name": "@vue/cli", "version": "5.0.8"}, {"kind": "npm", "name": "pnpm", "version": "9.1.0"},
                 {"kind": "pip", "name": "requests", "version": "2.32.3"},
                 {"kind": "pip", "name": "typing-extensions", "version": "4.12.2"}], tools
assert computer.installed_tools(storage.project_dir("empty")) == []
print("disk ok")

# ---- 3. 后台任务 OOM（真 run.sh，本机 bash；OOM 计数读假文件，命令自己让它 +1）----
counter = d / "oomcount"
counter.write_text("3\n")
jobs.OOM_COUNT = f"cat {counter}"
procs = {}
async def start_job(pid, jid):
    procs[jid] = subprocess.Popen(["bash", f".jobs/{jid}/run.sh"], cwd=storage.project_dir(pid), start_new_session=True)
sandbox_client.start_job = start_job
async def run_job(cmd):
    async with SessionLocal() as db:
        job = await jobs.start(db, project_id="me", command=cmd, title="训练")
        jid = job.id
    procs[jid].wait(20)
    async with SessionLocal() as db:
        job = await db.get(Job, jid)
        await jobs.refresh(db, job)
        return job.state, job.exit_code, job.stop_reason, jobs.describe(job), jobs.wire(job)
state, code, reason, desc, wire = asyncio.run(run_job(f"echo 加载数据; echo 4 > {counter}; kill -9 $$"))
assert state == "failed" and code == 137 and reason == jobs.OOM_REASON, (state, code, reason)
assert "失败：内存超过" in desc and "分批" in desc and "被自动停止" not in desc, desc
assert wire["stop_reason"] == jobs.OOM_REASON
state, code, reason, desc, _ = asyncio.run(run_job("kill -9 $$"))  # 计数没涨：普通被杀，不说是内存
assert state == "failed" and code == 137 and reason is None and "内存" not in desc, (state, reason, desc)
state, code, reason, _, _ = asyncio.run(run_job("echo ok"))
assert state == "done" and reason is None
jobs.OOM_COUNT = "echo"  # 读不到计数（输出空）→ 不判 OOM，也不报错
state, code, reason, _, _ = asyncio.run(run_job("exit 3"))
assert state == "failed" and code == 3 and reason is None
print("job oom ok")

# ---- 4. 前台 run_command ----
reply = {}
async def stream(pid, command, timeout=60, stdin=None):
    yield {"type": "exit", **reply}
sandbox_client.stream = stream
async def run(cmd):
    async with SessionLocal() as db:
        return await REGISTRY["run_command"].run(ToolContext(db=db), command=cmd)
reply.update(exit_code=137, timed_out=False, output="Killed\n", oom=True, memory_limit=2**30)
res = asyncio.run(run("python big.py"))
assert jobs.OOM_REASON in res.content and "上限 1 GB" in res.content and "分批" in res.content, res.content
assert jobs.OOM_REASON in res.blocks[0]["source"], res.blocks
reply.update(oom=False)
res = asyncio.run(run("python big.py"))
assert "退出码 137" in res.content and "内存" not in res.content, res.content
print("run_command ok")

# ---- 5. 接口 ----
up = {"ok": True}
freed_box = {"n": 777}
async def status(ws):
    if not up["ok"]:
        raise httpx.ConnectError("down")
    return {"state": "running", "memory_used": 300, "memory_limit": 1000, "cpu_percent": 12.5, "oom_kills": 1,
            "processes": [{"pid": 42, "cpu": 12.0, "memory": 2048, "elapsed": 60, "command": "python a.py"}, "junk"],
            "started_at": 1791781262.0, "outdated": False, "idle_minutes": 30, "last_used": None}
async def cleanup(ws):
    if not up["ok"]:
        raise httpx.ConnectError("down")
    return freed_box["n"]
sandbox_client.status, sandbox_client.cleanup = status, cleanup
app = FastAPI(); app.include_router(rf.router)
app.dependency_overrides[require_user] = lambda: "u"
cl = TestClient(app)
(d / ".jobs" / "jrun").exists()
async def fake_running():
    async with SessionLocal() as db:
        db.add(Job(id="jrun", project_id="me", title="还在跑", command="sleep 100", timeout=600, state="running"))
        await db.commit()
asyncio.run(fake_running())
w(".jobs/jrun/pid", 1)  # 有 pid 没 exit：refresh 只看磁盘 → 仍在跑
j = cl.get("/api/projects/me/computer").json()
sb = j["sandbox"]
assert sb["cpu_percent"] == 12.5 and sb["oom_kills"] == 1 and sb["processes"] == [
    {"pid": 42, "cpu": 12.0, "memory": 2048, "elapsed": 60, "command": "python a.py"}], sb
assert set(j["storage"]) == {"files", "installed", "logs", "spill", "cache", "cleanable"}, j["storage"]
assert j["disk_used"] == sum(j["storage"][k] for k in ("files", "installed", "logs", "spill", "cache"))
assert {t["name"] for t in j["tools"]} >= {"pnpm", "requests"}
before = j["storage"]
r = cl.post("/api/projects/me/computer/cleanup")
assert r.status_code == 200, r.text
out = r.json()
assert out["freed"] == before["cleanable"] + 777, (out["freed"], before)
assert not (d / ".spill").exists() and not (d / ".home/.cache").exists()
assert (d / ".jobs/jrun/log").exists() and (d / "报告.md").exists() and (d / ".home/.local/lib/node_modules/pnpm").exists()
assert out["status"]["storage"]["cleanable"] == 0 and out["status"]["storage"]["spill"] == 0, out["status"]["storage"]
assert [x["id"] for x in out["status"]["running_jobs"]] == ["jrun"]
w(".spill/x.txt", 40); up["ok"] = False
out = cl.post("/api/projects/me/computer/cleanup").json()
assert out["freed"] == 40 and out["status"]["sandbox"] == {"state": "unreachable"}, out
assert cl.post("/api/projects/nope/computer/cleanup").status_code == 404
print("api ok")
print("ALL OK")
