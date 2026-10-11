# 冒烟：用量报表的本月逐日序列（daily）。按用户时区（上海）分桶：UTC 16:00 前后落在不同的本地日期；
# 从 1 号到今天每天一项、空天补 0、日期升序；合计与“本月”一致；月初第一天只有一项；
# 时钟晚于 now 的行不画；没有任何用量时也给出整段 0。
# 运行：python tests/smoke_usage_daily.py
import os, sys, asyncio, subprocess, tempfile, json
from datetime import datetime, timezone
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="",
  MODEL_PRICES=json.dumps({"fast": [2, 8]}), MONTHLY_BUDGET="30", TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from app import usage
from app.db import SessionLocal
from app.models import UsageRecord

UTC = timezone.utc
U = lambda p, c, t: UsageRecord(model="fast", kind="chat", prompt_tokens=p, completion_tokens=c,
                                cost=usage.cost_of("fast", p, c), created_at=t)

async def main():
    async with SessionLocal() as db:
        # 空库：上海 10-03 10:00 → 三天全 0
        rep = await usage.report(db, now=datetime(2026, 10, 3, 2, 0, tzinfo=UTC))
        assert [d["date"] for d in rep["daily"]] == ["2026-10-01", "2026-10-02", "2026-10-03"], rep["daily"]
        assert all(d == {"date": d["date"], "calls": 0, "tokens": 0, "cost": 0} for d in rep["daily"]), rep["daily"]

        db.add_all([
            U(1_000_000, 0, datetime(2026, 9, 30, 15, 59, tzinfo=UTC)),       # 上海 9-30 23:59：上个月，不算
            U(1_000_000, 0, datetime(2026, 9, 30, 16, 0, tzinfo=UTC)),        # 上海 10-01 00:00 → 1 号
            U(0, 500_000, datetime(2026, 10, 1, 15, 59, tzinfo=UTC)),         # 上海 10-01 23:59 → 1 号
            U(250_000, 0, datetime(2026, 10, 1, 16, 0, tzinfo=UTC)),          # 上海 10-02 00:00 → 2 号
            U(100, 0, datetime(2026, 10, 3, 1, 0, tzinfo=UTC)),               # 上海 10-03 09:00 → 3 号（今天）
            U(999, 0, datetime(2026, 10, 3, 17, 0, tzinfo=UTC)),              # 上海 10-04：比 now 晚，不画
        ])
        await db.commit()
        rep = await usage.report(db, now=datetime(2026, 10, 3, 2, 0, tzinfo=UTC))
    d = rep["daily"]
    assert [x["date"] for x in d] == ["2026-10-01", "2026-10-02", "2026-10-03"], d
    assert d[0] == {"date": "2026-10-01", "calls": 2, "tokens": 1_500_000, "cost": 6.0}, d[0]
    assert d[1] == {"date": "2026-10-02", "calls": 1, "tokens": 250_000, "cost": 0.5}, d[1]
    assert d[2]["calls"] == 1 and d[2]["tokens"] == 100, d[2]
    assert rep["today"]["tokens"] == d[2]["tokens"] + 999   # “今天”是 >= 起点的全部（含晚于 now 的那行），daily 只画到今天

    async with SessionLocal() as db:                 # 月初第一天：只有一项
        rep = await usage.report(db, now=datetime(2026, 9, 30, 17, 0, tzinfo=UTC))
    assert [x["date"] for x in rep["daily"]] == ["2026-10-01"] and rep["daily"][0]["calls"] == 2, rep["daily"]

    async with SessionLocal() as db:                 # 月中：合计 = 本月
        rep = await usage.report(db, now=datetime(2026, 10, 20, 4, 0, tzinfo=UTC))
    d = rep["daily"]
    assert len(d) == 20 and d[-1]["date"] == "2026-10-20"
    assert sum(x["calls"] for x in d) == rep["month"]["calls"] and abs(sum(x["cost"] for x in d) - rep["month"]["cost"]) < 1e-9
    assert sum(x["tokens"] for x in d) == rep["month"]["tokens"], (d, rep["month"])

asyncio.run(main())
print("usage daily smoke OK")
