# 冒烟：定时任务连续失败升级（模拟模型，不打真接口）。
# 第 1 次失败 → 首次失败卡、fail_streak=1；第 2 次 → 不发卡、streak=2；第 3 次 → 自动暂停（active=False,
# paused_reason=failures），首次失败卡被“已暂停”卡顶替（只剩一张活卡、有“去做”）；暂停后再失败不再发卡；
# 手动“立即运行”成功 → 自动恢复、归零、卡收起；再连败 3 次又暂停（去重键已清 → 再提醒）；
# 用户 PATCH active=true → 恢复、归零、卡收起；用户手动停 → paused_reason 仍为 null；
# 一次性任务失败不暂停；中间成功一次 → streak 归零；智能体工具 list 写明“已自动暂停”；迁移回填老失败任务。
# 运行：python tests/smoke_task_autopause.py
import os, sys, asyncio, subprocess, tempfile
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
# 先停在 0023，塞一条“上次失败”的老任务，再升到 head 验回填
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "0023"], cwd=root, check=True, capture_output=True)
import sqlite3
con = sqlite3.connect(db_path)
con.execute("INSERT INTO scheduled_tasks (id, name, prompt, cron, active, output, run_requested, last_status, created_at)"
            " VALUES ('old1', '老任务', 'x', '0 8 * * *', 1, 'report', 0, 'error', '2026-01-01 00:00:00')")
con.commit(); con.close()
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from datetime import datetime, timedelta, timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import task_runs, worker
from app.agent.builtin import tasks as task_tools
from app.auth import require_user
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import ScheduledTask
from app.routes import tasks as rt
from app.routes.resources import routers

mode = {"v": "ok"}

class Reply:
    def __init__(self, text): self.blocks = text_to_blocks(text)

async def fake_run_turn(db, conv, emit=None, **kw):  # 模拟模型
    if mode["v"] == "ok":
        return Reply("报告内容")
    await emit({"type": "error", "message": "模型调用失败：401 key 无效"})
    return None
worker.run_turn = fake_run_turn

app = FastAPI()
for r in [rt.router, *routers]:
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)

def task(tid):
    return next(x for x in c.get("/api/tasks").json() if x["id"] == tid)

assert task("old1")["fail_streak"] == 1 and task("old1")["paused_reason"] is None

async def seed(name, cron="0 8 * * *", run_at=None):
    async with SessionLocal() as db:
        t = ScheduledTask(name=name, prompt="做点事", cron=cron, run_at=run_at)
        db.add(t); await db.commit()
        return t.id

def run(tid, m="ok"):
    mode["v"] = m
    asyncio.run(worker.run_task(tid))

def alerts(tid):
    return [x for x in c.get("/api/cards").json() if x["task_id"] == tid and x["kind"] == "action" and not x["dismissed"]]

tid = asyncio.run(seed("每日新闻"))
run(tid, "fail")
t = task(tid); [a1] = alerts(tid)
assert t["fail_streak"] == 1 and t["active"] and t["paused_reason"] is None, t
assert "没跑成功" in a1["title"], a1
run(tid, "fail")
assert task(tid)["fail_streak"] == 2 and [x["id"] for x in alerts(tid)] == [a1["id"]]
run(tid, "fail")
t = task(tid); [a3] = alerts(tid)
assert t["fail_streak"] == task_runs.PAUSE_AFTER and not t["active"] and t["paused_reason"] == "failures", t
assert t["next_run_at"] is None, t
assert "已暂停" in a3["title"] and a3["action_prompt"] and a3["target"] == "tasks" and a3["unread"], a3
assert a3["id"] != a1["id"]

# 工具 list 让模型知道
async def listed():
    async with SessionLocal() as db:
        t = await db.get(ScheduledTask, tid)
        return task_tools._line(t)
assert "已自动暂停" in asyncio.run(listed())

# 暂停后（手动）再失败：不再发卡
run(tid, "fail")
assert [x["id"] for x in alerts(tid)] == [a3["id"]] and task(tid)["fail_streak"] == 4

# 手动试跑成功 → 自动恢复
c.post(f"/api/tasks/{tid}/run")
run(tid, "ok")
t = task(tid)
assert t["active"] and t["paused_reason"] is None and t["fail_streak"] == 0 and alerts(tid) == [], t

# 再连败 3 次 → 又暂停、又提醒（去重键被清过）
for _ in range(3):
    run(tid, "fail")
t = task(tid)
assert not t["active"] and t["paused_reason"] == "failures"
[a4] = alerts(tid)
assert "已暂停" in a4["title"] and a4["id"] != a3["id"]

# 用户在任务上重新启用 → 归零、收起
r = c.patch(f"/api/tasks/{tid}", json={"active": True})
assert r.status_code == 200, r.text
t = r.json()
assert t["active"] and t["paused_reason"] is None and t["fail_streak"] == 0, t
assert alerts(tid) == []
# 恢复后再失败一次：重新从首次失败算
run(tid, "fail")
assert task(tid)["fail_streak"] == 1 and len(alerts(tid)) == 1

# 用户手动停：不是“自动暂停”
r = c.patch(f"/api/tasks/{tid}", json={"active": False}).json()
assert r["paused_reason"] is None and not r["active"]

# 中间成功一次 → 归零，不会累计到暂停
t2 = asyncio.run(seed("周报"))
for m in ["fail", "fail", "ok", "fail", "fail"]:
    run(t2, m)
t = task(t2)
assert t["active"] and t["fail_streak"] == 2, t

# 一次性任务失败不暂停（跑过就完了）
once = asyncio.run(seed("提醒一次", cron="", run_at=datetime.now(timezone.utc) + timedelta(hours=1)))
for _ in range(3):
    run(once, "fail")
t = task(once)
assert t["paused_reason"] is None and t["fail_streak"] == 3, t

print("smoke_task_autopause OK")
