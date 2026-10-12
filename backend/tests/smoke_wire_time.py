# 冒烟：接口里的时间一律带时区（SQLite 读回来无时区，按 UTC 补上），不打模型。
# 以前对话列表 updated_at、CRUD 资源（卡片/任务/项目/记忆）、收件箱 latest、密钥 created_at 直接 isoformat()
# → 无偏移字符串 → 浏览器/Dart 当本地时间解析，东八区错 8 小时（日期分隔、“今天 08:00”、formatAgo 全偏）。
# 运行：python tests/smoke_wire_time.py
import os, sys, asyncio, subprocess, tempfile
from datetime import date, datetime, timezone
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth import require_user
from app.db import SessionLocal
from app.models import Conversation, Message
from app.routes.resources import routers
from app.routes.inbox import router as inbox_router
from app.routes.conversations import router as conv_router
from app.wire_time import iso, wire

# 纯规则
naive = datetime(2026, 10, 11, 14, 0)
assert iso(naive) == "2026-10-11T14:00:00+00:00"
assert iso(datetime(2026, 10, 11, 22, 0, tzinfo=timezone.utc)) == "2026-10-11T22:00:00+00:00"
assert iso(None) is None
assert wire(date(2026, 10, 11)) == "2026-10-11" and wire(3) == 3 and wire("x") == "x"

app = FastAPI()
for r in routers + [inbox_router, conv_router]:
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)

def aware(s):
    assert isinstance(s, str), s
    t = datetime.fromisoformat(s)
    assert t.tzinfo is not None, f"无时区：{s}"
    return t

async def seed():
    async with SessionLocal() as db:
        conv = Conversation(title="t")
        db.add(conv)
        await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=[{"type": "text", "text": "hi"}]))
        await db.commit()
        return conv.id
cid = asyncio.run(seed())

# 对话列表 + 详情消息
lst = c.get("/api/conversations").json()
rows = lst if isinstance(lst, list) else lst.get("items", lst.get("conversations"))
row = next(r for r in rows if r["id"] == cid)
t = aware(row["updated_at"])
assert abs((datetime.now(timezone.utc) - t).total_seconds()) < 120, t  # 真是 UTC，不是差 8 小时
det = c.get(f"/api/conversations/{cid}").json()
aware(det["messages"][0]["created_at"])

# CRUD：卡片（含收件箱 latest）、任务（含算出来的 next_run_at）、项目、记忆
card = c.post("/api/cards", json={"blocks": [], "kind": "report", "title": "早报"}).json()
aware(card["created_at"]); aware(card["updated_at"])
aware(c.get("/api/inbox").json()["latest"]["created_at"])
task = c.post("/api/tasks", json={"name": "n", "prompt": "p", "cron": "0 7 * * *"}).json()
aware(task["created_at"]); aware(task["next_run_at"])
proj = c.post("/api/projects", json={"name": "考研"}).json()
aware(proj["created_at"])
mem = c.post("/api/memories", json={"content": "生日 10月14日"})
if mem.status_code == 200:
    aware(mem.json()["created_at"])
print("smoke_wire_time OK")
