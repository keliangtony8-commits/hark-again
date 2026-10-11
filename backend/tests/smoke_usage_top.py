# 冒烟：用量报表的本月最花钱对话（conversations）。按花费降序、同价按 token；只算本月；
# 不归属对话的调用不进表；对话删了 title=null 但仍在；最多 TOP_CONVERSATIONS 个；HTTP 接口带上该字段。
# 运行：python tests/smoke_usage_top.py
import os, sys, asyncio, subprocess, tempfile, json
from datetime import datetime, timezone
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="",
  MODEL_PRICES=json.dumps({"fast": [2, 8]}), TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from app import usage
from app.db import SessionLocal
from app.models import Conversation, UsageRecord

UTC = timezone.utc
NOW = datetime(2026, 10, 10, 4, 0, tzinfo=UTC)
IN, OLD = datetime(2026, 10, 5, tzinfo=UTC), datetime(2026, 9, 20, tzinfo=UTC)
U = lambda cid, p, c, t=IN: UsageRecord(model="fast", kind="chat", conversation_id=cid, prompt_tokens=p,
                                        completion_tokens=c, cost=usage.cost_of("fast", p, c), created_at=t)

async def main():
    async with SessionLocal() as db:
        assert (await usage.report(db, now=NOW))["conversations"] == []
        db.add_all([Conversation(id="a", title="写论文"), Conversation(id="b", title="查资料"),
                    Conversation(id="c", title="闲聊")] + [Conversation(id=f"x{i}", title=f"小{i}") for i in range(5)])
        db.add_all([
            U("a", 1_000_000, 0), U("a", 0, 100_000),          # 2.8
            U("b", 0, 1_000_000),                               # 8.0
            U("c", 100, 0), U("c", 100_000_000, 0, OLD),        # 本月只有 100 token，上个月的不算
            U("gone", 500_000, 0),                              # 1.0，对话已删
            U(None, 9_000_000, 0),                              # 不归属对话
        ] + [U(f"x{i}", 10 * (i + 1), 0) for i in range(5)])
        await db.commit()
        rep = await usage.report(db, now=NOW)
    top = rep["conversations"]
    assert len(top) == usage.TOP_CONVERSATIONS, top
    assert [t["id"] for t in top] == ["b", "a", "gone", "c", "x4"], top     # c(100 tok) 比 x4(50 tok) 多
    assert top[0] == {"id": "b", "title": "查资料", "calls": 1, "tokens": 1_000_000, "cost": 8.0}, top[0]
    assert top[1]["calls"] == 2 and top[1]["tokens"] == 1_100_000 and abs(top[1]["cost"] - 2.8) < 1e-9
    assert top[2]["title"] is None and top[2]["cost"] == 1.0
    assert top[3]["tokens"] == 100

asyncio.run(main())

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth import require_user
from app.routes import usage as ru
app = FastAPI(); app.include_router(ru.router)
app.dependency_overrides[require_user] = lambda: "u"
r = TestClient(app).get("/api/usage")
assert r.status_code == 200 and r.json()["conversations"][0]["id"] == "b", r.text
print("usage top conversations smoke OK")
