# 冒烟：一次性任务（run_at）+ 智能体工具 schedule_task（模拟模型，不打真接口）。
# 接口：cron/run_at 二选一（都给/都不给/cron 无效 → 422），next_run_at = run_at、done=false；PATCH 合并后仍校验；
# 到点 is_due → worker 跑一次 → done=true、next_run_at=null、不再到点、结果进收件箱；把 run_at 改到以后 → 重新排上；
# 一次性 ↔ 重复互换；工具：create（本地时间字符串，过去的时间拒绝、二选一校验）、list 带 id、update 改时刻、cancel 连带删卡。
# 运行：python tests/smoke_once_task.py
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
from sqlalchemy import select
from app import worker
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.auth import require_user
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import HomeCard, ScheduledTask
from app.routes.resources import routers
from app.schedule import is_due

class Reply:
    def __init__(self, text): self.blocks = text_to_blocks(text)

async def fake_run_turn(db, conv, emit=None, **kw):
    return Reply("提醒：交作业")
worker.run_turn = fake_run_turn

app = FastAPI()
for r in routers:
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
SH = ZoneInfo("Asia/Shanghai")
parse = datetime.fromisoformat
now = datetime.now(timezone.utc)

# —— 接口校验 ——
for bad in [{"cron": "0 8 * * *", "run_at": (now + timedelta(hours=1)).isoformat()}, {}, {"cron": "不是 cron"}]:
    r = c.post("/api/tasks", json={"name": "x", "prompt": "y", **bad})
    assert r.status_code == 422, (bad, r.status_code, r.text)

at = now + timedelta(hours=2)
t = c.post("/api/tasks", json={"name": "交作业", "prompt": "提醒我：交作业", "run_at": at.isoformat()}).json()
assert t["cron"] == "" and t["done"] is False, t
assert abs((parse(t["next_run_at"]) - at).total_seconds()) < 1, t
assert abs((parse(t["run_at"]) - at).total_seconds()) < 1, t
rep = c.post("/api/tasks", json={"name": "早报", "prompt": "x", "cron": "0 8 * * *"}).json()
assert rep["run_at"] is None and rep["done"] is False

# PATCH 合并后仍要成立
assert c.patch(f"/api/tasks/{t['id']}", json={"cron": "0 9 * * *"}).status_code == 422  # 两个都有
assert c.patch(f"/api/tasks/{rep['id']}", json={"cron": ""}).status_code == 422        # 两个都没有
assert c.patch(f"/api/tasks/{rep['id']}", json={"cron": "坏"}).status_code == 422

# —— 到点 → 跑 → 已完成 ——
async def get(tid):
    async with SessionLocal() as db:
        return await db.get(ScheduledTask, tid)
task = asyncio.run(get(t["id"]))
assert not is_due(task, now) and is_due(task, at + timedelta(seconds=1))
# “立即运行”（提前跑）不消耗这次提醒：跑完仍排在 run_at
asyncio.run(worker.run_task(t["id"]))
early = c.get(f"/api/tasks/{t['id']}").json()
assert early["done"] is False and early["next_run_at"], early
# 到点：把时刻挪到刚过去，worker 照 is_due 领走
c.patch(f"/api/tasks/{t['id']}", json={"run_at": (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()})
asyncio.run(worker.tick())
done = c.get(f"/api/tasks/{t['id']}").json()
assert done["done"] is True and done["next_run_at"] is None and done["last_status"] == "ok", done
task = asyncio.run(get(t["id"]))
assert not is_due(task, at + timedelta(days=30)), "已完成的一次性任务不该再跑"
cards = [x for x in c.get("/api/cards").json() if x["task_id"] == t["id"]]
assert cards and cards[0]["unread"], cards  # 结果进收件箱

# 改到以后 → 重新排上
later = datetime.now(timezone.utc) + timedelta(days=1)
again = c.patch(f"/api/tasks/{t['id']}", json={"run_at": later.isoformat()}).json()
assert again["done"] is False and abs((parse(again["next_run_at"]) - later).total_seconds()) < 1, again

# 一次性 ↔ 重复
rr = c.patch(f"/api/tasks/{t['id']}", json={"cron": "30 7 * * *", "run_at": None}).json()
assert rr["run_at"] is None and rr["done"] is False and parse(rr["next_run_at"]).astimezone(SH).hour == 7, rr
oo = c.patch(f"/api/tasks/{t['id']}", json={"cron": "", "run_at": later.isoformat()}).json()
assert oo["cron"] == "" and oo["run_at"], oo

# —— 智能体工具 ——
load_builtin()
tool = REGISTRY["schedule_task"]

async def call(**kw):
    async with SessionLocal() as db:
        return (await tool.run(ToolContext(db=db), **kw)).content

tomorrow = (datetime.now(SH) + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
out = asyncio.run(call(action="create", name="带伞", prompt="提醒我：带伞", run_at=tomorrow.strftime("%Y-%m-%d %H:%M")))
assert "已安排" in out and tomorrow.strftime("%Y-%m-%d 08:00") in out, out
assert "已经过去" in asyncio.run(call(action="create", name="a", prompt="b", run_at="2020-01-01 08:00"))
assert "恰好选一个" in asyncio.run(call(action="create", name="a", prompt="b"))
assert "无效" in asyncio.run(call(action="create", name="a", prompt="b", cron="每天"))
assert "格式不对" in asyncio.run(call(action="create", name="a", prompt="b", run_at="明天早上"))
assert "已安排" in asyncio.run(call(action="create", name="周报", prompt="总结本周", cron="0 18 * * 5"))

listing = asyncio.run(call(action="list"))
assert "「带伞」" in listing and "「周报」" in listing and "id=" in listing, listing
umb = next(x for x in c.get("/api/tasks").json() if x["name"] == "带伞")
assert parse(umb["run_at"]).astimezone(SH) == tomorrow, umb

out = asyncio.run(call(action="update", id=umb["id"], run_at=tomorrow.replace(hour=7).strftime("%Y-%m-%d %H:%M")))
assert "07:00" in out, out
out = asyncio.run(call(action="update", id=umb["id"], cron="0 7 * * *"))  # 换成重复
assert "cron 0 7 * * *" in out and c.get(f"/api/tasks/{umb['id']}").json()["run_at"] is None, out
assert "没找到" in asyncio.run(call(action="cancel", id="nope"))

# cancel 连带删卡（接口与工具同一套 task_store）
async def card_for(tid):
    async with SessionLocal() as db:
        db.add(HomeCard(kind="report", title="x", task_id=tid, blocks=[])); await db.commit()
asyncio.run(card_for(umb["id"]))
assert "已删除" in asyncio.run(call(action="cancel", id=umb["id"]))
assert c.get(f"/api/tasks/{umb['id']}").status_code == 404
assert not [x for x in c.get("/api/cards").json() if x["task_id"] == umb["id"]]

print("smoke_once_task OK")
