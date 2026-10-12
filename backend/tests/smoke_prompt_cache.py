# 冒烟：提示缓存（app/prompt_cache.py；命中计数移植自 deepseek-harness token-meter normalizeUsage，prompt_cache_key 嫁接 Codex）。
# 一、cached_of 各家字段 / 不可信数据；cost 命中价；二、真的 llm.stream_turn / complete（假的 create）：命中数记账 + 按命中价算钱、
# prompt_cache_key 默认不发 / 开了按对话发 / 供应商拒收去掉重发且不再发 / 和 reasoning 同时被拒两次重发；三、系统提示排版：
# 时间和记忆变了稳定前缀逐字不变，易变段都在后面；整轮 run_turn：两轮之间（换了时间、记忆、出现摘要、压下的任务结论）
# 系统提示开头相同且摘要在稳定段之后；子助手 ROLE 在稳定段；工具定义顺序固定；四、用量报表带 prompt_tokens / cached_tokens；迁移 down/up。
# 运行：python tests/smoke_prompt_cache.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速", "smart": "深度"}), DEFAULT_MODEL="fast",
  MODEL_PRICES=json.dumps({"fast": [2, 8, 0.5], "smart": [4, 16]}),
  MODEL_REASONING=json.dumps({"smart": ["low", "high"]}), LLM_MAX_RETRIES="0")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

import httpx, openai
from sqlalchemy import select
from app import llm, prompt_cache, reasoning, usage
from app.config import settings
from app.db import SessionLocal
from app.models import UsageRecord

# —— 一、规则 ——
pc = prompt_cache
assert pc.cached_of(None) == 0
assert pc.cached_of(NS(prompt_tokens=100, prompt_tokens_details=NS(cached_tokens=64), model_extra={})) == 64     # OpenAI / 阶跃
assert pc.cached_of(NS(prompt_tokens=100, prompt_tokens_details=None, model_extra={"prompt_cache_hit_tokens": 80})) == 80  # DeepSeek
assert pc.cached_of({"prompt_tokens": 100, "cached_tokens": 30}) == 30                                            # 顶层
assert pc.cached_of({"prompt_tokens": 100, "cache_read_input_tokens": 12}) == 12
assert pc.cached_of({"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 0}}) == 0
assert pc.cached_of({"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 101}}) == 0               # 矛盾 → 不信
for bad in (-1, True, 1.5, "40", None):
    assert pc.cached_of({"prompt_tokens": 100, "cached_tokens": bad}) == 0, bad
assert pc.cached_of({"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": None}, "prompt_cache_hit_tokens": 7}) == 7
assert pc.cached_of(NS(prompt_tokens=10, completion_tokens=2, model_extra=None)) == 0
assert pc.cost(None, 100, 10) == 0
assert pc.cost([2, 8], 1_000_000, 0, 600_000) == 2.0                    # 没配命中价：命中也按输入价
assert pc.cost([2, 8, 0.5], 1_000_000, 1_000_000, 600_000) == (400_000 * 2 + 600_000 * 0.5 + 1_000_000 * 8) / 1_000_000
assert pc.cost([2, 8, 0.5], 100, 0, 500) == pc.cost([2, 8, 0.5], 100, 0, 100)  # 命中数封顶到输入
assert pc.key_for("abc") == "conv-abc" and pc.key_for(None) is None and len(pc.key_for("x" * 100)) == 64
p = pc.Prompt().add(pc.VOLATILE, "时间").add(pc.STABLE, "人设").add(pc.STABLE, "  ").add(pc.STABLE, None).add(pc.STABLE, "技能")
assert p.text() == "人设\n\n技能\n\n时间" and p.prefix() == "人设\n\n技能"
print("ok: rules")

# —— 二、真的 stream_turn / complete，假的 create ——
REQ = httpx.Request("POST", "http://x/chat/completions")
def bad_request(msg):
    return openai.BadRequestError(msg, response=httpx.Response(400, request=REQ), body={"error": {"message": msg}})
assert pc.rejected(bad_request("Unrecognized request argument supplied: prompt_cache_key"))
assert not pc.rejected(bad_request("messages too long"))
assert not pc.rejected(bad_request("Unrecognized request argument supplied: reasoning_effort"))

sent: list[dict] = []
reject: set[str] = set()
USAGE = lambda: NS(prompt_tokens=1000, completion_tokens=10, prompt_tokens_details=NS(cached_tokens=800), model_extra={})

def chunk(text=None, finish=None, usage=None):
    return NS(choices=[NS(delta=NS(content=text, tool_calls=None, model_extra={}), finish_reason=finish)] if text or finish else [],
              usage=usage)

async def fake_create(**kw):
    sent.append(kw)
    if "cache" in reject and "extra_body" in kw:
        raise bad_request("Unrecognized request argument supplied: prompt_cache_key")
    if "effort" in reject and "reasoning_effort" in kw:
        raise bad_request("Unrecognized request argument supplied: reasoning_effort")
    if kw.get("stream"):
        async def gen():
            yield chunk("好")
            yield chunk(finish="stop")
            yield chunk(usage=USAGE())
        return gen()
    return NS(choices=[NS(message=NS(content="摘要"), finish_reason="stop")], usage=USAGE())
llm.client.chat.completions.create = fake_create

async def stream(model="fast", effort=None):
    async for item in llm.stream_turn([{"role": "user", "content": "x"}], None, model, effort):
        last = item
    return last

async def rows():
    async with SessionLocal() as db:
        return (await db.scalars(select(UsageRecord).order_by(UsageRecord.created_at))).all()

with usage.scope("c1"):
    asyncio.run(stream())
assert "extra_body" not in sent[-1]                                       # 默认不发
rs = asyncio.run(rows())
assert rs[-1].cached_tokens == 800 and rs[-1].prompt_tokens == 1000 and rs[-1].conversation_id == "c1"
assert abs(rs[-1].cost - (200 * 2 + 800 * 0.5 + 10 * 8) / 1e6) < 1e-12, rs[-1].cost
settings.prompt_cache_key = True
with usage.scope("c1"):
    asyncio.run(stream())
    asyncio.run(llm.complete([{"role": "user", "content": "x"}]))
assert sent[-2]["extra_body"] == {"prompt_cache_key": "conv-c1"} and sent[-1]["extra_body"] == {"prompt_cache_key": "conv-c1"}
assert asyncio.run(rows())[-1].cached_tokens == 800 and asyncio.run(rows())[-1].kind == "summary"
asyncio.run(stream())
assert "extra_body" not in sent[-1]                                       # 没有对话归属：不发
with usage.scope("c2"):
    asyncio.run(stream("smart"))
assert sent[-1]["extra_body"] == {"prompt_cache_key": "conv-c2"} and asyncio.run(rows())[-1].cost == (1000 * 4 + 10 * 16) / 1e6
# 拒收：去掉重发、记住
reject.add("cache")
n = len(sent)
with usage.scope("c1"):
    t = asyncio.run(stream())
assert t.text == "好" and len(sent) == n + 2 and "extra_body" in sent[n] and "extra_body" not in sent[n + 1]
with usage.scope("c1"):
    asyncio.run(stream())
assert len(sent) == n + 3 and "extra_body" not in sent[-1]
# smart 两个参数都被拒：各去掉一次，共 3 次请求
reject.add("effort")
n = len(sent)
with usage.scope("c3"):
    t = asyncio.run(stream("smart", "high"))
assert t.text == "好" and len(sent) == n + 3, len(sent) - n
assert "reasoning_effort" not in sent[-1] and "extra_body" not in sent[-1]
reject.clear(); reasoning.reload(); pc._unsupported.clear(); settings.prompt_cache_key = False
# 别的 400 原样抛
async def boom(**kw):
    raise bad_request("messages too long")
llm.client.chat.completions.create = boom
try:
    asyncio.run(stream())
    raise AssertionError("should raise")
except openai.BadRequestError:
    pass
llm.client.chat.completions.create = fake_create
print("ok: llm")

# —— 三、排版 ——
from datetime import datetime as real_dt
from app.agent import context, loop, runner, subagent
from app.agent.tools import REGISTRY, ToolContext, load_builtin, schemas
from app.models import Conversation, Memory, Message
load_builtin()

class FakeDT(real_dt):
    at = real_dt(2026, 10, 12, 9, 0)
    @classmethod
    def now(cls, tz=None):
        return cls.at.replace(tzinfo=tz)
context.datetime = FakeDT

async def fake_embed(texts):
    return [[1.0] + [0.0] * 7 for _ in texts]
llm.embed = fake_embed

async def layout():
    async with SessionLocal() as db:
        a = await context.build_system_prompt(db, None, "")
        db.add(Memory(id="m" * 32, category="food", content="不吃辣"))
        await db.commit()
        FakeDT.at = real_dt(2026, 10, 12, 9, 7)
        b = await context.build_system_prompt(db, None, "吃什么")
        return a, b
a, b = asyncio.run(layout())
assert a.prefix() == b.prefix() and a.prefix() and b.text().startswith(b.prefix())
assert "09:00" in a.text() and "09:07" in b.text() and "不吃辣" in b.text() and "不吃辣" not in b.prefix()
bt = b.text()
assert bt.index("现在是") > len(b.prefix()) and bt.index("不吃辣") > bt.index("现在是")
assert all("现在是" not in s for s in b.stable)

# 整轮：抓每轮发给模型的系统提示
systems: list[str] = []
async def fake_stream_turn(messages, tools=None, model=None, effort=None):
    systems.append(messages[0]["content"])
    yield "好"
    yield llm.Turn(text="好")
loop.stream_turn = fake_stream_turn

async def turns():
    async with SessionLocal() as db:
        conv = Conversation(title="t")
        db.add(conv)
        await db.commit()
        cid = conv.id
        db.add(Message(conversation_id=cid, role="user", blocks=[{"type": "text", "text": "第一问"}]))
        await db.commit()
        await runner.run_turn(db, await db.get(Conversation, cid))
        FakeDT.at = real_dt(2026, 10, 12, 9, 30)
        orig_hist = runner.build_history
        async def with_summary(*a, **kw):
            h = await orig_hist(*a, **kw)
            return context.History(summary="早先聊过：用户在做自建助手", messages=h.messages)
        runner.build_history = with_summary
        db.add(Message(conversation_id=cid, role="user", blocks=[{"type": "text", "text": "吃什么"}]))
        await db.commit()
        orig = runner.jobs.take_held
        async def held(db, cid):
            return "后台任务的结论：备份完成"
        runner.jobs.take_held = held
        try:
            await runner.run_turn(db, await db.get(Conversation, cid))
        finally:
            runner.jobs.take_held = orig
            runner.build_history = orig_hist
asyncio.run(turns())
s1, s2 = systems[-2], systems[-1]
head = s1[:s1.index("现在是")]
assert len(head) > 200 and s2.startswith(head), (head[-200:], s2[:400])
assert s2.index("早先聊过") > s2.index("现在是") and s2.index("备份完成") > s2.index("早先聊过"), s2[-400:]
# 子助手 ROLE 在稳定段（时间之前）
async def child_prompt():
    async with SessionLocal() as db:
        return (await context.build_system_prompt(db, None, "x")).add(prompt_cache.STABLE, subagent.ROLE).text()
cp = asyncio.run(child_prompt())
assert cp.index("你现在是子助手") < cp.index("现在是 ")
# 工具顺序：按模块名导入，每次相同
names = [s["function"]["name"] for s in schemas(ToolContext(db=None))]
assert names == [s["function"]["name"] for s in schemas(ToolContext(db=None))] and len(names) > 20
mods = [REGISTRY[n].run.__module__ for n in REGISTRY]
first_seen = list(dict.fromkeys(m for m in mods if m.startswith("app.agent.builtin.")))
assert first_seen == sorted(first_seen), first_seen
print("ok: layout")

# —— 四、报表 + 迁移 ——
async def rep():
    async with SessionLocal() as db:
        return await usage.report(db), await usage.conversation_report(db, "c1")
full, conv1 = asyncio.run(rep())
m = full["today"]
assert m["prompt_tokens"] >= 1000 and m["cached_tokens"] > 0 and m["cached_tokens"] <= m["prompt_tokens"]
fast = next(x for x in m["models"] if x["model"] == "fast")
assert fast["cached_tokens"] == sum(r.cached_tokens for r in asyncio.run(rows()) if r.model == "fast")
assert conv1["total"]["cached_tokens"] == 800 * 5 and conv1["total"]["prompt_tokens"] == 1000 * 5, conv1["total"]
for args in (["downgrade", "0035"], ["upgrade", "head"]):
    r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
print("ok: report + migration")
print("ALL OK")
