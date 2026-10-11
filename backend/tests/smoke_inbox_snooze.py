# 冒烟：收件箱报告“稍后再看”（不打模型）。
# 报告推迟 → 不算未读、不是 latest、/api/cards 带 snoozed_until；叫醒 → 重新未读并成为 latest
# （即使有更早来的未读，也即使它本身 created_at 更早）——客户端横幅据此再弹一次；
# 读过别的条目不让旧条目冒成 latest；收起推迟中的报告 → 不再叫醒；manage_home 能推迟报告。
# 运行：python tests/smoke_inbox_snooze.py
import os, sys, asyncio, subprocess, tempfile
from datetime import datetime, timedelta, timezone
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import card_snooze
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.auth import require_user
from app.db import SessionLocal
from app.routes.resources import routers
from app.routes.inbox import router as inbox_router

app = FastAPI()
for r in routers + [inbox_router]:
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
load_builtin()

async def wake(at):
    async with SessionLocal() as db:
        return await card_snooze.wake_due(db, at)

async def tool(**kw):
    async with SessionLocal() as db:
        return (await REGISTRY["manage_home"].run(ToolContext(db=db), **kw)).content

now = datetime.now(timezone.utc)
iso = lambda t: t.isoformat()
mk = lambda **kw: c.post("/api/cards", json={"blocks": [], "kind": "report", **kw}).json()
old = mk(title="周报")
new = mk(title="早报")
inbox = lambda: c.get("/api/inbox").json()
assert inbox()["unread"] == 2 and inbox()["latest"]["id"] == new["id"]

# 推迟最新那条：未读 −1，latest 退回到上一条
r = c.patch(f"/api/cards/{new['id']}", json={"snoozed_until": iso(now + timedelta(hours=1))})
assert r.status_code == 200, r.text
assert r.json()["unread"] is False and r.json()["snoozed_until"]
j = inbox()
assert j["unread"] == 1 and j["latest"]["id"] == old["id"], j

# 读过 old，再推迟到点叫醒 new：new 重新未读并成为 latest
c.post("/api/inbox/read", json={"ids": [old["id"]]})
assert inbox() == {"unread": 0, "latest": None}
assert asyncio.run(wake(now + timedelta(hours=2))) == 1
j = inbox()
assert j["unread"] == 1 and j["latest"]["id"] == new["id"], j

# 叫醒的旧条目压过更早到的未读：third 先到（未读），再叫醒一条 created_at 更早的 old
c.post("/api/inbox/read", json={"ids": [new["id"]]})
third = mk(title="晚报")
c.patch(f"/api/cards/{old['id']}", json={"snoozed_until": iso(now + timedelta(minutes=10))})
assert inbox()["latest"]["id"] == third["id"]
assert asyncio.run(wake(now + timedelta(hours=3))) == 1
j = inbox()
assert j["unread"] == 2 and j["latest"]["id"] == old["id"], j  # old 被重新标未读（叫醒 = 像新来的）

# 读掉 old 不改 updated_at：latest 回到 third
c.post("/api/inbox/read", json={"ids": [old["id"]]})
assert inbox()["latest"]["id"] == third["id"], inbox()

# 收起推迟中的报告 → 推迟清掉，不再叫醒
c.patch(f"/api/cards/{third['id']}", json={"snoozed_until": iso(now + timedelta(minutes=5))})
r = c.patch(f"/api/cards/{third['id']}", json={"dismissed": True}).json()
assert r["dismissed"] is True and r["snoozed_until"] is None
assert asyncio.run(wake(now + timedelta(days=1))) == 0

# 助手也能推迟报告（“这份晚上再看”）
local = (now + timedelta(hours=5)).astimezone(__import__("zoneinfo").ZoneInfo("Asia/Shanghai"))
out = asyncio.run(tool(action="snooze", id=new["id"], until=local.strftime("%Y-%m-%d %H:%M")))
assert "稍后" in out or "收起" in out or "提醒" in out, out
assert c.get(f"/api/cards/{new['id']}").json()["snoozed_until"]
assert inbox()["unread"] == 0
print("ok: inbox snooze")
