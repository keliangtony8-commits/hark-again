# 冒烟：v1.84 定时脚本（app/script_tasks.py）：到点不叫模型，在工作区沙盒里当后台任务跑命令；notify 决定告不告诉用户。
# 沙盒服务用本机 bash 顶替（同 smoke_job_keep_alive.py：run.sh 真跑），模拟模型（脚本任务不该调用它），迁移 0042。
# 运行：python tests/smoke_script_tasks.py
import os, sys, asyncio, subprocess, tempfile, json, signal, time
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
from sqlalchemy import delete, select
from app import jobs, sandbox_client, script_tasks, storage, task_runs, worker
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.auth import require_user
from app.db import SessionLocal
from app.models import Conversation, HomeCard, Job, Message, Project, ScheduledTask, TaskRun
from app.routes import tasks as rt
from app.routes.resources import routers

# ---- 本机顶替沙盒服务 ----
procs: dict[str, subprocess.Popen] = {}
sandbox_down = {"v": False}
async def start_job(pid, jid):
    if sandbox_down["v"]:
        import httpx
        raise httpx.ConnectError("down")
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
        os.kill(p, 0)
        return True
    except ProcessLookupError:
        return False
async def remove(pid):
    return None
sandbox_client.start_job, sandbox_client.cancel_job, sandbox_client.job_alive = start_job, cancel_job, job_alive
sandbox_client.remove = remove
jobs.LOST_GRACE = 2

async def no_model(*a, **k):
    raise AssertionError("定时脚本不该调用模型")
worker.run_turn = no_model

load_builtin()
app = FastAPI()
for rr in [rt.router, *routers]:
    app.include_router(rr)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)

# ---- 1. 接口校验 ----
assert c.post("/api/tasks", json={"name": "x", "prompt": "  ", "kind": "script", "cron": "0 3 * * *"}).status_code == 422
assert c.post("/api/tasks", json={"name": "x", "prompt": "ls", "kind": "script", "notify": "never", "cron": "0 3 * * *"}).status_code == 422
assert c.post("/api/tasks", json={"name": "x", "prompt": "ls", "kind": "shell", "cron": "0 3 * * *"}).status_code == 422
assert c.post("/api/tasks", json={"name": "x", "prompt": "x" * 4001, "kind": "script", "cron": "0 3 * * *"}).status_code == 422
a = c.post("/api/tasks", json={"name": "普通", "prompt": "总结", "cron": "0 8 * * *", "project_id": "p"}).json()
assert a["kind"] == "agent" and a["notify"] == "failure" and a["project_id"] is None, a
s = c.post("/api/tasks", json={"name": "备份", "prompt": "echo hi", "kind": "script", "cron": "0 3 * * *"}).json()
assert s["kind"] == "script" and s["notify"] == "failure", s
assert c.patch(f"/api/tasks/{s['id']}", json={"notify": "sometimes"}).status_code == 422
assert c.patch(f"/api/tasks/{s['id']}", json={"prompt": ""}).status_code == 422
assert c.patch(f"/api/tasks/{s['id']}", json={"notify": "always"}).json()["notify"] == "always"
assert c.patch(f"/api/tasks/{a['id']}", json={"prompt": ""}).status_code == 200  # 普通任务不受脚本规则约束（原样）
print("1 api ok")


async def settle_all(timeout=15):
    """模拟 worker 的 tick：对一遍后台任务，再收脚本运行，直到没有 running 的脚本运行。"""
    end = time.time() + timeout
    while time.time() < end:
        async with SessionLocal() as db:
            await jobs.tick(db)
            await script_tasks.settle_ready(db)
            left = await db.scalar(select(TaskRun.id).where(TaskRun.status == "running", TaskRun.job_id.is_not(None)))
        if left is None:
            return
        await asyncio.sleep(0.2)
    raise AssertionError("脚本没跑完")


async def mk(name, command, notify="failure", project_id=None):
    async with SessionLocal() as db:
        t = ScheduledTask(name=name, prompt=command, cron="0 3 * * *", kind="script", notify=notify, project_id=project_id)
        db.add(t); await db.commit()
        return t.id


async def state(tid):
    async with SessionLocal() as db:
        t = await db.get(ScheduledTask, tid)
        runs = (await db.scalars(select(TaskRun).where(TaskRun.task_id == tid).order_by(TaskRun.started_at.desc()))).all()
        cards = (await db.scalars(select(HomeCard).where(HomeCard.task_id == tid))).all()
        return t, runs, cards


async def tool(_tool, pid=None, **args):
    async with SessionLocal() as db:
        return (await REGISTRY[_tool].run(ToolContext(db=db, project_id=pid), **args))


async def main():
    # ---- 2. 工具 ----
    async with SessionLocal() as db:
        p = Project(name="爬虫"); db.add(p); await db.commit(); pid = p.id
    out = await tool("schedule_task", pid=pid, action="create", name="抓价格", command="echo 99", cron="0 * * * *", notify="change")
    assert "脚本" in out.content and "输出变了" in out.content, out.content
    async with SessionLocal() as db:
        t = await db.scalar(select(ScheduledTask).where(ScheduledTask.name == "抓价格"))
        assert t.kind == "script" and t.project_id == pid and t.prompt == "echo 99" and t.notify == "change"
        tool_tid = t.id
    out = await tool("schedule_task", action="create", name="x", command="ls", prompt="总结", cron="0 3 * * *")
    assert "只给一个" in out.content
    out = await tool("schedule_task", action="update", id=tool_tid, prompt="总结")
    assert "command" in out.content
    out = await tool("schedule_task", action="update", id=a["id"], command="ls")
    assert "不能改成脚本" in out.content
    out = await tool("schedule_task", action="update", id=tool_tid, command="echo 100", notify="always")
    assert "echo 100" in out.content and "每次" in out.content, out.content
    out = await tool("schedule_task", action="list")
    assert "抓价格" in out.content and "脚本" in out.content
    print("2 tool ok")

    # ---- 3. failure 模式成功：静悄悄，不开对话、不放卡 ----
    tid = await mk("静默", "echo quiet")
    await worker.run_task(tid)
    await settle_all()
    t, runs, cards = await state(tid)
    assert len(runs) == 1 and runs[0].status == "ok" and runs[0].conversation_id is None and runs[0].job_id, [(r.status, r.error, r.conversation_id, r.job_id) for r in runs]
    assert not cards and t.last_status == "ok" and t.output_digest and t.fail_streak == 0
    async with SessionLocal() as db:
        job = await db.get(Job, runs[0].job_id)
        assert job.project_id == "me" and job.conversation_id is None and job.task_id == tid and job.followup == "none"
    print("3 quiet ok")

    # ---- 4. always：对话 + 任务卡 + 收件箱卡 ----
    tid = await mk("每次", "echo hello", notify="always")
    await worker.run_task(tid)
    await settle_all()
    t, runs, cards = await state(tid)
    assert runs[0].status == "ok" and runs[0].conversation_id, (runs[0].status, runs[0].error)
    reports = [c_ for c_ in cards if c_.kind == "report"]
    assert len(reports) == 1 and reports[0].conversation_id == runs[0].conversation_id and "跑完了" in reports[0].blocks[0]["text"]
    async with SessionLocal() as db:
        msgs = (await db.scalars(select(Message).where(Message.conversation_id == runs[0].conversation_id).order_by(Message.created_at))).all()
        assert [m.role for m in msgs] == ["user", "assistant"]
        jb = [b for b in msgs[1].blocks if b["type"] == "job"][0]
        assert jb["state"] == "done" and "hello" in jb["tail"], jb
    await worker.run_task(tid); await settle_all()
    t, runs, cards = await state(tid)
    assert len(runs) == 2 and len([c_ for c_ in cards if c_.kind == "report" and not c_.dismissed]) == 1  # 只留最新一张
    print("4 always ok")

    # ---- 5. change：第一次告诉、一样不告诉、变了告诉 ----
    async with SessionLocal() as db:
        t = await db.get(ScheduledTask, tool_tid); t.notify = "change"; await db.commit()
    await worker.run_task(tool_tid); await settle_all()
    t, runs, cards = await state(tool_tid)
    assert runs[0].conversation_id and "第一次" in [c_ for c_ in cards if c_.kind == "report"][-1].blocks[0]["text"]
    async with SessionLocal() as db:
        conv = await db.get(Conversation, runs[0].conversation_id)
        assert conv.project_id == pid  # 对话落在脚本所在的项目
        job = await db.get(Job, runs[0].job_id); assert job.project_id == pid
    await worker.run_task(tool_tid); await settle_all()
    t, runs, cards = await state(tool_tid)
    assert runs[0].status == "ok" and runs[0].conversation_id is None
    async with SessionLocal() as db:
        t = await db.get(ScheduledTask, tool_tid); t.prompt = "echo 101"; await db.commit()
    await worker.run_task(tool_tid); await settle_all()
    t, runs, cards = await state(tool_tid)
    assert runs[0].conversation_id and "不一样" in [c_ for c_ in cards if c_.kind == "report" and not c_.dismissed][0].blocks[0]["text"]
    print("5 change ok")

    # ---- 6. 失败：记原因、开对话、首次失败提醒卡，连续 3 次自动暂停 ----
    tid = await mk("会挂", "echo boom; exit 3")
    await worker.run_task(tid); await settle_all()
    t, runs, cards = await state(tid)
    assert runs[0].status == "error" and "退出码 3" in runs[0].error and runs[0].conversation_id, runs[0].error
    assert t.fail_streak == 1 and t.last_status == "error" and any(c_.kind == "action" for c_ in cards), [c_.kind for c_ in cards]
    for _ in range(2):
        await worker.run_task(tid); await settle_all()
    t, runs, cards = await state(tid)
    assert not t.active and t.paused_reason == task_runs.PAUSED_BY_FAILURES
    print("6 failure ok")

    # ---- 7. 重叠：上一次还在跑就跳过；8. worker 重启不把它当中断 ----
    tid = await mk("慢", "sleep 3; echo done")
    await worker.run_task(tid)
    await asyncio.sleep(0.5)
    await worker.run_task(tid)
    t, runs, _ = await state(tid)
    assert len(runs) == 1 and runs[0].status == "running" and t.last_run_at is not None
    async with SessionLocal() as db:
        assert await task_runs.recover_stale(db) == 0
    t, runs, _ = await state(tid)
    assert runs[0].status == "running"
    await settle_all()
    t, runs, _ = await state(tid)
    assert runs[0].status == "ok"
    print("7/8 overlap + recover ok")

    # ---- 9. 起不来：沙盒没响应 → 当场失败；手动运行记成 manual ----
    tid = await mk("沙盒挂了", "echo x")
    async with SessionLocal() as db:
        (await db.get(ScheduledTask, tid)).run_requested = True; await db.commit()
    sandbox_down["v"] = True
    await worker.run_task(tid)
    sandbox_down["v"] = False
    t, runs, _ = await state(tid)
    assert runs[0].status == "error" and "沙盒没响应" in runs[0].error and runs[0].trigger == "manual" and not t.run_requested
    print("9 start failure ok")

    # ---- 10. 后台任务记录没了 → 记失败，不永远挂着 ----
    tid = await mk("孤儿", "sleep 2")
    await worker.run_task(tid)
    t, runs, _ = await state(tid)
    async with SessionLocal() as db:
        await db.execute(delete(Job).where(Job.id == runs[0].job_id)); await db.commit()
        await script_tasks.settle_ready(db)
    t, runs, _ = await state(tid)
    assert runs[0].status == "error" and runs[0].error == script_tasks.LOST_RECORD
    await asyncio.sleep(2.5)
    print("10 orphan ok")


asyncio.run(main())

# ---- 11. 删项目连带删它的脚本；接口给出 job_id ----
tasks_before = c.get("/api/tasks").json()
script_row = next(t for t in tasks_before if t["name"] == "抓价格")
runs = c.get(f"/api/tasks/{script_row['id']}/runs").json()
assert runs and "job_id" in runs[0]
assert c.delete(f"/api/projects/{script_row['project_id']}").status_code in (200, 204)
assert not any(t["name"] == "抓价格" for t in c.get("/api/tasks").json())
print("11 project cascade ok")
print("smoke_script_tasks OK")
