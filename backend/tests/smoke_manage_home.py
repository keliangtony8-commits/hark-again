# 冒烟：Home 管理（模拟模型，不打真接口）。
# create_panel 走 task_store（坏 cron 拒绝）；接口 PATCH 面板任务改名 → 卡片标题跟着改（crud after_update 钩子）；
# 工具 manage_home：list 分组带 id 与 cron、只列未隐藏；refresh 置 run_requested；update 改名/cron（卡片同步、坏 cron 拒绝、
# 非面板拒绝）；dismiss 建议 = 隐藏并清未读，dismiss 面板 = 连任务带卡删除；未知 id 提示先 list。
# 运行：python tests/smoke_manage_home.py
import os, sys, asyncio, subprocess, tempfile
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.auth import require_user
from app.db import SessionLocal
from app.models import HomeCard
from app.routes.resources import routers

app = FastAPI()
for r in routers:
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
load_builtin()

async def call(name, **kw):
    async with SessionLocal() as db:
        return (await REGISTRY[name].run(ToolContext(db=db), **kw)).content

# —— create_panel ——
assert "无效" in asyncio.run(call("create_panel", title="坏", prompt="x", cron="每天"))
assert "已放到 Home" in asyncio.run(call("create_panel", title="天气", prompt="查上海天气", cron="0 8 * * *"))
assert "已放到 Home" in asyncio.run(call("create_panel", title="比分", prompt="查比分", cron="0 * * * *"))
panel = lambda title: next(x for x in c.get("/api/cards").json() if x["kind"] == "panel" and x["title"] == title)
weather = panel("天气")
task = c.get(f"/api/tasks/{weather['task_id']}").json()
assert task["output"] == "panel" and task["run_requested"] is True, task

# —— 接口改名 → 卡片跟着改 ——
r = c.patch(f"/api/tasks/{task['id']}", json={"name": "上海天气"})
assert r.status_code == 200 and r.json()["name"] == "上海天气"
assert c.get(f"/api/cards/{weather['id']}").json()["title"] == "上海天气"
assert c.patch(f"/api/tasks/{task['id']}", json={"cron": "坏"}).status_code == 422
assert c.get(f"/api/cards/{weather['id']}").json()["title"] == "上海天气"

# —— 一张建议、一条收件箱、一张隐藏的卡 ——
async def seed():
    async with SessionLocal() as db:
        db.add_all([HomeCard(kind="action", title="回复老师邮件", blocks=[], unread=True),
                    HomeCard(kind="report", title="早报", blocks=[], unread=True),
                    HomeCard(kind="action", title="旧建议", blocks=[], dismissed=True)])
        await db.commit()
asyncio.run(seed())

listing = asyncio.run(call("manage_home", action="list"))
assert "[面板]「上海天气」" in listing and "cron 0 8 * * *" in listing, listing
assert "[建议]「回复老师邮件」" in listing and "[收件箱]「早报」 · 未读" in listing, listing
assert "旧建议" not in listing and listing.count("id=") == 4, listing
assert listing.index("[建议]") < listing.index("[面板]") < listing.index("[收件箱]"), listing

# —— refresh / update ——
score = panel("比分")
async def clear_flag(tid):
    from app.models import ScheduledTask
    async with SessionLocal() as db:
        (await db.get(ScheduledTask, tid)).run_requested = False; await db.commit()
asyncio.run(clear_flag(score["task_id"]))
assert "开始刷新" in asyncio.run(call("manage_home", action="refresh", id=score["id"]))
assert c.get(f"/api/tasks/{score['task_id']}").json()["run_requested"] is True
out = asyncio.run(call("manage_home", action="update", id=score["id"], title="湖人比分", cron="0 12 * * *"))
assert "湖人比分" in out and "0 12 * * *" in out, out
assert c.get(f"/api/cards/{score['id']}").json()["title"] == "湖人比分"
assert c.get(f"/api/tasks/{score['task_id']}").json()["cron"] == "0 12 * * *"
assert "无效" in asyncio.run(call("manage_home", action="update", id=score["id"], cron="每天"))
assert c.get(f"/api/tasks/{score['task_id']}").json()["cron"] == "0 12 * * *"
assert "至少" in asyncio.run(call("manage_home", action="update", id=score["id"]))
action = next(x for x in c.get("/api/cards").json() if x["title"] == "回复老师邮件")
assert "不是面板" in asyncio.run(call("manage_home", action="refresh", id=action["id"]))
assert "没找到" in asyncio.run(call("manage_home", action="dismiss", id="nope"))

# —— dismiss ——
assert "已从 Home 拿掉" in asyncio.run(call("manage_home", action="dismiss", id=action["id"]))
a = c.get(f"/api/cards/{action['id']}").json()
assert a["dismissed"] is True and a["unread"] is False, a
assert "没找到" in asyncio.run(call("manage_home", action="dismiss", id=action["id"]))  # 已隐藏的不再可操作
assert "已删除面板" in asyncio.run(call("manage_home", action="dismiss", id=score["id"]))
assert c.get(f"/api/tasks/{score['task_id']}").status_code == 404
assert c.get(f"/api/cards/{score['id']}").status_code == 404

print("smoke_manage_home OK")
