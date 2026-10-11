# 冒烟：任务接口带 next_run_at（只读、算出来的），与 worker 的 is_due 同一套计算。
# 新建 → 下次按 cron 在用户时区；停用 → null；改 cron → 跟着变；跑过一次 → 从上次运行往后算；
# 过期未跑（worker 停过）→ 显示为“现在”且 is_due；无效 cron → null；客户端传 next_run_at 被忽略。
# 运行：python tests/smoke_task_next_run.py
import os, sys, asyncio, subprocess, tempfile
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth import require_user
from app.db import SessionLocal
from app.models import ScheduledTask
from app.routes.resources import routers
from app.schedule import is_due, next_run_at

app = FastAPI()
for r in routers:
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
SH = ZoneInfo("Asia/Shanghai")

def parse(s): return datetime.fromisoformat(s)

t = c.post("/api/tasks", json={"name": "早报", "prompt": "x", "cron": "0 8 * * *"}).json()
nxt = parse(t["next_run_at"]).astimezone(SH)
assert (nxt.hour, nxt.minute) == (8, 0), nxt
assert timedelta(0) < nxt - datetime.now(SH) <= timedelta(days=1), nxt
assert c.get(f"/api/tasks/{t['id']}").json()["next_run_at"] == t["next_run_at"]
assert c.get("/api/tasks").json()[0]["next_run_at"] == t["next_run_at"]

off = c.patch(f"/api/tasks/{t['id']}", json={"active": False}).json()
assert off["next_run_at"] is None
on = c.patch(f"/api/tasks/{t['id']}", json={"active": True, "cron": "30 21 * * *"}).json()
n2 = parse(on["next_run_at"]).astimezone(SH)
assert (n2.hour, n2.minute) == (21, 30), n2

# 客户端写不进来（不在 TaskPatch 里）
same = c.patch(f"/api/tasks/{t['id']}", json={"next_run_at": "2000-01-01T00:00:00+00:00"}).json()
assert same["next_run_at"] == on["next_run_at"]

async def check():
    now = datetime.now(timezone.utc)
    # 从上次运行往后算：上次是今天 21:30 之后 → 下次是明天 21:30
    last = datetime.now(SH).replace(hour=21, minute=31, second=0, microsecond=0)
    task = ScheduledTask(name="a", prompt="x", cron="30 21 * * *", last_run_at=last, created_at=now, active=True, run_requested=False)
    n = next_run_at(task, now).astimezone(SH)
    assert n.date() == (last + timedelta(days=1)).date() and n.hour == 21, n
    # 过期未跑：上次运行在三天前 → 应该马上补跑，显示为现在
    stale = ScheduledTask(name="b", prompt="x", cron="0 8 * * *", last_run_at=now - timedelta(days=3), created_at=now, active=True, run_requested=False)
    assert is_due(stale, now)
    assert abs((next_run_at(stale, now) - now).total_seconds()) < 1
    # SQLite 读回来的无时区时间按 UTC 处理
    naive = ScheduledTask(name="c", prompt="x", cron="0 * * * *", last_run_at=(now - timedelta(minutes=5)).replace(tzinfo=None), created_at=now, active=True, run_requested=False)
    # （上次运行可能在上个整点之前 → 已过期 = 显示“现在”，所以是 >=；跨整点时间段不再偶发失败）
    assert next_run_at(naive, now) >= now - timedelta(seconds=1)
    bad = ScheduledTask(name="d", prompt="x", cron="不是 cron", created_at=now, active=True, run_requested=False)
    assert next_run_at(bad, now) is None and not is_due(bad, now)
    # 存库再读回（SQLite）：路由给出的与函数一致
    async with SessionLocal() as db:
        db.add(ScheduledTask(id="z", name="z", prompt="x", cron="0 8 * * *", last_run_at=now - timedelta(days=3)))
        await db.commit()
asyncio.run(check())
z = c.get("/api/tasks/z").json()
assert abs((parse(z["next_run_at"]) - datetime.now(timezone.utc)).total_seconds()) < 5, z

print("smoke_task_next_run OK")
