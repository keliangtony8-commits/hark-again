# 冒烟：预算提醒。预算 10、档位 80%/100%：
# 没到 80% 不发；跨 80% 发一张 action 卡（target=usage、未读、带预测）；再记账不重复；
# 用户删了卡也不重发（去重在 alerts_sent）；跨 100% 发新卡并收起旧卡；下个月重新计；
# 改了预算 = 新一组档位；预算 0 不检查；并发两笔同时跨档只有一张；/api/cards 带 target、不带去重表；
# record() 走完整路径（记账后自动检查）。
# 运行：python tests/smoke_budget.py
import os, sys, asyncio, subprocess, tempfile, json
from datetime import datetime, timezone
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="",
  MODEL_PRICES=json.dumps({"fast": [1_000_000, 0]}), MONTHLY_BUDGET="10", TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from app import usage
from app.config import settings
from app.db import SessionLocal
from app.models import AlertSent, HomeCard, UsageRecord
from sqlalchemy import delete, select

OCT = datetime(2026, 10, 15, 4, 0, tzinfo=timezone.utc)
NOV = datetime(2026, 11, 2, 4, 0, tzinfo=timezone.utc)

async def spend(amount, at=OCT):
    async with SessionLocal() as db:
        db.add(UsageRecord(model="fast", kind="chat", prompt_tokens=0, completion_tokens=0, cost=amount, created_at=at))
        await db.commit()

async def check(now=OCT):
    async with SessionLocal() as db:
        return await usage.check_budget(db, now)

async def cards(live=True):
    async with SessionLocal() as db:
        q = select(HomeCard).order_by(HomeCard.created_at)
        if live:
            q = q.where(HomeCard.dismissed.is_(False))
        return (await db.scalars(q)).all()

async def main():
    await spend(7.9)
    assert await check() is None and await cards() == []          # 79%：不发

    await spend(0.2)                                              # 81%
    c = await check()
    assert c is not None and c.kind == "action" and c.target == "usage" and c.unread and "80%" in c.title, c
    text = c.blocks[0]["text"]
    assert "¥8.10" in text and "¥10.00" in text and "81%" in text and "月底大约" in text, text
    assert c.action_prompt
    assert await check() is None and len(await cards()) == 1      # 同一档不重复

    async with SessionLocal() as db:                              # 用户删卡：也不重发
        await db.execute(delete(HomeCard)); await db.commit()
    assert await check() is None and await cards() == []

    await spend(2.0)                                              # 101%：发 100% 档，收起旧预算卡
    async with SessionLocal() as db:
        db.add(HomeCard(kind="action", title="旧预算卡", target="usage", blocks=[]))
        db.add(HomeCard(kind="action", title="别的建议", blocks=[]))
        await db.commit()
    c = await check()
    assert c is not None and "超出" in c.title and "101%" in c.blocks[0]["text"], c.title
    live = [x.title for x in await cards()]
    assert "旧预算卡" not in live and "别的建议" in live and c.title in live, live
    assert await check() is None

    settings.monthly_budget = 20                                  # 改预算：新一组档位（10.1/20 = 50% 不发）
    assert await check() is None
    await spend(6.0)                                              # 16.1/20 = 80.5%
    c = await check()
    assert c is not None and "80%" in c.title and "¥20.00" in c.blocks[0]["text"]

    assert await check(NOV) is None                               # 下个月从零计
    await spend(16.5, NOV)                                        # 82.5% of 20
    c = await check(NOV)
    assert c is not None and "80%" in c.title

    settings.monthly_budget = 0                                   # 不设预算：不检查
    await spend(100)
    assert await check() is None
    settings.monthly_budget = 10

    async with SessionLocal() as db:                              # 并发：两笔同时跨档只有一张
        await db.execute(delete(AlertSent)); await db.execute(delete(HomeCard)); await db.execute(delete(UsageRecord))
        await db.commit()
    await spend(9.0)
    got = await asyncio.gather(check(), check(), check())
    assert sum(x is not None for x in got) == 1, got
    assert len(await cards()) == 1

    async with SessionLocal() as db:                              # 完整路径：record() 记完自动检查（用真实当前时间）
        await db.execute(delete(AlertSent)); await db.execute(delete(HomeCard)); await db.execute(delete(UsageRecord))
        await db.commit()
    await usage.record("fast", "chat", 11, 0)                     # 11 个 token × 1e6/1M = ¥11 → 超出
    live = await cards()
    assert len(live) == 1 and "超出" in live[0].title, [x.title for x in live]

    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as tc:
        tok = tc.post("/api/auth/login", json={"username": "u", "password": "p"}).json()["token"]
        out = tc.get("/api/cards", headers={"Authorization": f"Bearer {tok}"}).json()
        assert out[0]["target"] == "usage" and out[0]["unread"] is True, out
        made = tc.post("/api/cards", json={"kind": "action", "title": "t", "target": "usage"},
                       headers={"Authorization": f"Bearer {tok}"}).json()
        assert made["target"] == "usage"
    print("smoke_budget ok")

asyncio.run(main())
