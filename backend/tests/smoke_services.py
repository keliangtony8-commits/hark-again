# 冒烟：v1.82 常驻服务健康 + 手动重启（app/services.py）：电脑状态里的 services 一节（健康、端口归属、意外结束留 24 小时）、
# POST /api/jobs/{id}/restart（在跑 → 杀了重起 / 等重启 → 马上起 / 放弃了 → 重新拉起）、restart_service 工具（模拟模型）。
# 沙盒服务用本机 bash 顶替（run.sh 真跑），无新迁移。
# 运行：python tests/smoke_services.py
import os, sys, asyncio, subprocess, tempfile, json, signal, time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, JOB_MAX_RUNNING="6",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from sqlalchemy import select
from app import jobs, llm, sandbox_client, storage
from app.agent.runner import run_turn
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.auth import require_user
from app.blocks import Block, blocks_to_text, text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Job, Message, Project
from app.routes import files as rf, jobs as rj

# ---- 本机顶替沙盒服务 ----
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
    procs[jid].wait(10)  # run.sh 写完 exit 才算
async def job_alive(pid, jid):
    p = _pid(pid, jid)
    if p is None:
        return False
    try:
        os.kill(p, 0)
        return True
    except ProcessLookupError:
        return False
sandbox_client.start_job, sandbox_client.cancel_job, sandbox_client.job_alive = start_job, cancel_job, job_alive
jobs.LOST_GRACE = 0

# ---- 模拟模型 ----
script: list = []
seen: list[list] = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append(messages)
    step = script.pop(0)
    async def gen():
        if isinstance(step, tuple):
            yield chunk(tool=[NS(index=0, id=f"c{len(script)}", function=NS(name=step[0], arguments=json.dumps(step[1], ensure_ascii=False)))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()

app = FastAPI()
app.include_router(rj.router); app.include_router(rf.router)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)

def run(coro):
    return asyncio.run(coro)

async def seed():
    async with SessionLocal() as db:
        p = Project(name="训练", emoji="🧪"); db.add(p); await db.flush()
        conv = Conversation(title="跑训练", project_id=p.id); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("把训练脚本放后台跑")))
        await db.commit()
        return p.id, conv.id
pid, cid = run(seed())

async def turn(conv_id=cid, notice=None):
    async with SessionLocal() as db:
        conv = await db.get(Conversation, conv_id)
        return await run_turn(db, conv, notice=notice)

async def job(jid):
    async with SessionLocal() as db:
        return await db.get(Job, jid)

def wait_exit(jid, secs=10):
    end = time.time() + secs
    while time.time() < end:
        if (storage.project_dir(pid) / ".jobs" / jid / "exit").exists():
            return
        time.sleep(0.1)
    raise AssertionError("job never exited")


from app import computer, job_restart, quota, workspaces
from app.config import settings

async def start(cmd, conv_id=cid, **kw):
    async with SessionLocal() as db:
        return (await jobs.start(db, project_id=pid, command=cmd, conversation_id=conv_id, **kw)).id
async def tick():
    async with SessionLocal() as db:
        return await jobs.tick(db)
async def tool(name, **args):
    async with SessionLocal() as db:
        return await REGISTRY[name].run(ToolContext(db=db, project_id=pid, conversation_id=cid), **args)
async def patch(jid, **kw):
    async with SessionLocal() as db:
        j = await db.get(Job, jid)
        for k, v in kw.items():
            setattr(j, k, v)
        await db.commit()
def jd(jid):
    return storage.project_dir(pid) / ".jobs" / jid
def due(jid):
    run(patch(jid, restart_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
def wait_restart_planned(jid, secs=10):
    end = time.time() + secs
    while time.time() < end:
        run(tick())
        if run(job(jid)).restart_at is not None or run(job(jid)).state != "running":
            return run(job(jid))
        time.sleep(0.1)
    raise AssertionError("restart never planned")
def kill_all(jid):
    if (p := _pid(pid, jid)) is not None:
        try:
            os.killpg(p, signal.SIGKILL)
        except ProcessLookupError:
            pass


from app import services
import httpx

def wait_pid(jid, secs=10):
    end = time.time() + secs
    while time.time() < end:
        if (p := _pid(pid, jid)) is not None:
            try:
                os.kill(p, 0); return p
            except ProcessLookupError:
                pass
        time.sleep(0.05)
    raise AssertionError("no pid")

# 假沙盒状态 + 端口（端口进程组 = 任务组长 pid）
fake_ports: list = []
async def fake_status(ws):
    return {"state": "running", "processes": []}
async def fake_ports_call(ws):
    return {"state": "running", "ports": fake_ports}
sandbox_client.status, sandbox_client.ports = fake_status, fake_ports_call
async def status():
    async with SessionLocal() as db:
        return await computer.status(db, pid)

# ---- 1. 起一个常驻服务 + 一个普通任务：服务进 services，普通任务留在 running_jobs ----
k = run(start("echo 起来了; sleep 30", keep_alive=True, title="机器人"))
n = run(start("sleep 30", title="普通"))
g = wait_pid(k); wait_pid(n)
fake_ports[:] = [{"port": 8000, "loopback": False, "pid": g + 1, "pgid": g, "command": "python bot.py"},
                 {"port": 9000, "loopback": False, "pid": 1, "pgid": 1, "command": "other"}]
st = run(status())
assert [j["id"] for j in st["running_jobs"]] == [n], st["running_jobs"]
sv = st["services"]
assert len(sv) == 1 and sv[0]["id"] == k and sv[0]["health"] == "up" and sv[0]["ports"] == [8000], sv
assert sv[0]["uptime"] is not None and sv[0]["uptime"] >= 0 and sv[0]["crash_streak"] == 0 and sv[0]["keep_alive"] is True
assert st["ports"][0]["pgid"] == g

# ---- 2. 普通任务不能重启（409）；没有的任务 404 ----
r = c.post(f"/api/jobs/{n}/restart"); assert r.status_code == 409 and "常驻" in r.json()["detail"], r.text
assert c.post("/api/jobs/jnope/restart").status_code == 404

# ---- 3. 在跑的手动重启：整组杀掉 → restart_at=现在、不算崩溃 → worker 一轮拉起，日志接着写 ----
run(patch(k, crash_streak=3))
r = c.post(f"/api/jobs/{k}/restart"); assert r.status_code == 200, r.text
j = run(job(k))
assert j.state == "running" and j.restart_at is not None and j.crash_streak == 0, (j.state, j.restart_at)
assert (jd(k) / "exit").exists()  # 旧 run.sh 已写完退出码（不会晚写把新进程判成结束）
try:
    os.kill(g, 0); raise AssertionError("old process still alive")
except ProcessLookupError:
    pass
assert services.health(j) == "restarting" and services.owned_ports(j, fake_ports) == []
assert run(status())["services"][0]["health"] == "restarting"
run(tick())
j = run(job(k))
assert j.restarts == 1 and j.restart_at is None and j.state == "running" and j.followup == "none", (j.restarts, j.followup)
g2 = wait_pid(k); assert g2 != g
time.sleep(0.3)
log = (jd(k) / "log").read_text()
assert log.count("起来了") == 2 and "第 1 次重启" in log, log
run(tick()); assert run(job(k)).state == "running"  # 旧的退出码清掉了，新进程没被误判

# ---- 4. 等自动重启中 → 手动“立即重启”：不叫沙盒杀（进程本来就没了），restart_at 拉回现在 ----
kills = []
real_cancel = sandbox_client.cancel_job
async def counting_cancel(p, jid):
    kills.append(jid); await real_cancel(p, jid)
sandbox_client.cancel_job = counting_cancel
kill_all(k); wait_exit(k)
j = wait_restart_planned(k)
assert j.restart_at is not None and j.crash_streak == 1
run(patch(k, restart_at=datetime.now(timezone.utc) + timedelta(seconds=200)))
assert c.post(f"/api/jobs/{k}/restart").status_code == 200
j = run(job(k))
assert kills == [] and j.crash_streak == 0 and j.restart_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc), (kills, j.restart_at)
run(tick()); assert run(job(k)).restarts == 2
wait_pid(k)

# ---- 5. 沙盒杀不动 → 409 原因写清，restart_at 撤回、状态不动 ----
async def broken_cancel(p, jid):
    raise httpx.ConnectError("down")
sandbox_client.cancel_job = broken_cancel
r = c.post(f"/api/jobs/{k}/restart"); assert r.status_code == 409 and "沙盒没响应" in r.json()["detail"], r.text
j = run(job(k)); assert j.restart_at is None and j.state == "running" and j.restarts == 2
sandbox_client.cancel_job = real_cancel

# ---- 6. 连续崩溃放弃了（failed）：电脑里还留着（gave_up），“重新启动”清零拉起、聊天卡片改回运行中 ----
async def seed_card(jid):
    async with SessionLocal() as db:
        j = await db.get(Job, jid)
        db.add(Message(conversation_id=cid, role="assistant", blocks=[jobs.block(j)])); await db.commit()
run(seed_card(k))
kill_all(k); wait_exit(k)
run(patch(k, crash_streak=job_restart.CRASH_LIMIT))
j = wait_restart_planned(k)  # 很快又崩：到上限，jobs._end 直接放弃
assert j.state == "failed" and j.stop_reason == job_restart.give_up_text(), (j.state, j.stop_reason)
async def give_up(jid):
    async with SessionLocal() as db:
        j = await db.get(Job, jid)
        j.stop_reason = job_restart.give_up_text()
        await jobs.settle(db, j, "failed", 1)
j = run(job(k)); assert j.state == "failed" and j.followup == "pending"
sv = run(status())["services"]
assert sv[0]["id"] == k and sv[0]["health"] == "gave_up" and sv[0]["uptime"] is None and sv[0]["ports"] == [], sv
assert sv[0]["stop_reason"] == job_restart.give_up_text()
async def card(jid):
    async with SessionLocal() as db:
        ms = (await db.scalars(select(Message).where(Message.conversation_id == cid, Message.role == "assistant"))).all()
        return [b for m in ms for b in m.blocks if b.get("type") == "job" and b.get("id") == jid][-1]
assert run(card(k))["state"] == "failed"
r = c.post(f"/api/jobs/{k}/restart"); assert r.status_code == 200, r.text
assert r.json()["state"] == "running" and r.json()["stop_reason"] is None
j = run(job(k))
assert j.state == "running" and j.finished_at is None and j.crash_streak == 0 and j.followup == "none" and j.restart_at is not None
assert run(card(k))["state"] == "running" and "finished_at" not in run(card(k))
run(tick()); j = run(job(k)); assert j.restarts == 3 and j.restart_at is None
wait_pid(k)
assert run(status())["services"][0]["health"] == "up"

# ---- 7. 名额满了不能重新拉起；磁盘满了也不行 ----
run(give_up(k))
old_max = settings.job_max_running
settings.job_max_running = 1  # 普通任务 n 还在跑
r = c.post(f"/api/jobs/{k}/restart"); assert r.status_code == 409 and "上限" in r.json()["detail"], r.text
settings.job_max_running = old_max
real_check = quota.check
def full(ws):
    raise quota.QuotaError("磁盘满了")
quota.check = full
r = c.post(f"/api/jobs/{k}/restart"); assert r.status_code == 409 and "磁盘满了" in r.json()["detail"], r.text
quota.check = real_check
assert run(job(k)).state == "failed"

# ---- 8. 用户停掉的（cancelled）不进服务列表、不能“重新启动”；超过 24 小时的意外结束也不列 ----
k2 = run(start("sleep 30", keep_alive=True, title="停掉的"))
wait_pid(k2)
c.post(f"/api/jobs/{k2}/cancel"); assert run(job(k2)).state == "cancelled"
r = c.post(f"/api/jobs/{k2}/restart"); assert r.status_code == 409 and "停掉" in r.json()["detail"], r.text
ids = [s["id"] for s in run(status())["services"]]
assert k2 not in ids and k in ids, ids
run(patch(k, finished_at=datetime.now(timezone.utc) - timedelta(hours=services.GONE_HOURS + 1)))
assert run(status())["services"] == []

# ---- 9. 模型用 restart_service（模拟模型一轮）：重启后自己接一句；普通任务、别的工作区的给出原因 ----
run(patch(k, finished_at=datetime.now(timezone.utc)))
script[:] = [("restart_service", {"job_id": k}), "好了，机器人重启了"]
out = run(turn())
assert script == [], script
tool_msgs = [m for m in seen[-1] if m.get("role") == "tool"]
assert tool_msgs and "已安排重启" in str(tool_msgs[-1].get("content")), tool_msgs[-1:]
assert run(job(k)).state == "running"
r = run(tool("restart_service", job_id=n)); assert "常驻" in r.content
r = run(tool("restart_service", job_id="jnope")); assert "只能重启本工作区" in r.content
from app.agent import subagent
assert "restart_service" in subagent.CHILD_TOOLS
from app import plan_mode
assert "restart_service" not in plan_mode.READ_TOOLS

# ---- 10. v2.85 同一个服务只出一行（同名同命令）：旧的意外结束记录折成 earlier_stops；两个都在跑各出一行 ----
J = lambda i, st, t="机器人", cmd="python bot.py": NS(id=i, state=st, title=t, command=cmd)
m = services.merge([J("a", "running"), J("b", "failed"), J("c", "lost"), J("d", "failed", t="别的")])
assert [(j.id, n) for j, n in m] == [("a", 2), ("d", 0)], m
m = services.merge([J("a", "running"), J("b", "running"), J("c", "failed")])
assert [(j.id, n) for j, n in m] == [("a", 1), ("b", 0)], m
m = services.merge([J("x", "failed"), J("y", "timed_out"), J("z", "failed", cmd="python other.py")])
assert [(j.id, n) for j, n in m] == [("x", 1), ("z", 0)], m
async def clone_gone(jid):
    async with SessionLocal() as db:
        j = await db.get(Job, jid)
        import uuid
        db.add(Job(id="j" + uuid.uuid4().hex[:11], project_id=j.project_id, conversation_id=j.conversation_id, title=j.title, command=j.command, keep_alive=True,
                   state="failed", finished_at=datetime.now(timezone.utc), timeout=j.timeout)); await db.commit()
k3 = run(start("sleep 30", keep_alive=True, title="复活"))
wait_pid(k3)
run(clone_gone(k3)); run(clone_gone(k3))
sv = [x for x in run(status())["services"] if x["title"] == "复活"]
assert len(sv) == 1 and sv[0]["id"] == k3 and sv[0]["health"] == "up" and sv[0]["earlier_stops"] == 2, sv
c.post(f"/api/jobs/{k3}/cancel")

# ---- 11. v2.85 整台服务器读数（machine.py）：解析 meminfo；个人工作区才给，项目的电脑 None ----
from app import machine, workspaces
assert machine._meminfo("MemTotal: 4000 kB\nMemFree: 100 kB\nMemAvailable: 1000 kB\n") == (4000 * 1024, 3000 * 1024)
assert machine._meminfo("MemTotal: 4000 kB\nMemFree: 500 kB\n") == (4000 * 1024, 3500 * 1024)
mr = machine.read(tmp)
assert set(mr) == {"cpus", "load1", "memory_total", "memory_used", "disk_total", "disk_used"} and mr["disk_total"] > 0, mr
st = run(status())
assert ("machine" in st) and ((st["machine"] is not None) == workspaces.is_personal(pid)), (pid, st.get("machine"))
async def personal_status():
    async with SessionLocal() as db:
        return await computer.status(db, workspaces.PERSONAL)
try:
    pm = run(personal_status())["machine"]
    assert pm is not None and pm["cpus"] >= 1, pm
except LookupError:
    pass  # 个人工作区没建好（只在完整安装里有）

for jid in (k, n):
    c.post(f"/api/jobs/{jid}/cancel")
for p in procs.values():
    try:
        p.kill()
    except Exception:
        pass
print("smoke_services OK")
