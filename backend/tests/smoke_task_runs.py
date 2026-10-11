# 冒烟：定时任务运行记录 + 失败提醒（模拟模型，不打真接口）。
# 成功 → 记录 ok、last_status=ok、带对话 id、无提醒；模型报错 → error + 原因 + 首次失败一张 action 卡
# （target=tasks、挂在任务上、未读）；接着失败不再发卡；下一份报告不会把失败卡收掉；恢复成功 → 失败卡收起；
# 面板任务的记录没有对话 id；工具抛异常也记成失败；没产出算失败；“立即运行” trigger=manual；
# 对话被删 → conversation_id 置 null；只留最近 KEEP 条；worker 重启把 running 标成中断；
# 接口 404 / limit / 新的在前；删任务连带删记录和卡。
# 运行：python tests/smoke_task_runs.py
import os, sys, asyncio, subprocess, tempfile
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from app import task_runs, worker
from app.auth import require_user
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, HomeCard, ScheduledTask, TaskRun
from app.routes import tasks as rt
from app.routes.resources import routers

mode = {"v": "ok"}

class Reply:
    def __init__(self, text): self.blocks = text_to_blocks(text)

async def fake_run_turn(db, conv, emit=None, **kw):  # 模拟模型
    m = mode["v"]
    if m == "ok":
        return Reply("报告内容")
    if m == "model_error":
        await emit({"type": "error", "message": "模型调用失败：401 key 无效"})
        return None
    if m == "empty":
        return None
    raise RuntimeError("工具炸了")
worker.run_turn = fake_run_turn

app = FastAPI()
for r in [rt.router, *routers]:
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)

async def seed(name, output="report"):
    async with SessionLocal() as db:
        t = ScheduledTask(name=name, prompt="做点事", cron="0 8 * * *", output=output)
        db.add(t); await db.commit()
        return t.id

def run(tid, m="ok"):
    mode["v"] = m
    asyncio.run(worker.run_task(tid))

def runs(tid, **q):
    r = c.get(f"/api/tasks/{tid}/runs", params=q)
    assert r.status_code == 200, r.text
    return r.json()

def task(tid):
    return next(x for x in c.get("/api/tasks").json() if x["id"] == tid)

def alerts(tid, live=True):
    return [x for x in c.get("/api/cards").json()
            if x["task_id"] == tid and x["kind"] == "action" and (not live or not x["dismissed"])]

rep = asyncio.run(seed("每日新闻"))
assert task(rep)["last_status"] is None and runs(rep) == []

run(rep)
[r1] = runs(rep)
assert r1["status"] == "ok" and r1["error"] is None and r1["trigger"] == "schedule", r1
assert r1["conversation_id"] and r1["duration_ms"] is not None and r1["finished_at"], r1
assert task(rep)["last_status"] == "ok" and alerts(rep) == []

run(rep, "model_error")
r2 = runs(rep)[0]
assert r2["status"] == "error" and "401" in r2["error"], r2
assert task(rep)["last_status"] == "error"
[a] = alerts(rep)
assert a["target"] == "tasks" and a["unread"] and "每日新闻" in a["title"] and a["action_prompt"], a
assert "401" in a["blocks"][0]["text"], a
reports = [x for x in c.get("/api/cards").json() if x["task_id"] == rep and x["kind"] == "report" and not x["dismissed"]]
assert len(reports) == 1, "失败时仍投递一份（说明没跑成功的）报告，旧报告收起"

run(rep, "crash")                                    # 连着失败：不再发卡，失败卡也没被新报告收掉
r3 = runs(rep)[0]
assert r3["status"] == "error" and "RuntimeError" in r3["error"] and "工具炸了" in r3["error"], r3
assert [x["id"] for x in alerts(rep)] == [a["id"]]

run(rep, "empty")
assert runs(rep)[0]["error"] == task_runs.NO_OUTPUT and len(alerts(rep)) == 1

run(rep)                                             # 恢复：失败卡收起
assert task(rep)["last_status"] == "ok" and alerts(rep) == [] and len(alerts(rep, live=False)) == 1

run(rep, "model_error")                              # 新一轮连续失败：再提醒一次
assert len(alerts(rep)) == 1 and len(alerts(rep, live=False)) == 2

hist = runs(rep)                                     # 新的在前、limit
assert [h["status"] for h in hist] == ["error", "ok", "error", "error", "error", "ok"], hist
assert len(runs(rep, limit=2)) == 2
assert c.get(f"/api/tasks/{rep}/runs", params={"limit": 0}).status_code == 422
assert c.get("/api/tasks/nope/runs").status_code == 404

async def drop_conv(cid):                            # 对话被删 → 记录里置 null
    async with SessionLocal() as db:
        await db.execute(delete(Conversation).where(Conversation.id == cid)); await db.commit()
asyncio.run(drop_conv(hist[1]["conversation_id"]))
assert runs(rep)[1]["conversation_id"] is None and runs(rep)[0]["conversation_id"]

c.post(f"/api/tasks/{rep}/run")                      # 立即运行
run(rep)
assert runs(rep)[0]["trigger"] == "manual"

pan = asyncio.run(seed("天气面板", "panel"))         # 面板：没有对话 id；失败提醒文案提到面板
run(pan)
assert runs(pan)[0]["status"] == "ok" and runs(pan)[0]["conversation_id"] is None
run(pan, "model_error")
[pa] = alerts(pan)
assert "面板" in pa["blocks"][0]["text"], pa
panel = next(x for x in c.get("/api/cards").json() if x["task_id"] == pan and x["kind"] == "panel")
assert panel["blocks"] and "报告内容" in panel["blocks"][0]["text"], "失败时面板保留上一次内容"

old_keep = task_runs.KEEP                            # 只留最近 KEEP 条
task_runs.KEEP = 3
for _ in range(5):
    run(pan)
task_runs.KEEP = old_keep
async def count(tid):
    async with SessionLocal() as db:
        return await db.scalar(select(func.count()).select_from(TaskRun).where(TaskRun.task_id == tid))
assert asyncio.run(count(pan)) == 3

async def stale():                                   # worker 被杀留下的 running → 启动时标中断
    async with SessionLocal() as db:
        t = await db.get(ScheduledTask, pan)
        await task_runs.start(db, t, worker.datetime.now(worker.timezone.utc)); await db.commit()
    async with SessionLocal() as db:
        return await task_runs.recover_stale(db)
assert runs(pan)[0]["status"] == "ok"
assert asyncio.run(stale()) == 1
r = runs(pan)[0]
assert r["status"] == "error" and r["error"] == task_runs.INTERRUPTED and task(pan)["last_status"] == "error"

assert c.delete(f"/api/tasks/{rep}").status_code in (200, 204)   # 删任务：记录和卡一起走
assert asyncio.run(count(rep)) == 0
assert [x for x in c.get("/api/cards").json() if x["task_id"] == rep] == []
print("smoke_task_runs ok")
