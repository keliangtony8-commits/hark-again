# 冒烟：迁移 0008 回填搜索文本；对话搜索（中文、内容摘录 + 命中消息 id、通配符转义）、重命名、置顶排序不改 updated_at。
# 运行：python tests/smoke_conversations.py
import os, sys, asyncio, json, subprocess, tempfile
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
alembic = lambda rev: subprocess.run([sys.executable, "-m", "alembic", "upgrade", rev], cwd=root, check=True,
                                    capture_output=True)

# 1) 旧库里已有消息 → 升级后能搜到
alembic("0007")
import sqlite3
con = sqlite3.connect(db_path)
con.execute("insert into conversations (id,title,project_id,created_at,updated_at) values "
            "('old','旧对话',null,'2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')")
con.execute("insert into messages (id,conversation_id,role,blocks,created_at) values (?,?,?,?,?)",
            ("m0", "old", "user", json.dumps([{"type": "text", "text": "旧的猫咪话题"}]), "2026-01-01T00:00:00+00:00"))
con.commit(); con.close()
alembic("head")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routes import conversations as rc
from app.auth import require_user
from app.db import SessionLocal
from app.models import Conversation, Message
from app.blocks import text_to_blocks

app = FastAPI(); app.include_router(rc.router)
app.dependency_overrides[require_user] = lambda: "u"

async def seed():
    async with SessionLocal() as db:
        a = Conversation(title="周末计划"); b = Conversation(title="英语作业")
        db.add_all([a, b]); await db.flush()
        db.add(Message(conversation_id=a.id, role="user", blocks=text_to_blocks("去爬山")))
        db.add(Message(conversation_id=b.id, role="assistant",
                       blocks=text_to_blocks("这是一段很长的解释。" * 10 + "关键词100%_ok 在这里" + "结尾。" * 20)))
        await db.commit()
        return a.id, b.id
a, b = asyncio.run(seed())
c = TestClient(app)

ids = lambda r: [x["id"] for x in r.json()]
assert ids(c.get("/api/conversations", params={"q": "猫咪"})) == ["old"], "迁移回填失败"
r = c.get("/api/conversations", params={"q": "周末"}).json()
assert [x["id"] for x in r] == [a] and "snippet" not in r[0] and "message_id" not in r[0]  # 标题命中不带摘录/定位
r = c.get("/api/conversations", params={"q": "100%_ok"}).json()
assert [x["id"] for x in r] == [b] and "100%_ok" in r[0]["snippet"] and r[0]["snippet"].startswith("…"), r
assert ids(c.get("/api/conversations", params={"q": "100%"})) == [b]
# 命中定位：message_id 指向最近一条命中的消息，且确实在 GET /{id} 的消息里
async def add_later():
    async with SessionLocal() as db:
        m = Message(conversation_id=b, role="user", blocks=text_to_blocks("再问一次 100%_ok 是什么"))
        db.add(m); await db.commit(); return m.id
newer = asyncio.run(add_later())
r = c.get("/api/conversations", params={"q": "100%_ok"}).json()
assert r[0]["message_id"] == newer and r[0]["snippet"].startswith("再问一次"), r
assert newer in [m["id"] for m in c.get(f"/api/conversations/{b}").json()["messages"]]
assert ids(c.get("/api/conversations", params={"q": "周%划"})) == []    # % 是字面量，不是通配
assert ids(c.get("/api/conversations", params={"q": "不存在"})) == []

before = {x["id"]: x["updated_at"] for x in c.get("/api/conversations").json()}
r = c.patch(f"/api/conversations/{a}", json={"title": "  爬山计划 ", "pinned": True}).json()
assert r["title"] == "爬山计划" and r["pinned"] is True and r["updated_at"] == before[a], r
lst = c.get("/api/conversations").json()
assert lst[0]["id"] == a and lst[0]["pinned"], lst                      # 置顶在最前
assert c.patch(f"/api/conversations/{a}", json={"title": "   "}).status_code == 422
assert c.patch("/api/conversations/nope", json={"pinned": True}).status_code == 404
assert c.get(f"/api/conversations/{a}").json()["pinned"] is True
print("conversations smoke OK")
