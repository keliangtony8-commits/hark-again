# 冒烟：v1.03 “帮我准备今天”——day_overview 工具（app/day_brief.py）+ 技能 prep-my-day。模拟模型，无迁移（只读）。
# - 今天的日程：报告任务按钟点排序；已完成/失败/待运行/自动暂停各自标出；每小时的合成一行；手动停的、面板、明天的一次性不列；
# - 主页：系统提醒 = 需要用户亲自处理；智能体建议带按钮字；稍后提醒到今天的标出几点回来，到别的日子的不列；收起的不列；
# - 收件箱：只数未读；
# - 记忆：写了今天/几天内日期的、写了今天星期几的进来，远的、过去的不进；
# - 一轮对话：模型调 day_overview → show_summary，回复里有简报卡；工具结果交回模型；没有安排时提示别编造。
# 运行：python tests/smoke_day_brief.py
import os, sys, asyncio, subprocess, tempfile, json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from app import day_brief, llm, skills_store
from app.agent import runner
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.blocks import text_to_blocks
from app.config import settings
from app.db import SessionLocal
from app.models import Conversation, HomeCard, Memory, Message, ScheduledTask

TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 12, 10, 30, tzinfo=TZ)  # 周一
at = lambda h, m=0, d=0: (NOW.replace(hour=h, minute=m) + timedelta(days=d)).astimezone(timezone.utc)

# --- 纯规则 ---
today = NOW.date()
assert day_brief.memory_dates("2026-10-14 交高数作业", today) == [date(2026, 10, 14)]
assert day_brief.memory_dates("10月12日牙医复诊", today) == [today]
assert day_brief.memory_dates("2026年10月13号 面试", today) == [date(2026, 10, 13)]
assert day_brief.memory_dates("生日是3月5日", today) == []          # 明年，太远
assert day_brief.memory_dates("10月1日国庆", today) == []           # 已过 → 明年
assert day_brief.memory_dates("2026-10-30 期中考", today) == []
assert day_brief.memory_dates("2026-02-30 坏日期", today) == []
assert day_brief.mentions_weekday("每周一下午有实验课", today) and day_brief.mentions_weekday("星期一开组会", today)
assert not day_brief.mentions_weekday("周三游泳", today)
assert day_brief.day_label(date(2026, 10, 14)) == "10月14日 周三"

async def seed():
    async with SessionLocal() as db:
        db.add_all([
            ScheduledTask(name="早报", prompt="p", cron="0 8 * * *", last_run_at=at(8, 1), last_status="ok"),
            ScheduledTask(name="查成绩", prompt="p", cron="0 9 * * *", last_run_at=at(9, 1), last_status="error", fail_streak=1),
            ScheduledTask(name="背单词", prompt="p", cron="0 11 * * *"),
            ScheduledTask(name="盯快递", prompt="p", cron="0 * * * *", last_run_at=at(10), last_status="ok"),
            ScheduledTask(name="抢课", prompt="p", cron="0 13 * * *", active=False, paused_reason="failures", fail_streak=3),
            ScheduledTask(name="已停的", prompt="p", cron="0 12 * * *", active=False),
            ScheduledTask(name="天气面板", prompt="p", cron="0 7 * * *", output="panel"),
            ScheduledTask(name="交作业提醒", prompt="p", cron="", run_at=at(15)),
            ScheduledTask(name="明天的提醒", prompt="p", cron="", run_at=at(9, d=1)),
            HomeCard(kind="action", title="GitHub 连接已失效", blocks=text_to_blocks("令牌被撤销了。"), target="connectors"),
            HomeCard(kind="action", title="续费校园网", blocks=text_to_blocks("周五到期。"), action_prompt="续费",
                     action_label="帮我续费", origin="agent"),
            HomeCard(kind="action", title="回导师邮件", blocks=[], action_prompt="起草", origin="agent", snoozed_until=at(14)),
            HomeCard(kind="action", title="下周再说", blocks=[], action_prompt="x", origin="agent", snoozed_until=at(9, d=3)),
            HomeCard(kind="action", title="收起了的", blocks=[], action_prompt="x", dismissed=True),
            HomeCard(kind="report", title="早报 10-12", blocks=text_to_blocks("晴"), unread=True),
            HomeCard(kind="report", title="成绩播报", blocks=[], unread=True),
            HomeCard(kind="report", title="昨天的早报", blocks=[], unread=False),
            Memory(content="2026-10-14 交高数作业", category="study"),
            Memory(content="10月12日下午三点牙医复诊", category="health"),
            Memory(content="每周一下午有实验课", category="study"),
            Memory(content="2026-10-30 期中考", category="study"),
            Memory(content="喜欢喝美式", category="food"),
        ])
        await db.commit()

async def gather():
    async with SessionLocal() as db:
        return await day_brief.gather(db, NOW)

asyncio.run(seed())
b = asyncio.run(gather())
text = b.text()
print(text)
assert text.startswith("今天 2026-10-12 周一，现在 10:30（Asia/Shanghai）。"), text
names = [l.split("「")[1].split("」")[0] for l in b.agenda]
assert names == ["盯快递", "早报", "查成绩", "背单词", "抢课", "交作业提醒"], names
line = dict(zip(names, b.agenda))
assert line["早报"] == "- 08:00「早报」已完成"
assert line["查成绩"] == "- 09:00「查成绩」失败了"
assert line["背单词"] == "- 11:00「背单词」待运行"
assert line["交作业提醒"] == "- 15:00「交作业提醒」待运行"
assert line["盯快递"] == "- 00:00–23:00「盯快递」今天 24 次，已过 11 次，下一次 11:00", line["盯快递"]
assert "连续失败 3 次已自动暂停，今天不会跑" in line["抢课"] and line["抢课"].startswith("- 13:00")
assert not any(x in text for x in ("已停的", "天气面板", "明天的提醒", "下周再说", "收起了的", "昨天的早报", "期中考", "美式"))
cards = "\n".join(b.cards)
assert "「GitHub 连接已失效」需要用户亲自处理：令牌被撤销了。" in cards, cards
assert "「续费校园网」你提议的，按钮“帮我续费”：周五到期。" in cards, cards
assert "「回导师邮件」你提议的，按钮“去做”，稍后提醒，今天 14:00 回来" in cards, cards
assert b.unread == 2 and len(b.reports) == 2 and "【收件箱】未读 2 条" in text
mem = b.memories
assert mem[0].startswith("- 今天：10月12日下午三点牙医复诊") or mem[0].startswith("- 今天是周一"), mem
assert any(l.startswith("- 2 天后（10月14日 周三）：2026-10-14 交高数作业") for l in mem), mem
assert any(l.startswith("- 今天是周一：每周一下午有实验课") for l in mem), mem
assert len(mem) == 3 and not b.empty
# 过了午夜的同一个时刻：每天任务按新的一天重新排（昨天跑过不算今天完成）
async def gather_at(t):
    async with SessionLocal() as db:
        return await day_brief.gather(db, t)
b2 = asyncio.run(gather_at(NOW + timedelta(days=1)))
assert "- 08:00「早报」到点了，马上跑" in b2.agenda, b2.agenda
assert any("「明天的提醒」" in l for l in b2.agenda) and not any("交作业提醒" in l for l in b2.agenda)

# --- 一轮对话：模型 day_overview → show_summary ---
script: list = []
tool_results: list[str] = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    if messages and messages[-1]["role"] == "tool":
        tool_results.append(messages[-1]["content"])
    if tools is not None:
        assert any(t["function"]["name"] == "day_overview" for t in tools)
        assert "prep-my-day" in messages[0]["content"]  # 技能目录里有它
    step = script.pop(0)
    async def gen():
        if isinstance(step, tuple):
            yield chunk(tool=[NS(index=0, id=f"c{len(script)}", function=NS(name=step[0], arguments=json.dumps(step[1], ensure_ascii=False)))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()
assert "day_overview" in REGISTRY and "day_overview" in settings.system_prompt
skill = skills_store.get_skill("prep-my-day")
assert skill and "day_overview" in skill.body and "show_summary" in skill.body

SUMMARY = {"title": "今天 · 10月12日 周一", "markdown": "下午牙医，先把查成绩修好。\n\n**时间线**\n- 11:00 背单词"}
async def turn():
    script.extend([("day_overview", {}), ("show_summary", SUMMARY), "先修好查成绩任务。"])
    async with SessionLocal() as db:
        conv = Conversation(id="c1", title="t"); db.add(conv); await db.commit()
        db.add(Message(conversation_id="c1", role="user", blocks=text_to_blocks("帮我准备今天")))
        await db.commit()
        return await runner.run_turn(db, conv)
reply = asyncio.run(turn())
assert tool_results[0].startswith("今天 ") and "【今天的日程】" in tool_results[0] and "不要再用 offer_on_home 重复放" in tool_results[0]
types = [x["type"] for x in reply.blocks]
assert "summary" in types and types[-1] == "text", types
assert next(x for x in reply.blocks if x["type"] == "summary")["title"] == SUMMARY["title"]

# --- 空的一天 ---
async def wipe_and_call():
    async with SessionLocal() as db:
        for m in (ScheduledTask, HomeCard, Memory):
            for row in (await db.scalars(__import__("sqlalchemy").select(m))).all():
                await db.delete(row)
        await db.commit()
        return (await REGISTRY["day_overview"].run(ToolContext(db=db))).content
out = asyncio.run(wipe_and_call())
assert "- 今天没有排定的任务" in out and "别编造日程" in out and "未读 0 条" in out, out
print("smoke_day_brief OK")
