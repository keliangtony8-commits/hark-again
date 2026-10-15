# 冒烟：项目接口带只读的 conversation_id 和 last_active_at（v2.95 项目 = 一段对话）。
# 新项目 → 带着刚建的那段对话、活动时间 = 项目与对话中较晚的；那段对话更新得更晚 → 活动时间 = 它；
# 运行对话 / 别的项目 / 主聊天的对话不算；单条 GET / PATCH 同样带上；客户端写不进来。
# 运行：python tests/smoke_project_activity.py
import os, sys, asyncio, subprocess, tempfile
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from datetime import datetime, timedelta, timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth import require_user
from app.db import SessionLocal
from app.models import Conversation
from sqlalchemy import update
from app.routes.resources import routers

app = FastAPI()
for r in routers:
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
def parse(s): return datetime.fromisoformat(s).astimezone(timezone.utc)

a = c.post("/api/projects", json={"name": "考研"}).json()
b = c.post("/api/projects", json={"name": "旅行"}).json()
assert a["conversation_id"] and a["conversation_id"] != b["conversation_id"], a
assert abs((parse(a["last_active_at"]) - parse(a["updated_at"])).total_seconds()) < 1, a

later = datetime.now(timezone.utc) + timedelta(hours=2)
much_later = later + timedelta(hours=5)
async def seed():
    async with SessionLocal() as db:
        await db.execute(update(Conversation).where(Conversation.id == a["conversation_id"]).values(updated_at=later))
        db.add_all([
            Conversation(project_id=a["id"], title="脚本", task_id="t1", updated_at=much_later),  # 运行对话不算
            Conversation(project_id=None, title="main", updated_at=much_later),
        ])
        await db.commit()
asyncio.run(seed())

rows = {p["id"]: p for p in c.get("/api/projects").json()}
assert rows[a["id"]]["conversation_id"] == a["conversation_id"] and "conversation_count" not in rows[a["id"]], rows
assert abs((parse(rows[a["id"]]["last_active_at"]) - later).total_seconds()) < 1, rows[a["id"]]
one = c.get(f"/api/projects/{a['id']}").json()
assert one["conversation_id"] == a["conversation_id"] and one["last_active_at"] == rows[a["id"]]["last_active_at"]
patched = c.patch(f"/api/projects/{a['id']}", json={"rules": "用英文", "conversation_id": "x"}).json()
assert patched["conversation_id"] == a["conversation_id"] and patched["rules"] == "用英文", patched
# 任务接口的 extra（next_run_at）不受影响
t = c.post("/api/tasks", json={"name": "早报", "prompt": "x", "cron": "0 8 * * *"}).json()
assert t["next_run_at"], t
print("ok smoke_project_activity")
