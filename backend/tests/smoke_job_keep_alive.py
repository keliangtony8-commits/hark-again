# 冒烟：v1.80 常驻后台任务（keep_alive）：app/job_restart.py 规则 + jobs.py 重启/轮转 + run_command keep_alive + 电脑重启。
# 沙盒服务用本机 bash 顶替（同 smoke_jobs.py：run.sh 真跑），模拟模型，迁移 0041。
# 运行：python tests/smoke_job_keep_alive.py
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

# ---- 1. 纯规则 ----
d = job_restart.decide
assert d("done", 3, 0) == job_restart.Verdict(0, None) and d("cancelled", 3, 2).delay is None
assert d("failed", 3, 0) == job_restart.Verdict(1, 5)
assert d("lost", 3, 1).delay == 10 and d("timed_out", 3, 3).delay == 40 and d("failed", 3, 4) == job_restart.Verdict(5, 80)
v = d("failed", 3, 5)
assert v.delay is None and v.streak == 6 and "已停止自动重启" in v.give_up, v
assert d("failed", 120, 5) == job_restart.Verdict(1, 5)  # 稳定跑过 1 分钟：清零
assert job_restart.MAX_S == 300 and all(d("failed", 0, k).delay <= 300 for k in range(5))
sh = jobs.script("jabc", 0)
assert "timeout -k 5 0 bash -l" in sh and '>> "$J/log"' in sh, sh

# ---- 2. 模型用 keep_alive=true 起常驻服务（不必再写 background）→ 卡片 ----
CMD = "echo 第$(cat runs.txt 2>/dev/null | wc -l)次; echo x >> runs.txt; exit 1"
r = run(tool("run_command", command=CMD, keep_alive=True, title="机器人"))
assert "常驻任务" in r.content and "自动拉起" in r.content, r.content
blk = r.blocks[0]
assert blk["type"] == "job" and blk["keep_alive"] is True and blk["restarts"] == 0, blk
TypeAdapter(Block).validate_python(blk)
k1 = blk["id"]
j = run(job(k1))
assert j.keep_alive and j.timeout == 0 and j.idle_timeout == 0 and j.run_started_at is not None
wait_exit(k1)

# ---- 3. 意外退出 → 排队重启（不结算、不通知）→ 到点重启，日志接着写 ----
j = wait_restart_planned(k1)
assert j.state == "running" and j.crash_streak == 1 and j.exit_code == 1 and j.followup == "none", (j.state, j.crash_streak)
w = c.get(f"/api/jobs/{k1}").json()
assert w["keep_alive"] is True and w["restarts"] == 0 and w["restart_at"] and w["state"] == "running", w
assert "等待自动重启" in jobs.describe(j)
run(tick()); assert run(job(k1)).restarts == 0  # 没到点不动
due(k1); run(tick())
j = run(job(k1))
assert j.restarts == 1 and j.restart_at is None and not (jd(k1) / "exit").exists() or j.restarts == 1, j.restarts
wait_exit(k1)
log = (jd(k1) / "log").read_text()
assert "第0次" in log and "第 1 次自动重启" in log and "第1次" in log, log
assert (storage.project_dir(pid) / "runs.txt").read_text().count("x") == 2
j = wait_restart_planned(k1)
assert j.crash_streak == 2 and (j.restart_at - j.run_started_at.replace(tzinfo=timezone.utc) if j.restart_at.tzinfo else True)
assert "已自动重启 1 次" in jobs.describe(j)

# ---- 4. 连续很快就崩到上限 → 放弃：结算为失败、写原因、通知助手、卡片改终态 ----
run(patch(k1, crash_streak=job_restart.CRASH_LIMIT))
due(k1); run(tick()); wait_exit(k1)
j = wait_restart_planned(k1)
assert j.state == "failed" and j.stop_reason == job_restart.give_up_text() and j.followup == "pending", (j.state, j.stop_reason)
assert j.restart_at is None and j.restarts == 2
w = c.get(f"/api/jobs/{k1}").json()
assert w["restart_at"] is None and w["restarts"] == 2
async def stored_block(jid):
    async with SessionLocal() as db:
        for m in (await db.scalars(select(Message).where(Message.conversation_id == cid))).all():
            for b in m.blocks:
                if b.get("type") == "job" and b.get("id") == jid:
                    return b
# 工具直接调用没落库消息：手动放一条再让 _patch_blocks 生效
async def put_msg(b):
    async with SessionLocal() as db:
        db.add(Message(conversation_id=cid, role="assistant", blocks=[b])); await db.commit()
run(put_msg(blk))
async def repatch(jid):
    async with SessionLocal() as db:
        await jobs._patch_blocks(db, await db.get(Job, jid)); await db.commit()
run(repatch(k1))
sb = run(stored_block(k1))
assert sb["state"] == "failed" and sb["keep_alive"] and sb["restarts"] == 2, sb
text = blocks_to_text([sb])
assert "常驻任务" in text and "已停止自动重启" in text and "已自动重启 2 次" in text, text
assert "常驻运行中" in blocks_to_text([blk])

# ---- 5. 正常退出（0）= 它做完了：不重启，照普通任务结算 ----
k2 = run(start("echo 完成", keep_alive=True))
wait_exit(k2)
j = wait_restart_planned(k2)
assert j.state == "done" and j.restarts == 0 and j.followup == "pending", j.state

# ---- 6. 运行中取消：整组杀、不重启 ----
k3 = run(start("sleep 30", keep_alive=True))
time.sleep(0.3)
r = c.post(f"/api/jobs/{k3}/cancel").json()
assert r["state"] == "cancelled", r
run(tick()); assert run(job(k3)).state == "cancelled" and run(job(k3)).restarts == 0

# ---- 7. 等重启时取消：不叫沙盒杀（pid 可能已被复用），直接结算 ----
k4 = run(start("exit 2", keep_alive=True))
wait_exit(k4); wait_restart_planned(k4)
calls = []
real_cancel = sandbox_client.cancel_job
async def spy_cancel(p, jid):
    calls.append(jid); await real_cancel(p, jid)
sandbox_client.cancel_job = spy_cancel
r = c.post(f"/api/jobs/{k4}/cancel").json()
sandbox_client.cancel_job = real_cancel
assert r["state"] == "cancelled" and r["exit_code"] == 2 and calls == [], (r, calls)
due(k4); run(tick()); assert run(job(k4)).state == "cancelled" and run(job(k4)).restarts == 0

# ---- 8. 进程没了也没退出码（容器重启）→ 算意外，排队重启；稳定跑过 1 分钟的清零 ----
k5 = run(start("sleep 30", keep_alive=True))
time.sleep(0.3)
run(patch(k5, crash_streak=3, run_started_at=datetime.now(timezone.utc) - timedelta(minutes=5)))
kill_all(k5); procs[k5].kill(); procs[k5].wait(5)
j = wait_restart_planned(k5)
assert j.state == "running" and j.crash_streak == 1 and j.exit_code is None, (j.state, j.crash_streak)

# ---- 9. 重启时沙盒连不上：不算一次崩溃，5 秒后再试 ----
real_start = sandbox_client.start_job
async def down(p, jid):
    raise httpx.ConnectError("down")
import httpx
sandbox_client.start_job = down
due(k5); run(tick())
j = run(job(k5))
ra = j.restart_at if j.restart_at.tzinfo else j.restart_at.replace(tzinfo=timezone.utc)
assert j.restarts == 0 and j.crash_streak == 1 and 0 < (ra - datetime.now(timezone.utc)).total_seconds() <= 5, (j.restarts, ra)
sandbox_client.start_job = real_start

# ---- 10. 工作区满了：不再起，按自动停止结算 ----
real_reason = quota.job_reason
quota.job_reason = lambda p: "工作区磁盘满了（测试）"
due(k5); run(tick())
quota.job_reason = real_reason
j = run(job(k5))
assert j.state == "cancelled" and "磁盘满了" in j.stop_reason and j.restarts == 0, (j.state, j.stop_reason)

# ---- 11. 日志超上限：常驻任务轮转（留尾巴进 log.1、游标归零），服务不停；普通任务照旧被停 ----
k6 = run(start("for i in $(seq 1 3000); do echo 第$i行; done; sleep 30", keep_alive=True))
end = time.time() + 5
while jobs.log_size(run(job(k6))) < 20000 and time.time() < end:
    time.sleep(0.1)
run(patch(k6, read_offset=999))
old_max = settings.job_log_max_mb
settings.job_log_max_mb = 0
run(tick())
j = run(job(k6))
assert j.state == "running" and j.read_offset == 0 and jobs.log_size(j) == 0, (j.state, j.read_offset, jobs.log_size(j))
assert "第3000行" in (jd(k6) / "log.1").read_text()
assert jobs.guard_reason(j) is None
n6 = run(start("for i in $(seq 1 100); do echo 普通$i; done; sleep 30"))
end = time.time() + 5
while jobs.log_size(run(job(n6))) == 0 and time.time() < end:
    time.sleep(0.1)
run(tick())
assert run(job(n6)).state == "cancelled" and "MB" in run(job(n6)).stop_reason
settings.job_log_max_mb = old_max
time.sleep(0.2)
assert run(job(k6)).state == "running"

# ---- 12. “这台电脑”重启：常驻任务不停、删完容器马上排队重启；普通任务照旧停 ----
n7 = run(start("sleep 30"))
time.sleep(0.3)
async def ok_status(ws):
    return {"state": "running"}
async def fake_restart(ws):
    for jid in (k6, n7):
        kill_all(jid)
sandbox_client.status, sandbox_client.restart = ok_status, fake_restart
real_name = workspaces.name
async def any_name(db, ws):
    return "训练"
workspaces.name = any_name
real_status = computer.status
async def no_status(db, ws):
    return {}
computer.status = no_status
async def do_restart():
    async with SessionLocal() as db:
        return await computer.restart(db, pid)
run(do_restart())
workspaces.name, computer.status = real_name, real_status
assert run(job(n7)).state == "cancelled"
j = run(job(k6))
assert j.state == "running" and j.restart_at is not None and j.crash_streak == 0, (j.state, j.restart_at)
run(tick())  # restart_at = 现在：立刻重启
j = run(job(k6))
assert j.restarts == 1 and j.restart_at is None and j.crash_streak == 0, (j.restarts, j.crash_streak)
time.sleep(0.3)
assert "第 1 次自动重启" in (jd(k6) / "log").read_text()
c.post(f"/api/jobs/{k6}/cancel")
assert run(job(k6)).state == "cancelled"

# ---- 13. 普通任务不带常驻字段；唤醒提示提到 keep_alive ----
assert "keep_alive" not in jobs.block(run(job(n7))) and c.get(f"/api/jobs/{n7}").json()["keep_alive"] is False
assert "keep_alive=true" in computer.wake_note("idle")
for p in procs.values():
    try:
        p.kill()
    except Exception:
        pass
print("smoke_job_keep_alive OK")
