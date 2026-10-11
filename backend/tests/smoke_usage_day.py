# 冒烟：某一天的按模型拆分（GET /api/usage/days/{date}）。窗口是上海的本地 0 点到次日 0 点：
# UTC 16:00 前后分属两天；多个模型按花费降序；数字与 report() 的 daily 那根柱子完全一致；
# 那天最花钱的对话（只算窗口内、按花费降序、已删 title=null、不归属对话的不进）；没用量的日子全 0；跨月也能查；HTTP 接口：正确日期 200，格式不对 422。
# 运行：python tests/smoke_usage_day.py
import os, sys, asyncio, subprocess, tempfile, json
from datetime import date, datetime, timezone
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="",
  MODEL_PRICES=json.dumps({"fast": [2, 8], "smart": [10, 30]}), TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from app import usage
from app.db import SessionLocal
from app.models import Conversation, UsageRecord

UTC = timezone.utc
U = lambda m, p, c, t, cid=None: UsageRecord(model=m, kind="chat", prompt_tokens=p, completion_tokens=c,
                                             conversation_id=cid, cost=usage.cost_of(m, p, c), created_at=t)

async def main():
    async with SessionLocal() as db:
        empty = await usage.day_report(db, date(2026, 10, 2))
        assert empty["date"] == "2026-10-02" and empty["total"] == {"calls": 0, "tokens": 0, "cost": 0, "models": []}, empty
        assert empty["conversations"] == []
        db.add_all([Conversation(id="a", title="写论文"), Conversation(id="b", title="查资料")])
        assert empty["currency"] and empty["priced"] == ["fast", "smart"]
        db.add_all([
            U("fast", 1_000_000, 0, datetime(2026, 10, 1, 15, 59, tzinfo=UTC), "b"),   # 上海 10-01 23:59 → 1 号
            U("fast", 1_000_000, 0, datetime(2026, 10, 1, 16, 0, tzinfo=UTC), "a"),    # 上海 10-02 00:00 → 2 号：a 2.0
            U("smart", 100_000, 10_000, datetime(2026, 10, 2, 8, 0, tzinfo=UTC), "b"), # 2 号：1.0 + 0.3 = 1.3 → b
            U("fast", 0, 100_000, datetime(2026, 10, 2, 15, 59, tzinfo=UTC), "gone"),  # 2 号 23:59：0.8，对话已删
            U("fast", 5, 0, datetime(2026, 10, 2, 16, 0, tzinfo=UTC), "b"),            # 3 号
            U("smart", 1, 0, datetime(2026, 9, 15, 4, 0, tzinfo=UTC)),            # 上个月
        ])
        await db.commit()
        d2 = await usage.day_report(db, date(2026, 10, 2))
        rep = await usage.report(db, now=datetime(2026, 10, 3, 4, 0, tzinfo=UTC))
        sep = await usage.day_report(db, date(2026, 9, 15))
    t = d2["total"]
    assert t["calls"] == 3 and t["tokens"] == 1_210_000, t
    assert abs(t["cost"] - 4.1) < 1e-9, t                                        # 2.0 + 1.3 + 0.8
    assert [m["model"] for m in t["models"]] == ["fast", "smart"], t["models"]   # 2.8 > 1.3
    assert t["models"][0]["calls"] == 2 and t["models"][1]["completion_tokens"] == 10_000
    convs = d2["conversations"]
    assert [c["id"] for c in convs] == ["a", "b", "gone"], convs                  # 2.0 > 1.3 > 0.8；b 的 1 号、3 号不算
    assert convs[0] == {"id": "a", "title": "写论文", "calls": 1, "tokens": 1_000_000, "cost": 2.0}, convs[0]
    assert convs[1]["calls"] == 1 and abs(convs[1]["cost"] - 1.3) < 1e-9 and convs[2]["title"] is None
    assert sep["conversations"] == []                                            # 上个月那条不归属对话
    assert [c["id"] for c in rep["conversations"]] == ["b", "a", "gone"]         # 报表本月至今不受影响（b 2.0+1.3+…）
    bar = rep["daily"][1]
    assert bar["date"] == "2026-10-02" and (bar["calls"], bar["tokens"]) == (t["calls"], t["tokens"]) and abs(bar["cost"] - t["cost"]) < 1e-9, (bar, t)
    assert sep["total"]["calls"] == 1 and sep["total"]["models"][0]["model"] == "smart"

asyncio.run(main())

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth import require_user
from app.routes import usage as ru
app = FastAPI(); app.include_router(ru.router)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
r = c.get("/api/usage/days/2026-10-02")
assert r.status_code == 200 and r.json()["total"]["calls"] == 3 and r.json()["date"] == "2026-10-02", r.text
assert [c["id"] for c in r.json()["conversations"]] == ["a", "b", "gone"], r.text
assert c.get("/api/usage/days/2026-13-40").status_code == 422
assert c.get("/api/usage/days/today").status_code == 422
assert c.get("/api/usage").status_code == 200
print("usage day smoke OK")
