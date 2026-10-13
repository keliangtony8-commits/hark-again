# 冒烟：v2.17 移除的面板可以找回（app/panel_trash.py，模拟模型，不打真接口）。
# 接口 POST /api/cards/{id}/remove：任务 + 运行记录 + 它的提醒卡删掉，面板卡留下（dismissed、task_id=None、revivable、
# 快照不外发）；非面板 422；重复移除幂等。manage_home list 末尾列“最近移除的面板”；revive（工具 + 接口）按快照新建任务
# （名字/指令/cron/模型/runbook/note 回来、run_requested、卡顶到最前、旧内容留着）；再 revive 404；
# 超过 30 天不可找回 + worker tick 的 purge 删卡；快照 cron 坏了回落每天 8 点；worker 跑找回后的任务原地刷新同一张卡；
# 迁移 0051 往返。
# 运行：python tests/smoke_panel_trash.py
import os, sys, asyncio, subprocess, tempfile
from datetime import datetime, timedelta, timezone
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
alembic = lambda *a: subprocess.run([sys.executable, "-m", "alembic", *a], cwd=root, check=True, capture_output=True)
alembic("upgrade", "head")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from app import panel_trash, worker
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.auth import require_user
from app.db import SessionLocal
from app.models import HomeCard, ScheduledTask, TaskRun
from app.routes import home
from app.routes.resources import routers

app = FastAPI()
app.include_router(home.router)
for r in routers:
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
load_builtin()

async def call(name, **kw):
    async with SessionLocal() as db:
        return (await REGISTRY[name].run(ToolContext(db=db), **kw)).content

async def db_do(fn):
    async with SessionLocal() as db:
        out = await fn(db)
        await db.commit()
        return out

# —— 一个有内容、有做法、有运行记录和失败提醒的面板 ——
assert "已放到 Home" in asyncio.run(call("create_panel", title="上海天气", prompt="查上海天气", cron="0 8 * * *"))
card = next(x for x in c.get("/api/cards").json() if x["kind"] == "panel")
tid = card["task_id"]
assert c.patch(f"/api/tasks/{tid}", json={"runbook": "用 wttr.in", "note": "周末多云", "reasoning": "high"}).status_code == 200
async def seed(db):
    (await db.get(HomeCard, card["id"])).blocks = [{"type": "markdown", "text": "晴 21°"}]
    db.add(TaskRun(task_id=tid, status="ok"))
    db.add(HomeCard(kind="action", title="面板刷新失败", blocks=[], task_id=tid))
    db.add(HomeCard(kind="action", title="回复老师", blocks=[]))
asyncio.run(db_do(seed))
other = next(x for x in c.get("/api/cards").json() if x["title"] == "回复老师")

# —— 移除 ——
assert c.post(f"/api/cards/{other['id']}/remove").status_code == 422  # 建议卡不是面板
assert c.post("/api/cards/nope/remove").status_code == 404
r = c.post(f"/api/cards/{card['id']}/remove")
assert r.status_code == 200 and r.json() == {"id": card["id"], "title": "上海天气", "revivable": True}, r.json()
assert c.post(f"/api/cards/{card['id']}/remove").status_code == 200  # 幂等
assert c.get(f"/api/tasks/{tid}").status_code == 404
g = c.get(f"/api/cards/{card['id']}").json()
assert g["dismissed"] and g["task_id"] is None and g["revivable"] and g["removed_at"].endswith("+00:00"), g
assert g["revive_spec"] is None, g  # 快照不外发
async def leftovers(db):
    runs = (await db.scalars(select(TaskRun).where(TaskRun.task_id == tid))).all()
    alerts = (await db.scalars(select(HomeCard).where(HomeCard.title == "面板刷新失败"))).all()
    return len(runs), len(alerts)
assert asyncio.run(db_do(leftovers)) == (0, 0)

# —— 工具：list 列出、revive 找回 ——
listing = asyncio.run(call("manage_home", action="list"))
assert "最近移除的面板" in listing and f"id={card['id']} [已移除面板]「上海天气」" in listing, listing
assert "[面板]" not in listing, listing
assert "没找到" in asyncio.run(call("manage_home", action="read", id=card["id"]))  # 移除的不能再 read
assert "不是最近移除的面板" in asyncio.run(call("manage_home", action="revive", id=other["id"]))
assert "要给 id" in asyncio.run(call("manage_home", action="revive"))
out = asyncio.run(call("manage_home", action="revive", id=card["id"]))
assert "已放回 Home" in out and "0 8 * * *" in out, out
back = c.get(f"/api/cards/{card['id']}").json()
assert not back["dismissed"] and back["task_id"] and back["task_id"] != tid and not back["revivable"], back
assert back["removed_at"] is None and back["blocks"][0]["text"] == "晴 21°", back  # 旧内容先留着
t = c.get(f"/api/tasks/{back['task_id']}").json()
assert (t["name"], t["prompt"], t["cron"], t["output"], t["run_requested"]) == ("上海天气", "查上海天气", "0 8 * * *", "panel", True), t
assert (t["runbook"], t["note"], t["reasoning"]) == ("用 wttr.in", "周末多云", "high"), t
assert c.get("/api/cards").json()[0]["id"] == card["id"]  # 顶到最前
assert c.post(f"/api/cards/{card['id']}/revive").status_code == 404  # 已经回来了

# —— 工具 dismiss = 同一条规则；接口 revive ——
assert "30 天内可以用 revive 找回" in asyncio.run(call("manage_home", action="dismiss", id=card["id"]))
r = c.post(f"/api/cards/{card['id']}/revive")
assert r.status_code == 200 and r.json()["title"] == "上海天气" and r.json()["task_id"], r.json()

# —— worker 跑找回后的任务：原地刷新同一张卡 ——
from types import SimpleNamespace
async def fake_turn(db, conv, emit=None, task_id=None, brief=None, **kw):
    return SimpleNamespace(blocks=[{"type": "markdown", "text": "多云 19°"}])
worker.run_turn = fake_turn
asyncio.run(worker.run_task(r.json()["task_id"]))
panels = [x for x in c.get("/api/cards").json() if x["kind"] == "panel" and not x["dismissed"]]
assert len(panels) == 1 and panels[0]["id"] == card["id"] and "多云" in str(panels[0]["blocks"]), panels

# —— 过期：不可找回 + purge ——
assert c.post(f"/api/cards/{card['id']}/remove").status_code == 200
async def age(db):
    (await db.get(HomeCard, card["id"])).removed_at = datetime.now(timezone.utc) - timedelta(days=31)
asyncio.run(db_do(age))
assert c.get(f"/api/cards/{card['id']}").json()["revivable"] is False
r = c.post(f"/api/cards/{card['id']}/revive")
assert r.status_code == 404 and "30 天" in r.json()["detail"], r.json()
assert "最近移除" not in asyncio.run(call("manage_home", action="list"))
asyncio.run(worker.tick())
assert c.get(f"/api/cards/{card['id']}").status_code == 404

# —— 快照 cron 坏了：回落每天 8 点 ——
async def broken(db):
    x = HomeCard(kind="panel", title="旧面板", blocks=[], dismissed=True, removed_at=datetime.now(timezone.utc),
                 revive_spec={"name": "旧面板", "prompt": "看看", "cron": "坏的"})
    db.add(x); await db.flush(); return x.id
bid = asyncio.run(db_do(broken))
r = c.post(f"/api/cards/{bid}/revive")
assert r.status_code == 200, r.text
assert c.get(f"/api/tasks/{r.json()['task_id']}").json()["cron"] == "0 8 * * *"
assert asyncio.run(db_do(lambda db: panel_trash.purge(db))) == 0  # 没过期的不删

# —— 迁移往返 ——
alembic("downgrade", "0050")
alembic("upgrade", "head")
print("smoke_panel_trash OK")
