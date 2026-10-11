# 冒烟：用量报表的上月对比（last_month）。全月合计 + 同期 to_date（上月 1 号到上月同一天同一时刻，上海时区）；
# 边界：上月同一刻之前算、之后不算；上月没有这一天（3-31 对 2 月）→ 同期 = 全月；跨年（1 月对去年 12 月）；
# 本月和更早的月份都不混进来；空库全 0。
# 运行：python tests/smoke_usage_compare.py
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
from app.models import UsageRecord

UTC = timezone.utc
U = lambda p, t: UsageRecord(model="fast", kind="chat", prompt_tokens=p, completion_tokens=0,
                             cost=usage.cost_of("fast", p, 0), created_at=t)
Z = {"calls": 0, "tokens": 0, "cost": 0}

async def rep(now):
    async with SessionLocal() as db:
        return (await usage.report(db, now=now))["last_month"]

async def main():
    lm = await rep(datetime(2026, 10, 11, 0, 0, tzinfo=UTC))
    assert lm == {**Z, "to_date": Z}, lm

    async with SessionLocal() as db:
        db.add_all([
            U(1_000_000, datetime(2026, 8, 31, 15, 59, tzinfo=UTC)),   # 上海 8-31 23:59：上上个月，不算
            U(1_000_000, datetime(2026, 8, 31, 16, 0, tzinfo=UTC)),    # 上海 9-01 00:00：上月第一刻，同期
            U(500_000, datetime(2026, 9, 10, 23, 29, tzinfo=UTC)),     # 上海 9-11 07:29：同期（早于 07:30）
            U(250_000, datetime(2026, 9, 10, 23, 30, tzinfo=UTC)),     # 上海 9-11 07:30：恰好到点，不进同期
            U(100_000, datetime(2026, 9, 30, 15, 59, tzinfo=UTC)),     # 上海 9-30 23:59：上月最后一刻
            U(7_000_000, datetime(2026, 9, 30, 16, 0, tzinfo=UTC)),    # 上海 10-01：本月，不算
        ])
        await db.commit()

    lm = await rep(datetime(2026, 10, 10, 23, 30, tzinfo=UTC))       # 上海 10-11 07:30
    assert lm["calls"] == 4 and lm["tokens"] == 1_850_000 and lm["cost"] == 3.7, lm
    assert lm["to_date"] == {"calls": 2, "tokens": 1_500_000, "cost": 3.0}, lm

    lm = await rep(datetime(2026, 10, 31, 4, 0, tzinfo=UTC))         # 10-31：9 月没有 31 号 → 同期 = 全月
    assert lm["to_date"] == {k: lm[k] for k in ("calls", "tokens", "cost")}, lm

    lm = await rep(datetime(2026, 9, 30, 16, 30, tzinfo=UTC))        # 上海 10-01 00:30：同期只有 9-01 00:00 那一笔
    assert lm["to_date"]["calls"] == 1 and lm["calls"] == 4, lm

    lm = await rep(datetime(2026, 11, 5, 4, 0, tzinfo=UTC))          # 11 月对 10 月
    assert lm["calls"] == 1 and lm["tokens"] == 7_000_000 and lm["to_date"]["calls"] == 1, lm

    async with SessionLocal() as db:                                 # 跨年：2027-01 对 2026-12
        db.add(U(300_000, datetime(2026, 12, 14, 16, 0, tzinfo=UTC)))  # 上海 12-15 00:00
        await db.commit()
    lm = await rep(datetime(2027, 1, 20, 4, 0, tzinfo=UTC))
    assert lm["calls"] == 1 and lm["to_date"]["calls"] == 1 and lm["cost"] == 0.6, lm
    lm = await rep(datetime(2027, 1, 10, 4, 0, tzinfo=UTC))
    assert lm["calls"] == 1 and lm["to_date"] == Z, lm

    async with SessionLocal() as db:                                 # 报表其它字段不受影响
        full = await usage.report(db, now=datetime(2026, 10, 10, 23, 30, tzinfo=UTC))
    assert {"today", "month", "daily", "conversations", "last_month"} <= set(full)

asyncio.run(main())
print("usage compare smoke OK")
