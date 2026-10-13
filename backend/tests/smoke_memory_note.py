# 冒烟：v2.00 “内存快满 / 刚被系统杀了进程”时给模型的那句（app/memory_view.py current + note）。
# 1) note 规则：不紧张 → 空；紧张 → 前 3 个占用者（任务/服务带编号、零散程序带 pid 和截短的命令）+ 对应出路；
#    after_oom 不紧张也说（“现在内存已用”）；没有上限 → “约”；没有大户 → “没有哪个程序特别大”；None → 空。
# 2) current：沙盒没开 / 连不上 → None；在跑 → 同一张表（任务按进程组、组里的进程不重复、零散程序单列）。
# 3) 模拟模型：job_status 列表（零散程序 pid 出现在结果里）；前台命令被系统因内存杀掉 → 结果带“剩下谁在占”；
#    后台任务因内存被杀 → job_status 单看带上；结束通知（jobs.notice + _oom_note）带上；不是 OOM 的不带。
# 运行：python tests/smoke_memory_note.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', SANDBOX_TOKEN="t",
  HOST_PROJECTS_DIR=tmp)
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr
import httpx
from app import foreground, jobs, job_usage, llm, memory_view, sandbox_client, storage
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.db import SessionLocal
from app.models import Conversation, Job, Project

MB, GB = 1 << 20, 1 << 30


def row(kind, mem, **kw):
    return {"kind": kind, "memory": mem, "processes": 1, "share": 0.1, **kw}


# ---- 1. note 规则 ----
view = {"used": 3800 * MB, "limit": 4 * GB, "other": 0, "rows": [
    row("job", 1500 * MB, id="ja", title="训练"),
    row("process", 900 * MB, pid=812, title="python " + "x" * 100),
    row("service", 400 * MB, id="jb", title="网站"),
    row("job", 100 * MB, id="jc", title="第四个")]}
n = memory_view.note(view)
assert n.startswith("注意：这台电脑内存已用 93%（3.7 GB / 4 GB）"), n
assert "后台任务 ja「训练」约 1.5 GB" in n and "零散程序 pid 812「python xxx" in n and "…」约 900 MB" in n, n
assert "常驻服务 jb「网站」约 400 MB" in n and "jc" not in n, n  # 只列前 3
assert "cancel_job" in n and "kill <pid>" in n and "ps -p <pid>" in n and "先问用户" in n and "再涨系统会强制结束" in n, n
calm = {**view, "used": 1 * GB}
assert memory_view.note(calm) == ""
o = memory_view.note(calm, after_oom=True)
assert o.startswith("这台电脑现在内存已用 25%") and "再涨" not in o and "ja「训练」" in o, o
assert memory_view.note(None) == "" and memory_view.note(None, after_oom=True) == ""
nolimit = memory_view.note({"used": 700 * MB, "limit": None, "rows": [], "other": 0}, after_oom=True)
assert "已用 约 700 MB" in nolimit and "没有哪个程序特别大" in nolimit and "cancel_job" not in nolimit, nolimit
assert memory_view.note({"used": 700 * MB, "limit": None, "rows": [], "other": 0}) == ""  # 不知道上限就不说“快满”
only_proc = memory_view.note({**view, "rows": [row("process", 900 * MB, pid=9, title="node a.js")]})
assert "kill <pid>" in only_proc and "cancel_job" not in only_proc and "先问用户" not in only_proc, only_proc
print("1 note rules ok")

# ---- 2. current ----
state = {"raw": {"state": "off"}, "fail": False}
async def fake_status(ws):
    if state["fail"]:
        raise httpx.ConnectError("x")
    return state["raw"]
async def fake_groups(ws, pgids):
    return {"state": "running", "groups": [{"pgid": 100, "cpu": 50.0, "cpu_seconds": 9.0, "memory": 2 * GB, "processes": 3}],
            "box": {"used": 3800 * MB, "limit": 4 * GB}}
async def alive(ws, jid):
    return True
sandbox_client.status, sandbox_client.groups, sandbox_client.job_alive = fake_status, fake_groups, alive


async def seed():
    async with SessionLocal() as db:
        p = Project(name="数据", emoji="🧪"); db.add(p); await db.flush()
        conv = Conversation(title="跑", project_id=p.id); db.add(conv); await db.flush()
        j = Job(id="jbig", project_id=p.id, conversation_id=conv.id, title="大训练", command="python train.py",
                timeout=3600, state="running")
        db.add(j); await db.commit()
        d = jobs.job_dir(j); d.mkdir(parents=True, exist_ok=True)
        (d / "pid").write_text("100"); (d / "log").write_text("epoch 1\n")
        return p.id, conv.id
ws, cid = asyncio.run(seed())


async def cur():
    async with SessionLocal() as db:
        return await memory_view.current(db, ws)
assert asyncio.run(cur()) is None
state["fail"] = True
assert asyncio.run(cur()) is None
state.update(fail=False, raw={"state": "running", "memory_used": 3800 * MB, "memory_limit": 4 * GB, "memory_top": [
    {"pid": 101, "pgid": 100, "memory": 1800 * MB, "command": "python train.py --worker"},  # 属于 jbig：不重复
    {"pid": 812, "pgid": 812, "memory": 900 * MB, "command": "nohup python leak.py"}]})
v = asyncio.run(cur())
assert [(r["kind"], r.get("id") or r.get("pid")) for r in v["rows"]] == [("job", "jbig"), ("process", 812)], v
print("2 current ok")

# ---- 3. 模拟模型 ----
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

job_usage.forget()
script[:] = [("job_status", {}), "好。"]
asyncio.run(turn())
t = last_tool()
assert "注意：这台电脑内存已用 93%" in t and "后台任务 jbig「大训练」约 2 GB" in t and "零散程序 pid 812「nohup python leak.py」" in t, t

# 单看在跑的任务：采样缓存说快满了 → 也带上
job_usage.forget()
script[:] = [("job_status", {"job_id": "jbig"}), "好。"]
asyncio.run(turn())
t = last_tool()
assert "现在占 CPU 50%" in t and "pid 812" in t, t

# 前台命令被系统因内存杀掉
async def oom_run(*a, **kw):
    return foreground.Outcome(exit_code=137, oom=True, status="内存超上限被系统结束（退出码 137）", out="Killed", shown="Killed")
real_run = foreground.run
foreground.run = oom_run
state["raw"] = {**state["raw"], "memory_used": 2600 * MB}  # 杀完降下来了：不紧张也照说
job_usage.forget()
script[:] = [("run_command", {"command": "python big.py"}), "好。"]
asyncio.run(turn())
t = last_tool()
assert "别原样重跑" in t and "这台电脑现在内存已用 63%" in t and "pid 812" in t and "再涨" not in t, t
async def ok_run(*a, **kw):
    return foreground.Outcome(exit_code=0, status="退出码 0", out="hi", shown="hi")
foreground.run = ok_run
script[:] = [("run_command", {"command": "echo hi"}), "好。"]
asyncio.run(turn())
assert "内存已用" not in last_tool(), last_tool()
foreground.run = real_run

# 后台任务因内存被系统杀了：单看 + 结束通知
async def kill_it():
    async with SessionLocal() as db:
        j = Job(id="joom", project_id=ws, conversation_id=cid, title="吃内存", command="python eat.py", timeout=600,
                state="failed", exit_code=137, stop_reason=jobs.OOM_REASON)
        db.add(j)
        k = Job(id="jok", project_id=ws, conversation_id=cid, title="正常", command="true", timeout=600, state="done", exit_code=0)
        db.add(k); await db.commit()
        return await jobs._oom_note(db, [k, j]), await jobs._oom_note(db, [k])
extra, none = asyncio.run(kill_it())
assert "这台电脑现在内存已用 63%" in extra and "pid 812" in extra and none == "", (extra, none)
async def notice_text():
    async with SessionLocal() as db:
        j = await db.get(Job, "joom")
        return jobs.notice(j, extra)
nt = asyncio.run(notice_text())
assert "【系统通知" in nt and "pid 812" in nt and nt.index("pid 812") < nt.index("根据结果接着"), nt
job_usage.forget()
script[:] = [("job_status", {"job_id": "joom"}), "好。"]
asyncio.run(turn())
t = last_tool()
assert jobs.OOM_REASON in t and "这台电脑现在内存已用 63%" in t, t
state["raw"] = {"state": "off"}
script[:] = [("job_status", {"job_id": "joom"}), "好。"]
asyncio.run(turn())
assert "内存已用" not in last_tool(), last_tool()  # 电脑停了：拿不到就不说
print("3 fake model ok")
print("smoke_memory_note OK")
