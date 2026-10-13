# 冒烟：v2.35 启动观察（app/job_startup.py，E2E B11）：后台 / 常驻任务一启动就退出 → run_command 直接回失败 + 退出码 + 日志尾。
# 沙盒服务用本机 bash 顶替（同 smoke_job_keep_alive.py：run.sh 真跑），不需要模型。无迁移。
# 运行：python tests/smoke_job_startup.py
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


from app import job_startup
load_builtin()

def run(coro):
    return asyncio.run(coro)

async def seed():
    async with SessionLocal() as db:
        p = Project(name="网站", emoji="🌐"); db.add(p); await db.flush()
        conv = Conversation(title="起服务", project_id=p.id); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("把网站跑起来")))
        await db.commit()
        return p.id, conv.id
pid, cid = run(seed())

async def tool(name, **args):
    async with SessionLocal() as db:
        return await REGISTRY[name].run(ToolContext(db=db, project_id=pid, conversation_id=cid), **args)
async def job(jid):
    async with SessionLocal() as db:
        return await db.get(Job, jid)

# 1. 普通后台任务一启动就报错退出：失败 + 退出码 + 日志尾；已结算、不再事后叫醒
t0 = time.time()
r = run(tool("run_command", command="echo 'OSError: [Errno 98] Address already in use' >&2; exit 3", background=True, title="网站"))
assert time.time() - t0 < job_startup.WATCH_S + 1.5, "退出了就该马上回，不用等满"
b = r.blocks[0]
j = run(job(b["id"]))
assert r.failed == "刚启动就退出了", r.failed
assert "退出码 3" in r.content and "Address already in use" in r.content and "没在跑" in r.content and "preview_port" in r.content, r.content
assert j.state == "failed" and j.exit_code == 3 and j.followup == "seen", (j.state, j.followup)
assert b["state"] == "failed", b

# 2. 常驻服务启动即崩：不进自动重启，直接失败，原因写明
r = run(tool("run_command", command="python3 -c 'import nosuchmod'", keep_alive=True, title="机器人"))
j = run(job(r.blocks[0]["id"]))
assert j.state == "failed" and j.restart_at is None and j.followup == "seen", (j.state, j.restart_at, j.followup)
assert j.stop_reason == job_startup.crash_reason(1) and "没有自动重启" in r.content and "nosuchmod" in r.content, r.content
assert (j.crash_streak or 0) == 0

# 3. 很快跑完的后台任务（退出码 0）：直接带输出回，不再有结束通知
r = run(tool("run_command", command="echo 打包完成 3 个文件", background=True))
j = run(job(r.blocks[0]["id"]))
assert r.failed == "" and "已经跑完了" in r.content and "打包完成 3 个文件" in r.content, r.content
assert j.state == "done" and j.followup == "seen"

# 4. 常驻服务正常退出（0）：照普通结束
r = run(tool("run_command", command="echo once", keep_alive=True))
assert run(job(r.blocks[0]["id"])).state == "done" and r.failed == ""

# 5. 还活着：照旧“已在后台启动”，附上已有输出；状态 running，followup 仍是 none（结束时照常通知）
t0 = time.time()
r = run(tool("run_command", command="echo 'Serving on :8080'; sleep 30", keep_alive=True, title="站点"))
assert time.time() - t0 >= job_startup.WATCH_S - 0.1
jid = r.blocks[0]["id"]
j = run(job(jid))
assert j.state == "running" and j.followup == "none" and "已在后台启动常驻任务" in r.content and "Serving on :8080" in r.content, r.content
run(tool("cancel_job", job_id=jid))
r = run(tool("run_command", command="sleep 30", background=True))
assert "已有的输出" not in r.content and "已在后台启动任务" in r.content, r.content  # 没输出就不加那句
run(tool("cancel_job", job_id=r.blocks[0]["id"]))

# 直接测“库里已结”的分支：本会话对象过期 → refresh 后不是 running
async def race2():
    async with SessionLocal() as db:
        jid = (await jobs.start(db, project_id=pid, command="exit 2", conversation_id=cid)).id
    end = time.time() + 5
    while not (storage.project_dir(pid) / ".jobs" / jid / "exit").exists() and time.time() < end:
        await asyncio.sleep(0.05)
    async with SessionLocal() as mine, SessionLocal() as worker:
        j = await mine.get(Job, jid)  # 本会话：running
        await jobs.refresh(worker, await worker.get(Job, jid))  # worker 结掉，followup pending
        s = await job_startup.watch(mine, j)
        assert s.exited and j.state == "failed" and j.followup == "seen", (j.state, j.followup)
    assert (await job(jid)).followup == "seen"
    return jid
run(race2())

# 7. 关掉观察（WATCH_S=0）：退出码还没写出来就照旧回“已启动”
job_startup.WATCH_S = 0
r = run(tool("run_command", command="sleep 0.5; exit 1", background=True))
assert "已在后台启动任务" in r.content and run(job(r.blocks[0]["id"])).state == "running"
print("smoke_job_startup OK")
