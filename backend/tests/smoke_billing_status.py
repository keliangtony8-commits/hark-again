# 冒烟：v2.39 BRAIN (bc) billing_status——app/billing_status.py 唯一规则 + 工具。
# 1) 规则：overview（今天 / 本月 / 上月同期 / 预算百分比 + 月底估计 / 最花钱的模型与对话 / 没定价的模型 / 磁盘）；
#    没设预算、空库、对话已删、当前对话叫“这段对话”；conversation / day；parse_day；
# 2) 工具：deferred + parallel + 计划模式可用；scope 错 / 日期错；后台无对话；
# 3) 一轮（模拟模型，经 deferred_tool call）：工具结果里的数进了下一次模型调用。
# 运行：python tests/smoke_billing_status.py
import os, sys, asyncio, subprocess, tempfile, json
from datetime import date, datetime, timezone
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  MODEL_PRICES=json.dumps({"fast": [2, 8]}), MONTHLY_BUDGET="10", TIMEZONE="Asia/Shanghai", WORKSPACE_DISK_MB="1",
  CHAT_MODELS=json.dumps({"fast": "快速", "smart": "聪明"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import billing_status as B, plan_mode, quota, usage
from app.agent.runner import run_turn
from app.agent.tools import REGISTRY, ToolContext, load_builtin, nobody
from app.blocks import text_to_blocks
from app.config import settings
from app.db import SessionLocal
from app.models import Conversation, Message, UsageRecord
from app.storage import project_dir

UTC = timezone.utc
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)  # 上海 20:00，13 号
def U(model, p, c, at, cid=None):
    return UsageRecord(model=model, kind="chat", prompt_tokens=p, completion_tokens=c, conversation_id=cid,
                       cost=usage.cost_of(model, p, c), created_at=at)

# 月底估计：月初不足一天按一天
assert abs(usage.month_projection(1.0, datetime(2026, 10, 1, 0, 30, tzinfo=UTC)) - 31.0) < 1e-9
assert abs(usage.month_projection(12.0, NOW) - 12.0 / (12 + 20 / 24) * 31) < 1e-6
assert usage.money(1.5) == "¥1.50"
assert B.parse_day("2026-10-12") == date(2026, 10, 12) and B.parse_day("今天", NOW) == date(2026, 10, 13)
try:
    B.parse_day("昨天"); raise SystemExit("昨天 should fail")
except ValueError as e:
    assert "resolve_relative_date" in str(e)

load_builtin()
t = REGISTRY["billing_status"]
assert t.deferred and t.parallel and "billing_status" in plan_mode.READ_TOOLS

async def main():
    async with SessionLocal() as db:
        empty = await B.overview(db, "me", now=NOW)
        assert "今天：¥0.00（0 次调用，0 token）" in empty and "上月同期没有花费" in empty, empty
        assert "已用 0%，还剩 ¥10.00" in empty and "花得最多" not in empty and "没设单价" not in empty, empty

        a = Conversation(title="旅行计划"); b = Conversation(title="写简历"); db.add_all([a, b]); await db.flush()
        db.add_all([
            U("fast", 1_000_000, 100_000, datetime(2026, 10, 13, 2, tzinfo=UTC), a.id),   # ¥2.80 今天（上海 10 点）
            U("fast", 500_000, 0, datetime(2026, 10, 12, 2, tzinfo=UTC), b.id),           # ¥1.00 12 号
            U("smart", 40_000, 2_000, datetime(2026, 10, 12, 3, tzinfo=UTC), "gone"),     # 没定价，对话已删
            U("fast", 1_000_000, 0, datetime(2026, 9, 5, 2, tzinfo=UTC), a.id),           # ¥2.00 上月同期内
            U("fast", 1_000_000, 0, datetime(2026, 9, 20, 2, tzinfo=UTC), a.id),          # ¥2.00 上月同期外
        ])
        await db.commit()
        d = project_dir("me"); d.mkdir(parents=True, exist_ok=True)
        (d / "big.bin").write_bytes(b"x" * 900_000); quota.forget()

        text = await B.overview(db, "me", a.id, now=NOW)
        print(text)
        assert "今天：¥2.80（1 次调用，110 万 token）" in text and "昨天（10-12）：¥1.00（2 次调用" in text, text
        assert "本月至今（10 月 1 日起）：¥3.80（3 次调用" in text, text
        assert "比上月同期（¥2.00）多 90%；上月全月 ¥4.00" in text, text
        assert "已用 38%，还剩 ¥6.20；照这个速度月底约 ¥9.18" in text, text  # 3.80/12.83*31
        assert "本月花得最多的模型：快速 ¥3.80；聪明 未定价（4.2 万 token）" in text, text
        assert "本月花得最多的对话：这段对话 ¥2.80；「写简历」 ¥1.00；一段已删除的对话 ¥0.00" in text, text
        assert "聪明 没设单价" in text and "MODEL_PRICES" in text, text
        assert "已用 878.9 KB / 上限 1 MB（86%，快满了）" in text, text
        assert "自动选模型" not in text

        settings.monthly_budget = 3
        assert "已超出 ¥0.80" in await B.overview(db, "me", now=NOW)
        settings.monthly_budget = 0
        assert "没设每月预算" in await B.overview(db, "me", now=NOW)
        settings.monthly_budget = 10

        c = await B.conversation(db, a.id)
        assert c.startswith("这段对话从开始到现在：¥6.80（3 次调用") and "按模型：快速 ¥6.80" in c, c
        assert "还没有记到" in await B.conversation(db, "nope") and "后台运行" in await B.conversation(db, None)
        day = await B.day(db, date(2026, 10, 12), a.id)
        assert day.startswith("2026-10-12（用户时区）：¥1.00（2 次调用") and "「写简历」 ¥1.00" in day and "聪明 没设单价" in day, day
        assert "没有模型调用，花费 ¥0.00" in await B.day(db, date(2026, 8, 1))

        ctx = ToolContext(db=db, conversation_id=a.id)
        res = await t.run(ctx, scope="day", date="2026-10-12")
        assert res.content == day and res.detail == "2026-10-12 的用量" and not res.failed
        assert (await t.run(ctx, scope="week")).failed == "参数不对"
        assert (await t.run(ctx, scope="day", date="上周一")).failed == "日期不对"
        assert (await t.run(ctx, scope="conversation")).content == c
        assert "后台运行" in (await t.run(ToolContext(db=db, ask=nobody), scope="conversation")).content
        res = await t.run(ctx)
        assert res.detail == "本月用量" and "本月至今" in res.content
        return a.id
cid = asyncio.run(main())

# ---- 一轮（模拟模型）：经 deferred_tool call，结果进下一次调用 ----
from app import llm
seen, script = [], []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append({"messages": [dict(m) for m in messages], "tools": [x["function"]["name"] for x in tools or []]})
    step = script.pop(0)
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"b{len(script)}-{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
async def seed():
    async with SessionLocal() as db:
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks("这个月花了多少钱？")))
        await db.commit()
async def _ask(_id, _form):
    return None
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0), ask=_ask)
asyncio.run(seed())
script.extend([[("deferred_tool", {"action": "call", "tool": "billing_status", "arguments": {}})], "本月花了不少。"])
reply = asyncio.run(turn())
assert "billing_status" not in seen[0]["tools"], seen[0]["tools"]
tool_msgs = [m for m in seen[1]["messages"] if m.get("role") == "tool"]
assert tool_msgs and "本月至今" in str(tool_msgs[-1]["content"]), tool_msgs
assert [(x["tool"], x["state"]) for x in reply.steps] == [("billing_status", "done")], reply.steps
print("smoke_billing_status ok")
