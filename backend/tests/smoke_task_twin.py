# 冒烟（v2.41，E2E B14）：同一件事不会被 schedule_task create 两次；给助手任务传 notify 会明说“没用上”。
# 规则：task_store.twin（同类型 + 同计划 + 同内容、还会再跑、报告类 → 同一个；名字不看）；script_tasks.notify_ignored。
# 模拟模型复现 g5：create 成功 → 想加 notify=always 又 create 一遍 → 拿到“已经安排过了 id=…” → 库里只有一条。
# 运行：python tests/smoke_task_twin.py
import os, sys, json, asyncio, subprocess, tempfile
from types import SimpleNamespace as NS
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", TIMEZONE="Asia/Shanghai",
  WORKSPACES_DIR=tempfile.mkdtemp())
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select
from app import llm, script_tasks, task_store
from app.agent.runner import run_turn
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message, Project, ScheduledTask
load_builtin()
tool = REGISTRY["schedule_task"]
AT = (datetime.now(timezone.utc) + timedelta(days=3)).astimezone().strftime("%Y-%m-%d") + " 15:00"

async def call(**kw):
    async with SessionLocal() as db:
        return (await tool.run(ToolContext(db=db), **kw)).content

async def count():
    async with SessionLocal() as db:
        return await db.scalar(select(func.count()).select_from(ScheduledTask))

# 1) 规则本身
assert script_tasks.notify_ignored("agent", "always") == script_tasks.AGENT_NOTIFY_NOTE
assert script_tasks.notify_ignored(None, "failure")
assert script_tasks.notify_ignored("script", "always") is None and script_tasks.notify_ignored("agent", None) is None

# 2) 工具：一次性提醒
r1 = asyncio.run(call(action="create", name="交实验报告", prompt="提醒我：交实验报告", run_at=AT))
assert r1.startswith("已安排") and "notify" not in r1, r1
tid = asyncio.run(call(action="list")).split("id=")[1].split("「")[0]
r2 = asyncio.run(call(action="create", name="实验报告提醒", prompt="  提醒我：交实验报告。 \n", run_at=AT, notify="always"))
assert "已经安排过了" in r2 and f"update id={tid}" in r2 and "notify 只对定时脚本" in r2, r2
assert asyncio.run(count()) == 1
# 不同时间 / 不同内容 → 照建
assert asyncio.run(call(action="create", name="交实验报告", prompt="提醒我：交实验报告", run_at=AT.replace("15:00", "16:00"))).startswith("已安排")
assert asyncio.run(call(action="create", name="交实验报告", prompt="提醒我：交实验报告和预习", run_at=AT)).startswith("已安排")
assert asyncio.run(count()) == 3
# 新建时带 notify：建好，但明说没用上
r3 = asyncio.run(call(action="create", name="早报", prompt="给我今天的早报", cron="0 8 * * *", notify="always"))
assert r3.startswith("已安排") and "notify 只对定时脚本" in r3, r3
assert "已经安排过了" in asyncio.run(call(action="create", name="早报2", prompt="给我今天的早报", cron="0  8 * * *"))
assert asyncio.run(call(action="create", name="早报", prompt="给我今天的早报", cron="0 9 * * *")).startswith("已安排")
# 暂停的 / 已经跑过的一次性 → 不算（可以重新建）
async def deactivate():
    async with SessionLocal() as db:
        t = await db.get(ScheduledTask, tid); t.active = False; await db.commit()
asyncio.run(deactivate())
assert asyncio.run(call(action="create", name="交实验报告", prompt="提醒我：交实验报告", run_at=AT)).startswith("已安排")
# update 只传 notify 给助手任务 → 没改动 + 原因；连带改名 → 改名生效 + 原因，notify 不写
r4 = asyncio.run(call(action="update", id=tid, notify="always"))
assert r4.startswith("没改动") and "notify 只对定时脚本" in r4, r4
r5 = asyncio.run(call(action="update", id=tid, name="交报告", notify="change"))
assert r5.startswith("已更新") and "「交报告」" in r5 and "notify 只对定时脚本" in r5, r5
async def notify_of(i):
    async with SessionLocal() as db:
        return (await db.get(ScheduledTask, i)).notify
assert asyncio.run(notify_of(tid)) == "failure"

# 3) 脚本：同项目同命令同计划 → 同一个；别的项目 → 不同
async def projects():
    async with SessionLocal() as db:
        a, b = Project(name="a", emoji="a"), Project(name="b", emoji="b"); db.add_all([a, b]); await db.commit()
        return a.id, b.id
pa, pb = asyncio.run(projects())
async def call_in(pid, **kw):
    async with SessionLocal() as db:
        return (await tool.run(ToolContext(db=db, project_id=pid), **kw)).content
assert asyncio.run(call_in(pa, action="create", name="备份", command="tar czf b.tgz docs", cron="0 2 * * *")).startswith("已安排")
r6 = asyncio.run(call_in(pa, action="create", name="备份", command="tar czf b.tgz docs", cron="0 2 * * *", notify="always"))
assert "已经安排过了" in r6 and "notify 只对定时脚本" not in r6, r6
assert asyncio.run(call_in(pb, action="create", name="备份", command="tar czf b.tgz docs", cron="0 2 * * *")).startswith("已安排")
async def twin_direct():
    async with SessionLocal() as db:
        assert await task_store.twin(db, prompt="tar czf b.tgz docs", cron="0 2 * * *", kind="script", project_id=pa)
        assert await task_store.twin(db, prompt="tar czf b.tgz docs", cron="0 2 * * *", kind="agent") is None
asyncio.run(twin_direct())

# 4) 模拟模型：g5 的路线
async def seed():
    async with SessionLocal() as db:
        conv = Conversation(title="t"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("下周五下午 3 点提醒我交物理实验报告")))
        await db.commit(); return conv.id
cid = asyncio.run(seed())
seen, script = [], []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append([dict(m) for m in messages])
    step = script.pop(0)
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"c{len(script)}-{i}", function=NS(name=n, arguments=json.dumps(a)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
FRI = AT.replace("15:00", "15:00")
spec = {"action": "create", "name": "物理实验报告", "prompt": "提醒我：交物理实验报告", "run_at": FRI}
script.extend([[("schedule_task", spec)], [("schedule_task", {**spec, "notify": "always"})], "好了，到点提醒你。"])
before = asyncio.run(count())
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))
reply = asyncio.run(turn())
tools_out = [m["content"] for m in seen[2] if m["role"] == "tool"]
assert tools_out[0].startswith("已安排") and "已经安排过了" in tools_out[1] and "notify 只对定时脚本" in tools_out[1], tools_out
assert asyncio.run(count()) == before + 1
print("smoke_task_twin OK")
