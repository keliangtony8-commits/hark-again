# 冒烟：单个对话的用量（GET /api/conversations/{id}/usage）。
# 模拟到 OpenAI 客户端这一层：对话 A 两轮（第二轮换 smart）+ 一次作用域内的摘要 → A 的累计按模型拆分、钱对得上；
# 对话 B 只算自己的；没有归属的调用不算进任何对话；空对话 = 全零；不存在的对话 404；
# 删掉对话后用量行还在（月度总账不变）；/api/usage 报表形状不变（重构了共用的汇总）。
# 运行：python tests/smoke_conversation_usage.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="",
  MODEL_PRICES=json.dumps({"fast": [2, 8], "smart": [4, 16]}), MONTHLY_BUDGET="0", TIMEZONE="Asia/Shanghai",
  CHAT_MODELS=json.dumps({"fast": "快速", "smart": "深度"}))
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from app import llm, usage
from app.agent import runner
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message, UsageRecord
from sqlalchemy import func, select

def chunk(text=None, u=None):
    choices = [NS(delta=NS(content=text, tool_calls=None))] if text is not None else []
    return NS(choices=choices, usage=u)

async def fake_create(model, messages, stream=False, stream_options=None, **kw):
    if stream:
        async def gen():
            yield chunk("好的")
            yield chunk(u=NS(prompt_tokens=1000, completion_tokens=500))
        return gen()
    return NS(choices=[NS(message=NS(content="摘要"))], usage=NS(prompt_tokens=300, completion_tokens=100))
llm.client.chat.completions.create = fake_create

async def turn(cid, text, model=None):
    async with SessionLocal() as db:
        conv = await db.get(Conversation, cid)
        if model is not None:
            runner.apply_model(conv, model)
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks(text)))
        await db.commit()
        assert await runner.run_turn(db, conv) is not None

async def main():
    async with SessionLocal() as db:
        a, b, empty = Conversation(), Conversation(), Conversation()
        db.add_all([a, b, empty]); await db.commit()
        ids = a.id, b.id, empty.id
    A, B, E = ids
    await turn(A, "第一问")
    await turn(A, "第二问", model="smart")
    with usage.scope(A):                                  # 深处调用（摘要）自动归到 A
        await llm.complete([{"role": "user", "content": "x"}])
    await turn(B, "别的对话")
    await llm.complete([{"role": "user", "content": "x"}])  # 没有归属：不进任何对话

    async with SessionLocal() as db:
        ra = await usage.conversation_report(db, A)
        rb = await usage.conversation_report(db, B)
        re = await usage.conversation_report(db, E)
    assert ra["currency"] == "CNY" and ra["priced"] == ["fast", "smart"], ra
    t = ra["total"]
    assert t["calls"] == 3 and t["tokens"] == 1500 * 2 + 400, t
    fast = (1000 * 2 + 500 * 8 + 300 * 2 + 100 * 8) / 1e6   # 一轮聊天 + 摘要（默认 summary_model=fast）
    smart = (1000 * 4 + 500 * 16) / 1e6
    assert [m["model"] for m in t["models"]] == ["smart", "fast"], t   # 按花费降序
    by = {m["model"]: m for m in t["models"]}
    assert by["fast"]["calls"] == 2 and abs(by["fast"]["cost"] - round(fast, 4)) < 1e-9, by
    assert by["smart"]["calls"] == 1 and abs(by["smart"]["cost"] - round(smart, 4)) < 1e-9, by
    assert abs(t["cost"] - round(round(fast, 4) + round(smart, 4), 4)) < 1e-9, t
    assert rb["total"]["calls"] == 1 and rb["total"]["tokens"] == 1500, rb
    assert re["total"] == {"calls": 0, "tokens": 0, "cost": 0, "models": []}, re

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth import require_user
    from app.routes import conversations as rc, usage as ru
    app = FastAPI(); app.include_router(rc.router); app.include_router(ru.router)
    app.dependency_overrides[require_user] = lambda: "u"
    return app, ids

app, (A, B, E) = asyncio.run(main())
from fastapi.testclient import TestClient
c = TestClient(app)
r = c.get(f"/api/conversations/{A}/usage")
assert r.status_code == 200 and set(r.json()) == {"currency", "priced", "total"} and r.json()["total"]["calls"] == 3, r.text
assert c.get("/api/conversations/nope/usage").status_code == 404
assert set(c.get("/api/usage").json()) == {"currency", "budget", "priced", "today", "month", "daily", "conversations", "last_month"}
month_before = c.get("/api/usage").json()["month"]["calls"]
assert c.delete(f"/api/conversations/{A}").json() == {"ok": True}
assert c.get(f"/api/conversations/{A}/usage").status_code == 404
assert c.get("/api/usage").json()["month"]["calls"] == month_before   # 删对话不改总账

async def left():
    async with SessionLocal() as db:
        return await db.scalar(select(func.count()).select_from(UsageRecord).where(UsageRecord.conversation_id == A))
assert asyncio.run(left()) == 3
print("conversation usage smoke OK")
