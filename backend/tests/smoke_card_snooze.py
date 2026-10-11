# 冒烟：Home 卡片“稍后提醒”（不打模型）。
# 接口 PATCH snoozed_until：推迟清未读、wire 带时区、过去/超 30 天/面板 → 422、null 放回；忽略推迟中的卡清掉推迟；
# 收件箱未读不算推迟中的卡；worker 的 wake_due 只叫醒到点且未忽略的（重新未读 + 顶到最前）；
# 工具 manage_home：snooze（格式错/过去拒绝）、list 显示“稍后提醒于”、unsnooze。
# 运行：python tests/smoke_card_snooze.py
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
from app.models import HomeCard
from app.routes.resources import routers
from app.routes.inbox import router as inbox_router

app = FastAPI()
for r in routers + [inbox_router]:
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
load_builtin()

async def call(name, **kw):
    async with SessionLocal() as db:
        return (await REGISTRY[name].run(ToolContext(db=db), **kw)).content

now = datetime.now(timezone.utc)
iso = lambda t: t.isoformat()
mk = lambda **kw: c.post("/api/cards", json={"blocks": [], **kw}).json()
a = mk(kind="action", title="回复老师邮件")
b = mk(kind="action", title="交水费")
rep = mk(kind="report", title="早报")
panel = mk(kind="panel", title="天气", unread=False)
assert a["snoozed_until"] is None and a["unread"] is True
assert c.get("/api/inbox").json()["unread"] == 3

# —— 推迟 ——
r = c.patch(f"/api/cards/{a['id']}", json={"snoozed_until": iso(now + timedelta(hours=1))})
assert r.status_code == 200, r.text
j = r.json()
assert j["unread"] is False and j["snoozed_until"], j
assert datetime.fromisoformat(j["snoozed_until"]).tzinfo is not None  # 带时区，客户端不会误当本地时间
assert c.get("/api/inbox").json()["unread"] == 2  # 推迟中的不算未读
# 不合法的
for body, card in [({"snoozed_until": iso(now - timedelta(minutes=1))}, b),
                   ({"snoozed_until": iso(now + timedelta(days=31))}, b),
                   ({"snoozed_until": iso(now + timedelta(hours=1))}, panel)]:
    r = c.patch(f"/api/cards/{card['id']}", json=body)
    assert r.status_code == 422, (body, r.text)
assert c.get(f"/api/cards/{b['id']}").json()["snoozed_until"] is None
# null = 现在放回（不改未读）
c.patch(f"/api/cards/{b['id']}", json={"snoozed_until": iso(now + timedelta(days=2))})
r = c.patch(f"/api/cards/{b['id']}", json={"snoozed_until": None}).json()
assert r["snoozed_until"] is None and r["unread"] is False
# 忽略推迟中的卡 → 推迟一并清掉
c.patch(f"/api/cards/{b['id']}", json={"snoozed_until": iso(now + timedelta(minutes=5))})
r = c.patch(f"/api/cards/{b['id']}", json={"dismissed": True}).json()
assert r["dismissed"] is True and r["snoozed_until"] is None

# —— worker 叫醒 ——
async def wake(at):
    async with SessionLocal() as db:
        return await card_snooze.wake_due(db, at)
assert asyncio.run(wake(now + timedelta(minutes=30))) == 0  # 还没到点
assert c.get(f"/api/cards/{a['id']}").json()["snoozed_until"]
assert asyncio.run(wake(now + timedelta(hours=2))) == 1
j = c.get(f"/api/cards/{a['id']}").json()
assert j["snoozed_until"] is None and j["unread"] is True, j
assert c.get("/api/cards").json()[0]["id"] == a["id"]  # 顶到最前
assert c.get("/api/inbox").json()["unread"] == 2  # a 回来了，b 已忽略
# 被别处直接忽略（如预算提醒替换旧卡）但没清推迟的卡：不叫醒
async def stale():
    async with SessionLocal() as db:
        db.add(HomeCard(kind="action", title="旧提醒", blocks=[], dismissed=True,
                        snoozed_until=now + timedelta(minutes=1)))
        await db.commit()
asyncio.run(stale())
assert asyncio.run(wake(now + timedelta(hours=3))) == 0

# —— 工具 ——
assert "格式" in asyncio.run(call("manage_home", action="snooze", id=rep["id"], until="明天"))
assert "将来" in asyncio.run(call("manage_home", action="snooze", id=rep["id"], until="2020-01-01 08:00"))
assert "不能稍后提醒" in asyncio.run(call("manage_home", action="snooze", id=panel["id"], until="2099-01-01 08:00"))
tomorrow = (datetime.now(timezone(timedelta(hours=8))) + timedelta(days=1)).strftime("%Y-%m-%d 09:00")
out = asyncio.run(call("manage_home", action="snooze", id=rep["id"], until=tomorrow))
assert "收起来" in out, out
j = c.get(f"/api/cards/{rep['id']}").json()
assert j["unread"] is False and datetime.fromisoformat(j["snoozed_until"]).astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M") == tomorrow, j
listing = asyncio.run(call("manage_home", action="list"))
assert f"「早报」 · 稍后提醒于 {tomorrow[5:]}" in listing, listing
assert "放回" in asyncio.run(call("manage_home", action="unsnooze", id=rep["id"]))
assert "本来就在" in asyncio.run(call("manage_home", action="unsnooze", id=rep["id"]))
assert c.get(f"/api/cards/{rep['id']}").json()["snoozed_until"] is None
print("ok")
