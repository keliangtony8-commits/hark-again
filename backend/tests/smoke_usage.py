# 冒烟：用量与花费。模拟到 OpenAI 客户端这一层（真实走 llm.py 的解析和记账）：
# 流式聊天最后一个包带 usage → 记一行 chat（归属当前对话，按单价算钱）；摘要/向量各记一行且分类正确；
# 没定价的别名只记 token；没有 usage（中途停止）不记；记账出错不影响调用；
# 报表按用户时区切“今天/本月”（跨月、跨日边界）；/api/usage 路由。
# 运行：python tests/smoke_usage.py
import os, sys, asyncio, subprocess, tempfile, json
from datetime import datetime, timezone
from types import SimpleNamespace as NS
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="",
  MODEL_PRICES=json.dumps({"fast": [2, 8], "smart": [4, 16]}), MONTHLY_BUDGET="30", TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from app import llm, usage
from app.agent import runner
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message, UsageRecord
from sqlalchemy import delete, select

def chunk(text=None, u=None):
    choices = [NS(delta=NS(content=text, tool_calls=None))] if text is not None else []
    return NS(choices=choices, usage=u)

mode = {"usage": True}
async def fake_create(model, messages, stream=False, stream_options=None, **kw):
    if stream:
        assert stream_options == {"include_usage": True}
        async def gen():
            yield chunk("你好")
            yield chunk("！")
            if mode["usage"]:
                yield chunk(u=NS(prompt_tokens=1000, completion_tokens=500))
        return gen()
    return NS(choices=[NS(message=NS(content=" 摘要 "))], usage=NS(prompt_tokens=300, completion_tokens=100))
llm.client.chat.completions.create = fake_create

async def fake_embed(model, input):
    return NS(data=[NS(embedding=[0.1, 0.2]) for _ in input], usage=NS(prompt_tokens=12, total_tokens=12))
llm.client.embeddings.create = fake_embed

async def rows():
    async with SessionLocal() as db:
        return (await db.scalars(select(UsageRecord).order_by(UsageRecord.created_at))).all()

async def main():
    async with SessionLocal() as db:
        conv = Conversation(); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("嗨")))
        await db.commit(); cid = conv.id
        reply = await runner.run_turn(db, conv)
    assert reply is not None
    r = await rows()
    assert len(r) == 1 and r[0].kind == "chat" and r[0].model == "fast" and r[0].conversation_id == cid, r
    assert (r[0].prompt_tokens, r[0].completion_tokens) == (1000, 500)
    assert abs(r[0].cost - (1000 * 2 + 500 * 8) / 1e6) < 1e-12, r[0].cost

    assert await llm.complete([{"role": "user", "content": "x"}], model="smart") == "摘要"
    assert await llm.embed(["a", "b"]) == [[0.1, 0.2], [0.1, 0.2]]
    r = await rows()
    assert [x.kind for x in r] == ["chat", "summary", "embed"], [x.kind for x in r]
    assert r[1].conversation_id is None and r[1].model == "smart" and abs(r[1].cost - (300 * 4 + 100 * 16) / 1e6) < 1e-12
    assert r[2].model == "embed" and r[2].prompt_tokens == 12 and r[2].cost == 0.0   # 没定价：只记 token

    with usage.scope("c2"):                         # 作用域：深处调用自动归属，出了作用域复原
        await llm.complete([{"role": "user", "content": "x"}])
    assert (await rows())[-1].conversation_id == "c2" and usage._conversation.get() is None

    mode["usage"] = False                           # 没给 usage（比如中途停止）：不记，不报错
    n = len(await rows())
    out = [x async for x in llm.stream_turn([{"role": "user", "content": "x"}])]
    assert out[-1].text == "你好！" and len(await rows()) == n
    mode["usage"] = True

    real = usage.SessionLocal                        # 记账失败：吞掉，调用照常返回
    usage.SessionLocal = None
    assert await llm.complete([{"role": "user", "content": "x"}]) == "摘要"
    usage.SessionLocal = real

    # 报表：上海时间 2026-10-01 07:00 = UTC 09-30 23:00；“今天/本月”都从上海 10-01 00:00（UTC 09-30 16:00）起
    async with SessionLocal() as db:
        await db.execute(delete(UsageRecord))
        U = lambda m, p, c, t: UsageRecord(model=m, kind="chat", prompt_tokens=p, completion_tokens=c,
                                           cost=usage.cost_of(m, p, c), created_at=t)
        db.add_all([
            U("fast", 1_000_000, 0, datetime(2026, 9, 30, 15, 59, tzinfo=timezone.utc)),   # 上海 9-30 23:59：上个月
            U("fast", 1_000_000, 1_000_000, datetime(2026, 9, 30, 16, 0, tzinfo=timezone.utc)),  # 上海 10-01 00:00
            U("smart", 500_000, 0, datetime(2026, 9, 30, 22, 0, tzinfo=timezone.utc)),
        ])
        await db.commit()
        rep = await usage.report(db, now=datetime(2026, 9, 30, 23, 0, tzinfo=timezone.utc))
    assert rep["currency"] == "CNY" and rep["budget"] == 30 and rep["priced"] == ["fast", "smart"], rep
    assert rep["today"] == rep["month"], rep
    m = rep["month"]
    assert m["calls"] == 2 and m["tokens"] == 2_500_000 and m["cost"] == 12.0, m
    assert [x["model"] for x in m["models"]] == ["fast", "smart"] and m["models"][0]["cost"] == 10.0, m
    async with SessionLocal() as db:                 # 第二天：今天空，本月照算
        rep = await usage.report(db, now=datetime(2026, 10, 1, 17, 0, tzinfo=timezone.utc))
    assert rep["today"] == {"calls": 0, "tokens": 0, "cost": 0, "models": []} and rep["month"]["cost"] == 12.0, rep

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth import require_user
    from app.routes import usage as ru
    app = FastAPI(); app.include_router(ru.router)
    app.dependency_overrides[require_user] = lambda: "u"
    return app

app = asyncio.run(main())
from fastapi.testclient import TestClient
res = TestClient(app).get("/api/usage")
assert res.status_code == 200 and set(res.json()) == {"currency", "budget", "priced", "today", "month", "daily", "conversations", "last_month"}, res.text
print("usage smoke OK")
