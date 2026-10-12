# 冒烟：v1.94 “内存去哪了”（app/memory_view.py + sandbox/runner.py process_tables + computer.status 的 memory）。
# 1) 真 ps：本机跑 runner._PS，解析出 pgid、按内存排的 memory_top（一个吃 80 MB 的真进程排第一）；
# 2) build 规则：后台任务 / 常驻服务按进程组算一行、组里的进程不在“程序”里重复出现、不属于任务的程序单列、
#    小于 1 MB 不列、最多 6 行、按大小排、share、其它 = 已用 − 各行（口径差导致超出时为 0）、没在跑 / 没有已用 → None；
# 3) 接口：GET …/computer 带 memory（假沙盒 status + groups），休眠时 memory 为 null。
# 运行：python tests/smoke_memory_view.py
import os, sys, asyncio, subprocess, tempfile, json, time, types
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', SANDBOX_TOKEN="t",
  HOST_PROJECTS_DIR=tmp)
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
sys.path.insert(0, os.path.join(root, "..", "sandbox"))
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

class NotFound(Exception):
    pass
docker_mod = types.ModuleType("docker")
docker_mod.from_env = lambda: NS(api=None, containers=NS(get=lambda n: (_ for _ in ()).throw(NotFound(n)), list=lambda **kw: []),
                                 images=NS(get=lambda name: NS(id="img")))
errors_mod = types.ModuleType("docker.errors"); errors_mod.NotFound = NotFound
docker_mod.errors = errors_mod
sys.modules.update({"docker": docker_mod, "docker.errors": errors_mod})
import runner
from app import computer, job_usage, jobs, memory_view, preview, sandbox_client, storage
from app.db import SessionLocal
from app.models import Job, Project

MB = 1 << 20

# ---- 1. 真 ps ----
hog = subprocess.Popen([sys.executable, "-c", "b = bytearray(80 << 20)\nfor i in range(0, len(b), 4096): b[i] = 1\n"
                        "import time; time.sleep(30)"], start_new_session=True)
time.sleep(1.0)
try:
    out = subprocess.run(["bash", "-c", runner._PS], capture_output=True, text=True).stdout
    t = runner.process_tables(out)
    assert set(t) == {"processes", "memory_top"} and len(t["memory_top"]) <= runner.PROCESS_MAX
    me = next(p for p in t["memory_top"] if p["pid"] == hog.pid)
    assert me["pgid"] == hog.pid and me["memory"] >= 70 * MB, me  # start_new_session → 自己是组长
    mems = [p["memory"] for p in t["memory_top"]]
    assert mems == sorted(mems, reverse=True), mems
    assert not any(p["command"].startswith("ps -eo") for p in t["memory_top"] + t["processes"])
finally:
    hog.kill(); hog.wait()
assert runner.process_tables("junk\n") == {"processes": [], "memory_top": []}
print("real ps ok")


# ---- 2. build 规则 ----
def job(jid, pg, title="任务", keep=False, ws="w1"):
    j = Job(id=jid, project_id=ws, title=title, command="python x.py", timeout=600, state="running", keep_alive=keep)
    d = jobs.job_dir(j); d.mkdir(parents=True, exist_ok=True)
    if pg is not None:
        (d / "pid").write_text(str(pg))
    return j


def u(mem, n=1):
    return {"cpu": 1.0, "cpu_seconds": 2.0, "memory": mem, "processes": n}


storage.project_dir("w1").mkdir(parents=True, exist_ok=True)
a, b, c = job("ja", 100, "训练"), job("jb", 200, "网站", keep=True), job("jc", 300, "没采到")
raw = {"state": "running", "memory_used": 1000 * MB, "memory_limit": 2000 * MB, "memory_top": [
    {"pid": 101, "pgid": 100, "memory": 500 * MB, "command": "python train.py"},     # 训练的子进程：不重复
    {"pid": 300, "pgid": 300, "memory": 90 * MB, "command": "python other.py"},      # jc 没采到 usage，但它的组仍归它
    {"pid": 7, "pgid": 7, "memory": 150 * MB, "command": "node dev-server.js"},      # 对话里直接跑的
    {"pid": 8, "pgid": 8, "memory": MB // 2, "command": "sleep 1"},                  # 太小
    "junk", {"pid": "x", "memory": 1}]}
v = memory_view.build(raw, [a, b, c], {"ja": u(600 * MB, 3), "jb": u(100 * MB)})
assert v["used"] == 1000 * MB and v["limit"] == 2000 * MB, v
assert [(r["kind"], r.get("id") or r.get("pid")) for r in v["rows"]] == [("job", "ja"), ("process", 7), ("service", "jb")], v
assert v["rows"][0] == {"kind": "job", "id": "ja", "title": "训练", "memory": 600 * MB, "processes": 3, "share": 0.6}, v
assert v["rows"][1]["title"] == "node dev-server.js" and v["rows"][1]["share"] == 0.15
assert v["other"] == 1000 * MB - 600 * MB - 100 * MB - 150 * MB - MB // 2, v
# 行加起来超过已用（PSS / RSS 口径差）→ 其它 0
v = memory_view.build({**raw, "memory_used": 700 * MB}, [a, b, c], {"ja": u(600 * MB), "jb": u(100 * MB)})
assert v["other"] == 0 and v["rows"][0]["share"] == round(600 / 700, 3), v
# 最多 6 行，按大小
many = [{"pid": i, "pgid": i, "memory": i * MB, "command": f"p{i}"} for i in range(10, 20)]
v = memory_view.build({"state": "running", "memory_used": 4000 * MB, "memory_limit": None, "memory_top": many}, [], {})
assert [r["pid"] for r in v["rows"]] == [19, 18, 17, 16, 15, 14] and v["limit"] is None, v
# 没在跑 / 没有已用 / 坏数据
assert memory_view.build({"state": "stopped", "memory_used": 5}, [], {}) is None
assert memory_view.build({"state": "running", "memory_used": None}, [], {}) is None
assert memory_view.build({"state": "running", "memory_used": -3}, [], {}) is None
assert memory_view.build(None, [], {}) is None
v = memory_view.build({"state": "running", "memory_used": 0, "memory_limit": 0}, [], {})
assert v == {"used": 0, "limit": None, "rows": [], "other": 0}, v
# 没有 pid 文件的任务：不崩，进程照常单列
d = job("jd", None)
v = memory_view.build({"state": "running", "memory_used": 100 * MB, "memory_top": [
    {"pid": 5, "pgid": 5, "memory": 10 * MB, "command": "x"}]}, [d], {})
assert [r["pid"] for r in v["rows"]] == [5], v
print("rules ok")


# ---- 3. 接口 ----
state = {"s": "running"}
async def status(ws):
    if state["s"] != "running":
        return {"state": "stopped"}
    return {"state": "running", "memory_used": 800 * MB, "memory_limit": 1024 * MB, "cpu_percent": 3.0,
            "processes": [], "memory_top": [{"pid": 9, "pgid": 9, "memory": 120 * MB, "command": "python bot.py"},
                                            {"pid": 41, "pgid": 40, "memory": 300 * MB, "command": "python big.py"}]}
async def groups(ws, pgids):
    return {"state": "running", "groups": [{"pgid": 40, "cpu": 5.0, "cpu_seconds": 1.0, "memory": 350 * MB, "processes": 2}]}
async def listening(ws):
    return {"ports": []}
sandbox_client.status, sandbox_client.groups, preview.listening = status, groups, listening


async def seed():
    async with SessionLocal() as db:
        p = Project(name="内存", emoji="🧠"); db.add(p); await db.flush()
        j = Job(id="jbig", project_id=p.id, title="大任务", command="python big.py", timeout=600, state="running")
        db.add(j); await db.commit()
        dd = jobs.job_dir(j); dd.mkdir(parents=True, exist_ok=True); (dd / "pid").write_text("40")
        return p.id
pid = asyncio.run(seed())


async def st():
    async with SessionLocal() as db:
        return await computer.status(db, pid)
job_usage.forget()
s = asyncio.run(st())
m = s["memory"]
assert [(r["kind"], r["memory"]) for r in m["rows"]] == [("job", 350 * MB), ("process", 120 * MB)], m
assert m["rows"][0]["id"] == "jbig" and m["other"] == 800 * MB - 470 * MB and m["limit"] == 1024 * MB, m
assert s["sandbox"]["memory_used"] == m["used"]  # 和状态块同一个数
state["s"] = "stopped"
assert asyncio.run(st())["memory"] is None
print("api ok")
print("ALL OK")
