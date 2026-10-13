# 冒烟：自动选模型的账（app/router_stats.py，v1.95）。模拟到 OpenAI 客户端这一层（真实走 llm.py 记账、runner 路由）。
# 一、整轮：auto 对话四轮（寒暄=规则简单、天气=分类器简单、规划=分类器复杂、“继续”=沿用复杂）→ routings 四行（来源去掉链名前缀），
#    usage.route 打在这一轮的 chat 调用上，分类器调用不打；手选模型的轮不记、不打。
# 二、month：轮数 / 简单 / 复杂 / 零调用 / 分类器轮数与花费与平均毫秒 / 简单档实花 / 按复杂档单价重算省下 / 净省；
#    复杂档没定价 → saved、net 为 null；本月一轮自动都没有 → null；/api/usage 带 router；迁移 down/up。
# 运行：python tests/smoke_router_stats.py
import os, sys, asyncio, subprocess, tempfile, json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", LLM_MAX_RETRIES="0",
  NEXT_SPEAKER_CHECK="off", AUTO_TITLE="false", TIMEZONE="Asia/Shanghai",
  MODEL_PRICES=json.dumps({"fast": [2, 8], "smart": [4, 16]}))
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from app import llm, model_router as mr, router_stats, usage
from app.agent import runner
from app.auth import require_user
from app.blocks import text_to_blocks
from app.config import settings
from app.db import SessionLocal
from app.models import Conversation, Message, Routing, UsageRecord
from app.routes import usage as ru

assert router_stats.source_of("router/classifier") == "classifier" and router_stats.source_of("") == "default"
assert router_stats.source_of("router/override") == "override"


def chunk(text=None, u=None):
    choices = [NS(delta=NS(content=text, tool_calls=None), finish_reason=None)] if text is not None else []
    return NS(choices=choices, usage=u)


seen_models: list[str] = []


async def fake_create(model, messages, stream=False, stream_options=None, **kw):
    if stream:
        seen_models.append(model)
        async def gen():
            yield chunk("好")
            yield chunk(u=NS(prompt_tokens=1000, completion_tokens=500, prompt_tokens_details=None))
        return gen()
    assert messages[0]["content"] == mr.CLASSIFIER_PROMPT, "只有分类器走非流式"
    pick = "complex" if "规划" in messages[-1]["content"] else "simple"
    return NS(choices=[NS(message=NS(content=json.dumps({"reasoning": "r", "model_choice": pick})), finish_reason="stop")],
              usage=NS(prompt_tokens=300, completion_tokens=100, prompt_tokens_details=None))
llm.client.chat.completions.create = fake_create


async def say(cid: str, text: str, model: str | None = None):
    async with SessionLocal() as db:
        conv = await db.get(Conversation, cid)
        if model:
            conv.model = model
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks(text)))
        await db.commit()
        assert await runner.run_turn(db, conv) is not None


async def main():
    since = datetime.now(timezone.utc) - timedelta(days=1)
    async with SessionLocal() as db:
        assert await router_stats.month(db, since) is None                  # 一轮自动都没有
        conv = Conversation(model="auto"); db.add(conv); await db.commit(); cid = conv.id
    for t in ("你好", "明天上海天气怎么样", "帮我规划日本十天行程", "继续"):
        await say(cid, t)
    assert seen_models == [llm.upstream(x) for x in ("fast", "fast", "smart", "smart")], seen_models
    await say(cid, "手选一轮", model="smart")                                 # override：不记、不打
    async with SessionLocal() as db:
        rs = (await db.scalars(select(Routing).order_by(Routing.created_at))).all()
        us = (await db.scalars(select(UsageRecord).order_by(UsageRecord.created_at))).all()
    assert [(x.complexity, x.source, x.model) for x in rs] == [
        ("simple", "rules", "fast"), ("simple", "classifier", "fast"), ("complex", "classifier", "smart"), ("complex", "sticky", "smart")], rs
    assert all(x.conversation_id == cid and x.ms >= 0 for x in rs)
    chats = [(u.model, u.route) for u in us if u.kind == "chat"]
    assert chats == [("fast", "simple"), ("fast", "simple"), ("smart", "complex"), ("smart", "complex"), ("smart", None)], chats
    assert [u.route for u in us if u.kind == "router"] == [None, None]
    async with SessionLocal() as db:
        m = await router_stats.month(db, since)
    assert (m["turns"], m["simple"], m["complex"], m["free"]) == (4, 2, 2, 2), m
    assert m["classifier"]["turns"] == 2 and abs(m["classifier"]["cost"] - 2 * (300 * 2 + 100 * 8) / 1e6) < 1e-9, m
    assert abs(m["simple_cost"] - 2 * 0.006) < 1e-9 and abs(m["saved"] - 2 * (0.012 - 0.006)) < 1e-9, m
    assert abs(m["net"] - (0.012 - 0.0028)) < 1e-9 and m["simple_model"] == mr.label_of("fast") and m["complex_model"] == mr.label_of("smart")
    prices = dict(settings.model_prices)
    settings.model_prices = {"fast": [2, 8]}                                 # 复杂档没定价：不估
    async with SessionLocal() as db:
        m2 = await router_stats.month(db, since)
    assert m2["saved"] is None and m2["net"] is None and m2["turns"] == 4
    settings.model_prices = prices
    async with SessionLocal() as db:                                         # 窗口外的不算
        assert await router_stats.month(db, datetime.now(timezone.utc) + timedelta(minutes=1)) is None
asyncio.run(main())
print("ok: month")

app = FastAPI()
app.include_router(ru.router)
app.dependency_overrides[require_user] = lambda: "u"
rep = TestClient(app).get("/api/usage").json()
assert rep["router"]["turns"] == 4 and rep["router"]["saved"] is not None, rep.get("router")
print("ok: api")

for step in ("downgrade", "upgrade"):
    rv = subprocess.run([sys.executable, "-m", "alembic", step, "-1" if step == "downgrade" else "head"], cwd=root,
                        capture_output=True, text=True)
    assert rv.returncode == 0, rv.stderr
print("ok: migration")
print("all ok")
