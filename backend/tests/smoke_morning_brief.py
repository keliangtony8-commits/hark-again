# 冒烟：v1.05 早间简报做成定时任务——worker 跑任务时把 task_id 交给工具（ToolContext.task_id），
# day_overview 不把正在跑的简报任务自己列进“今天的日程”、不把它昨天的报告卡当未读提醒，并注明“用户不在，不要提问”；
# 它的失败提醒卡（action）照样列；别的任务照常列；结果作为报告卡进 Home 收件箱（旧的那张收起）。
# 聊天里（无 task_id）一切照旧。模拟模型，无迁移（ToolContext 是内存里的）。
# 运行：python tests/smoke_morning_brief.py
import os, sys, asyncio, subprocess, tempfile, json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from sqlalchemy import select
from app import llm, worker
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import HomeCard, ScheduledTask

now = datetime.now(timezone.utc)
script: list = []
tool_results: list[str] = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    if messages and messages[-1]["role"] == "tool":
        tool_results.append(messages[-1]["content"])
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

# 一个每天都跑的简报任务（cron 每分钟 → 今天一定有它的时刻）+ 一个别的报告任务 + 简报昨天的未读报告 + 它的失败提醒
async def seed() -> str:
    async with SessionLocal() as db:
        brief = ScheduledTask(name="早间简报", prompt="帮我准备今天", cron="* * * * *")
        other = ScheduledTask(name="背单词", prompt="p", cron="* * * * *")
        db.add_all([brief, other]); await db.flush()
        db.add_all([
            HomeCard(kind="report", title="早间简报", task_id=brief.id, unread=True, blocks=text_to_blocks("昨天的简报")),
            HomeCard(kind="report", title="背单词", task_id=other.id, unread=True, blocks=text_to_blocks("10 个词")),
            HomeCard(kind="action", title="「早间简报」上次没跑成", task_id=brief.id, alert_subject=f"task:{brief.id}",
                     target="tasks", blocks=text_to_blocks("模型超时")),
        ])
        await db.commit()
        return brief.id
brief_id = asyncio.run(seed())

SUMMARY = {"title": "今天 · 简报", "markdown": "**时间线**\n- 背单词"}
script.extend([("day_overview", {}), ("show_summary", SUMMARY), "今天先背单词。"])
asyncio.run(worker.run_task(brief_id))
out = tool_results[0]
agenda = out.split("【今天的日程】")[1].split("【主页")[0]
assert "「背单词」" in agenda and "早间简报" not in agenda, agenda          # 不把自己当今天的一件事
inbox = out.split("【收件箱】")[1].split("【记忆")[0]
assert "未读 1 条" in inbox and "「背单词」" in inbox and "早间简报" not in inbox, inbox  # 自己昨天的报告不算
assert "上次没跑成" in out                                                # 自己的失败提醒照样要说
assert "用户不在：不要提问" in out and "Home 收件箱" in out, out

async def delivered():
    async with SessionLocal() as db:
        cards = (await db.scalars(select(HomeCard).where(HomeCard.task_id == brief_id, HomeCard.kind == "report"))).all()
        task = await db.get(ScheduledTask, brief_id)
        return cards, task
cards, task = asyncio.run(delivered())
live = [c for c in cards if not c.dismissed]
assert len(live) == 1 and live[0].unread and any(b["type"] == "summary" for b in live[0].blocks), [c.blocks for c in cards]
assert task.last_status == "ok", task.last_status

# 聊天里（没有 task_id）：简报任务和它的报告照常列，没有“用户不在”
async def chat_call():
    async with SessionLocal() as db:
        return (await REGISTRY["day_overview"].run(ToolContext(db=db))).content
chat = asyncio.run(chat_call())
assert "「早间简报」" in chat.split("【主页")[0] and "用户不在" not in chat, chat
print("smoke_morning_brief OK")
