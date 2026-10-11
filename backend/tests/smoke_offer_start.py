# 冒烟：v0.89 点建议卡 → 新对话并链回卡上（POST /api/cards/{id}/start，app/home_offers.start）。无模型调用，无迁移。
# - 第一次点：开新对话（标题 = 卡标题）、卡记下 conversation_id、清未读，started=True、带回指令；Home 顺序不跳；
# - 再点：回到同一段对话，started=False（客户端不重发）；
# - 那段对话被删 → 再点重新开一段；
# - 同标题重新提议 → 清掉对话链接（新的一件事）；
# - 系统提醒 / 已收起 / 不存在 → 404；manage_home list 标出“用户已点按钮开始做”；打开对话 = 卡已读（已有规则）。
# 运行：python tests/smoke_offer_start.py
import os, sys, asyncio, subprocess, tempfile
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import home_offers
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.auth import require_user
from app.db import SessionLocal
from app.models import HomeCard
from app.routes import conversations, home
from app.routes.resources import routers

load_builtin()
app = FastAPI()
for r in [*routers, home.router, conversations.router]:
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)

async def offer(title, prompt="打开 net.school.edu 续费一个月"):
    async with SessionLocal() as db:
        card, _, _ = await home_offers.offer(db, title, "周五到期", prompt, "帮我续费")
        return card.id

async def alert():
    async with SessionLocal() as db:
        x = HomeCard(kind="action", title="本月花费已到 80%", blocks=[], target="usage", action_prompt="看看用量", unread=True)
        db.add(x); await db.commit(); return x.id

card = lambda cid: next(x for x in c.get("/api/cards").json() if x["id"] == cid)

a = asyncio.run(offer("续费校园网"))
b = asyncio.run(offer("整理照片", "把相册里重复的照片挑出来"))
order = [x["id"] for x in c.get("/api/cards").json()]
before = card(a)

# 1) 第一次点
r = c.post(f"/api/cards/{a}/start")
assert r.status_code == 200, r.text
j = r.json()
assert j["started"] is True and j["prompt"] == "打开 net.school.edu 续费一个月" and j["conversation_id"], j
conv = c.get(f"/api/conversations/{j['conversation_id']}").json()
assert conv["title"] == "续费校园网", conv
after = card(a)
assert after["conversation_id"] == j["conversation_id"] and after["unread"] is False and after["dismissed"] is False, after
assert after["updated_at"] == before["updated_at"], (before, after)
assert [x["id"] for x in c.get("/api/cards").json()] == order

# 2) 再点 → 同一段，不重发
j2 = c.post(f"/api/cards/{a}/start").json()
assert j2["started"] is False and j2["conversation_id"] == j["conversation_id"], j2

# 3) 对话删了 → 重开
assert c.delete(f"/api/conversations/{j['conversation_id']}").status_code in (200, 204)
j3 = c.post(f"/api/cards/{a}/start").json()
assert j3["started"] is True and j3["conversation_id"] != j["conversation_id"], j3

# 4) manage_home list
async def listing():
    async with SessionLocal() as db:
        return (await REGISTRY["manage_home"].run(ToolContext(db=db), action="list")).content
out = asyncio.run(listing())
assert "「续费校园网」 · 你提议的 · 按钮“帮我续费” · 用户已点按钮开始做" in out, out
assert "「整理照片」 · 你提议的 · 按钮“帮我续费” · 未读\n" in out + "\n" and "整理照片」 · 你提议的 · 按钮“帮我续费” · 未读 · 用户" not in out, out

# 5) 同标题重新提议 → 链接清掉
asyncio.run(offer("续费校园网"))
assert card(a)["conversation_id"] is None and card(a)["unread"] is True

# 6) 不该点的
s = asyncio.run(alert())
assert c.post(f"/api/cards/{s}/start").status_code == 404
assert c.post("/api/cards/nope/start").status_code == 404
assert c.patch(f"/api/cards/{b}", json={"dismissed": True}).status_code == 200
assert c.post(f"/api/cards/{b}/start").status_code == 404
print("ok")
