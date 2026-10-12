# 冒烟：v1.74 同时开机的沙盒上限 + 腾内存（sandbox/runner.py room_order/_make_room/stopped_by/woke，
# backend app/computer.py sandbox_wire + wake_note，run_command 结果里的提醒）。
# 1) room_order 纯函数：没超不挑、最久没用的先挑、在用的 / 宽限期内用过的不挑、limit 0 不限；
# 2) 真 runner（docker 换假的）：上限 2，第三个工作区开机 → 最久没用的闲容器被停、stopped_by=room；
#    有后台任务的、正在跑前台命令的跳过；都在忙 → 照开（软上限）；已开着的不触发让位；
#    状态带 stopped_by/stopped_at；它下一条命令把它开起来 → 结果 woke=room，再下一条没有；后台任务开机不带 woke；
#    空闲回收 → stopped_by=idle；正在用的不被空闲回收；删除容器清掉记录；
# 2b) v1.76 宿主机内存：mem_available/mem_short 纯函数；剩余内存不够时即使台数没超也停闲容器，停一台看一次，够了就停手；
#     读不到 meminfo / reserve 0 只按台数；都在忙照开；
# 3) 后端：sandbox_wire 透传（只在 stopped 时、只认 idle/room）；run_command 结果附“之前前台起的程序已停”。
# 运行：python tests/smoke_sandbox_room.py
import os, sys, asyncio, tempfile, json, time, types
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)

# ---- 假 docker ----
class NotFound(Exception):
    pass
containers: dict = {}
busy_jobs: set = set()  # 有后台任务在跑的工作区
log: list = []
class FakeContainer:
    def __init__(self, name, status="running"):
        self.name, self.status, self.id = name, status, name
        self.image = NS(id="img")
        self.attrs = {"State": {"StartedAt": ""}}
    def start(self):
        log.append(("start", self.name)); self.status = "running"
    def stop(self, timeout=10):
        log.append(("stop", self.name)); self.status = "exited"
    def remove(self, force=False):
        containers.pop(self.name, None)
    def exec_run(self, cmd, **kw):
        text = " ".join(cmd) if isinstance(cmd, list) else cmd
        if "busy" in text:
            return NS(exit_code=0, output=b"busy\n" if self.name[4:] in busy_jobs else b"")
        return NS(exit_code=0, output=b"0\n")
def get(name):
    if name not in containers:
        raise NotFound(name)
    return containers[name]
def lst(filters=None, **kw):
    return [c for c in containers.values() if c.status == "running"]
def run(image, name, **kw):
    log.append(("create", name)); c = FakeContainer(name); containers[name] = c; return c
execs = {}
def exec_create(cid, cmd, **kw):
    execs["x"] = cid; return {"Id": "x"}
def exec_start(eid, stream=True):
    yield b"ok\n"
fake_client = NS(containers=NS(get=get, list=lst, run=run), images=NS(get=lambda name: NS(id="img")),
                 networks=NS(get=lambda name: (_ for _ in ()).throw(NotFound(name))),
                 api=NS(exec_create=exec_create, exec_start=exec_start, exec_inspect=lambda eid: {"ExitCode": 0}))
docker_mod = types.ModuleType("docker"); docker_mod.from_env = lambda: fake_client
errors_mod = types.ModuleType("docker.errors"); errors_mod.NotFound = NotFound
docker_mod.errors = errors_mod
sys.modules.update({"docker": docker_mod, "docker.errors": errors_mod})
os.environ.update(SANDBOX_TOKEN="t", HOST_PROJECTS_DIR=tmp, SANDBOX_MAX_RUNNING="2")
sys.path.insert(0, os.path.join(root, "..", "sandbox"))
import runner
runner.MEMINFO = os.path.join(tmp, "meminfo")  # 先不存在：读不到 = 只按台数
runner.PROJECTS_ROOT = tmp
_makedirs, _chown = runner.os.makedirs, runner.os.chown
runner.os.chown = lambda *a, **k: None
real_makedirs = os.makedirs
runner.os.makedirs = lambda p, exist_ok=False: real_makedirs(p.replace("/projects", tmp, 1), exist_ok=True)

# ---- 1. room_order ----
G = runner.ROOM_GRACE_S
now = 10_000.0
assert runner.room_order({"a": now - 999}, set(), 2, now) == (0, ["a"])  # 1 + 1 ≤ 2：不用停，顺序照给
need, order = runner.room_order({"a": now - 500, "b": now - 900, "c": now - 10}, set(), 2, now)
assert need == 2 and order == ["b", "a"], (need, order)  # c 刚用过（宽限期内）不挑
need, order = runner.room_order({"a": now - 500, "b": now - 900}, {"b"}, 2, now)
assert need == 1 and order == ["a"], (need, order)
assert runner.room_order({"a": 0, "b": 0, "c": 0}, set(), 0, now) == (0, ["a", "b", "c"])  # 0 = 台数不限，但给顺序（内存不够时用）
assert runner.room_order({"a": now - G, "b": now - G + 1}, set(), 1, now) == (2, ["a"])
print("room_order ok")

# ---- 2. 真 runner ----
assert runner.MAX_RUNNING == 2
t = time.time()
containers["sbx-old"] = FakeContainer("sbx-old"); runner.last_used["old"] = t - 3000
containers["sbx-mid"] = FakeContainer("sbx-mid"); runner.last_used["mid"] = t - 1000
runner._container("new")  # 已开 2 台 → 停最久没用的 old
assert ("stop", "sbx-old") in log and ("stop", "sbx-mid") not in log and ("create", "sbx-new") in log, log
assert runner.stopped_by["old"][0] == "room" and "old" not in runner.last_used
st = asyncio.run(runner.status("old"))
assert st["state"] == "stopped" and st["stopped_by"] == "room" and st["stopped_at"] >= t and st["max_running"] == 2, st
st = asyncio.run(runner.status("mid"))
assert st["state"] == "running" and "stopped_by" not in st, st
runner.last_used["new"] = t - 2000  # new 也闲了
log.clear()
runner._container("mid")  # 已开着：不触发让位
assert log == [], log

# 有后台任务的、正在跑前台命令的跳过：new 最久没用但有后台任务 → 停 mid
busy_jobs.add("new")
log.clear()
r = runner._exec("old", "echo hi", 10)  # old 开机 → 要停一台
assert ("stop", "sbx-mid") in log and ("stop", "sbx-new") not in log and ("start", "sbx-old") in log, log
assert r["woke"] == "room" and r["output"].strip() == "ok", r  # old 是被让位停的：告诉模型
assert "old" not in runner.stopped_by and "old" not in runner.woke
r = runner._exec("old", "echo hi", 10)
assert "woke" not in r, r  # 只提醒一次
assert runner.in_use == {}, runner.in_use  # 用完计数归零

# 都在忙 → 照开（软上限）
runner.last_used["old"] = t - 2000
runner.in_use["old"] = 1  # 前台命令在跑
log.clear()
runner._container("third")
assert ("create", "sbx-third") in log and not any(a == "stop" for a, _ in log), log
assert len(lst()) == 3
runner.in_use.clear(); busy_jobs.clear()

# 后台任务把它开机：不带 woke 到下一条命令
containers["sbx-mid"].status = "exited"; runner.stopped_by["mid"] = ("room", t)
runner.MAX_RUNNING = 0  # 不限，免得这里又挤掉别人
os.makedirs(f"{tmp}/mid/.jobs/j0000001", exist_ok=True)
containers["sbx-mid"].exec_run = lambda cmd, **kw: NS(exit_code=0, output=b"")
asyncio.run(runner.job_start(runner.JobIn(project_id="mid", job_id="j0000001")))
assert "mid" not in runner.woke and "mid" not in runner.stopped_by
r = runner._exec("mid", "ls", 10)
assert "woke" not in r, r

# 空闲回收 → idle；正在用的不收
runner.IDLE_MINUTES = 1
runner.last_used.update({"old": t - 500, "third": t - 500})
runner.in_use["third"] = 1
async def one_reap():
    orig = asyncio.sleep
    calls = {"n": 0}
    async def fake_sleep(s):
        calls["n"] += 1
        if calls["n"] > 1:
            raise asyncio.CancelledError
    runner.asyncio.sleep = fake_sleep
    try:
        await runner._reaper()
    except asyncio.CancelledError:
        pass
    finally:
        runner.asyncio.sleep = orig
asyncio.run(one_reap())
assert containers["sbx-old"].status == "exited" and runner.stopped_by["old"][0] == "idle"
assert containers["sbx-third"].status == "running" and "third" not in runner.stopped_by
assert runner.last_used["third"] >= t, runner.last_used
runner.in_use.clear()
r = runner._exec("old", "ls", 10)
assert r["woke"] == "idle", r
containers["sbx-old"].status = "exited"; runner.stopped_by["old"] = ("room", t)
asyncio.run(runner.remove("old"))
assert "old" not in runner.stopped_by and "old" not in runner.woke
print("runner room ok")

# ---- 2b. 宿主机内存（v1.76） ----
MI = "MemTotal:        4015000 kB\nMemFree:          100000 kB\nMemAvailable:    {} kB\n"
assert runner.mem_available(MI.format(2048)) == 2048 * 1024
assert runner.mem_available("MemTotal: 1 kB\n") is None
G1 = 1024 ** 3
assert runner.mem_short(G1, G1, 256 * 1024 ** 2) and not runner.mem_short(2 * G1, G1, 256 * 1024 ** 2)
assert not runner.mem_short(None, G1, 1) and not runner.mem_short(0, G1, 0) and not runner.mem_short(0, None, 1)
assert runner.mem_bytes(runner.HOST_RESERVE) == 256 * 1024 ** 2 and runner.mem_bytes("0") == 0
containers.clear(); log.clear(); runner.stopped_by.clear(); runner.woke.clear(); runner.last_used.clear(); runner.in_use.clear()
runner.MAX_RUNNING = 5  # 台数远没超
t = time.time()
for n, age in (("m1", 3000), ("m2", 2000), ("m3", 1000)):
    containers[f"sbx-{n}"] = FakeContainer(f"sbx-{n}"); runner.last_used[n] = t - age
# 每停一台就多出 600 MB：一开始 800 MB < 1 GB + 256 MB；停一台 1.4 GB 够了
def write_avail():
    up = sum(1 for c in containers.values() if c.status == "running")
    open(runner.MEMINFO, "w").write(MI.format((800 + (3 - up) * 600) * 1024))
orig_stop = FakeContainer.stop
def stop_and_free(self, timeout=10):
    orig_stop(self, timeout); write_avail()
FakeContainer.stop = stop_and_free
write_avail()
runner._container("m4")
assert [x for x in log if x[0] == "stop"] == [("stop", "sbx-m1")] and ("create", "sbx-m4") in log, log
assert runner.stopped_by["m1"][0] == "room"
# 内存一直不够、能停的都停了 → 照开（软上限）；在用的不停
log.clear(); runner.last_used["m4"] = t - 500
runner.in_use["m3"] = 1
open(runner.MEMINFO, "w").write(MI.format(100 * 1024)); FakeContainer.stop = orig_stop
runner._container("m5")
stops = [x for x in log if x[0] == "stop"]
assert stops == [("stop", "sbx-m2"), ("stop", "sbx-m4")] and ("create", "sbx-m5") in log, log
runner.in_use.clear()
# reserve 0：只按台数
log.clear(); runner.HOST_RESERVE = "0"
runner._container("m6")
assert not any(a == "stop" for a, _ in log) and ("create", "sbx-m6") in log, log
# MAX_RUNNING 0 + 内存够：不腾
runner.HOST_RESERVE = "256m"; runner.MAX_RUNNING = 0
open(runner.MEMINFO, "w").write(MI.format(3 * 1024 * 1024))
log.clear(); runner._container("m7")
assert not any(a == "stop" for a, _ in log), log
# MAX_RUNNING 0 + 内存不够：仍腾
open(runner.MEMINFO, "w").write(MI.format(100 * 1024)); runner.last_used.update({"m5": t - 900, "m6": t - 800, "m7": t - 700})
log.clear(); runner._container("m8")
assert ("stop", "sbx-m5") in log, log
os.remove(runner.MEMINFO)
print("host memory ok")

# ---- 3. 后端 ----
import subprocess
rr = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert rr.returncode == 0, rr.stderr
from app import computer, sandbox_client
from app.agent.tools import REGISTRY, ToolContext, load_builtin
load_builtin()
from app.db import SessionLocal
w = computer.sandbox_wire({"state": "stopped", "stopped_by": "room", "stopped_at": 1791781262.0})
assert w["stopped_by"] == "room" and w["stopped_at"] and "2026-10-12" in w["stopped_at"], w
assert computer.sandbox_wire({"state": "stopped", "stopped_by": "weird"})["stopped_by"] is None
assert computer.sandbox_wire({"state": "running", "stopped_by": "room"})["stopped_by"] is None
assert computer.sandbox_wire({"state": "stopped"})["stopped_at"] is None
assert computer.wake_note(None) == "" and computer.wake_note("x") == ""
assert "腾内存" in computer.wake_note("room") and "空闲" in computer.wake_note("idle")
reply = {}
async def stream(pid, command, timeout=60, stdin=None):
    yield {"type": "exit", **reply}
sandbox_client.stream = stream
async def run_cmd(cmd):
    async with SessionLocal() as db:
        return await REGISTRY["run_command"].run(ToolContext(db=db), command=cmd)
reply.update(exit_code=0, timed_out=False, output="hi\n", woke="room")
res = asyncio.run(run_cmd("curl localhost:3000"))
assert "腾内存" in res.content and "重新启动" in res.content and "background=true" in res.content, res.content
assert "腾内存" not in res.blocks[0]["source"], res.blocks  # 给模型的，不进用户看的代码块
reply.pop("woke")
res = asyncio.run(run_cmd("ls"))
assert "休眠" not in res.content, res.content
print("backend ok")
print("ALL OK")
