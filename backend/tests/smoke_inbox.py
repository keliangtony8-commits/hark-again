# 冒烟：迁移 0009 旧卡算已读；worker 用模拟模型跑报告任务 → 未读 +1；
# 收件箱摘要、打开对话即已读（不改 updated_at）、全部已读、面板刷新不算未读、忽略的卡不计数。
# 运行：python tests/smoke_inbox.py
import os, sys, asyncio, subprocess, tempfile
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
alembic = lambda rev: subprocess.run([sys.executable, "-m", "alembic", "upgrade", rev], cwd=root, check=True,
                                    capture_output=True)

alembic("0008")
import sqlite3
con = sqlite3.connect(db_path)
con.execute("insert into home_cards (id,kind,title,blocks,dismissed,created_at,updated_at) values "
            "('old','report','旧报告','[]',0,'2026-01-01 00:00:00','2026-01-01 00:00:00')")
con.commit(); con.close()
alembic("head")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import worker
from app.auth import require_user
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import HomeCard, ScheduledTask
from app.routes import conversations as rc, inbox as ri
from app.routes.resources import routers

class FakeReply:
    blocks = text_to_blocks("今天的新闻摘要：一切平安。")

async def fake_run_turn(db, conv, **kw):  # 模拟模型：不打真接口
    return FakeReply()
worker.run_turn = fake_run_turn

app = FastAPI()
for r in [rc.router, ri.router, *routers]:
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)

assert c.get("/api/inbox").json() == {"unread": 0, "latest": None}, "旧卡应算已读"

async def seed():
    async with SessionLocal() as db:
        rep = ScheduledTask(name="每日新闻", prompt="总结新闻", cron="0 8 * * *", output="report")
        pan = ScheduledTask(name="天气面板", prompt="天气", cron="0 * * * *", output="panel")
        db.add_all([rep, pan]); await db.commit()
        return rep.id, pan.id
rep, pan = asyncio.run(seed())
asyncio.run(worker.run_task(rep))
asyncio.run(worker.run_task(pan))

s = c.get("/api/inbox").json()
assert s["unread"] == 1 and s["latest"]["title"] == "每日新闻" and s["latest"]["kind"] == "report", s
cards = {x["kind"]: x for x in c.get("/api/cards").json() if x["task_id"]}
assert cards["panel"]["unread"] is False and cards["report"]["unread"] is True, cards

# 打开报告对话 = 读过；updated_at 不变
before = cards["report"]["updated_at"]
c.get(f"/api/conversations/{s['latest']['conversation_id']}")
assert c.get("/api/inbox").json()["unread"] == 0
after = next(x for x in c.get("/api/cards").json() if x["id"] == cards["report"]["id"])
assert after["unread"] is False and after["updated_at"] == before, after

# 主动建议卡经接口新建默认未读；忽略后不计数；全部已读
a = c.post("/api/cards", json={"kind": "action", "title": "回复老师的邮件"}).json()
b = c.post("/api/cards", json={"kind": "action", "title": "交水费"}).json()
assert c.get("/api/inbox").json()["unread"] == 2
c.patch(f"/api/cards/{a['id']}", json={"dismissed": True})
s = c.get("/api/inbox").json()
assert s["unread"] == 1 and s["latest"]["id"] == b["id"], s
assert c.post("/api/inbox/read", json={"ids": ["nope"]}).json()["unread"] == 1
assert c.post("/api/inbox/read", json={}).json() == {"unread": 0, "latest": None}

# 再跑一次报告：旧报告卡被替换，新的又未读
asyncio.run(worker.run_task(rep))
assert c.get("/api/inbox").json()["unread"] == 1
print("inbox smoke OK")
