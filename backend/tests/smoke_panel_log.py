# 冒烟：v2.55 BRAIN (bg) 记录面板 panel_log——app/panel_log.py 唯一规则 + 工具 + worker 不调模型重算 + 移除 / 找回 / 删除。迁移 0057。
# 1) 规则：clean（空 / 太长 / 非数字 / 无穷 / 单位太长；没数量丢单位）、when（日期 = 当天中午、未来 / 一年前拒）、_streak、_qty；
# 2) 工具 add：没面板 + 没 title → 提示；title 新建 + 记一笔 → 回执有今天合计 / 连续 / id，卡上 stats + 表；
#    同名（不分大小写空白）复用；数量不带单位沿用上一笔；一直记数量的面板这次没给 → 不记、让先问；坏参数不建空面板；
#    两个面板不给 id/title → 列出来；按卡片 id 找；
# 3) remove last / 按 id；list 带 id；manage_home list 标“记录面板”、read 带最近几笔、update prompt 拒、title 可改；
# 4) worker.run_task：不调模型（llm 被换成抛错的假函数）、运行记录 ok、“今天”翻篇后卡上今天归零；
# 5) panel_trash 移除 → 笔留着；revive → kind=log + 笔接到新任务；purge 过期 → 笔删掉；task_store.remove → 笔删掉；
# 6) 接口建 kind=log 任务 → 422（只在聊天里建）；
# 7) 一轮（模拟模型）：panel_log add → 回复“记下了…”不被 claimed_action 拦。
# 运行：python tests/smoke_panel_log.py
import os, sys, asyncio, subprocess, tempfile, json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from cryptography.fernet import Fernet
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY=Fernet.generate_key().decode(), DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from sqlalchemy import select, func
from app import llm, panel_log as P, panel_trash, script_tasks, task_store
from app.agent.runner import run_turn
from app.agent.tools import REGISTRY, ToolContext, load_builtin, nobody
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, HomeCard, Message, PanelEntry, ScheduledTask, TaskRun

load_builtin()
tool = REGISTRY["panel_log"]
home = REGISTRY["manage_home"]
assert not getattr(tool, "deferred", False), "记录是高频动作，直接给"

# ---- 1) 纯规则 ----
for bad in [("", 1, None), ("x" * 201, None, None), ("跑", "五", None), ("跑", float("inf"), None), ("跑", 1, "u" * 17)]:
    try:
        P.clean(*bad); raise AssertionError(bad)
    except P.LogError:
        pass
assert P.clean("  晨跑 \n 河边 ", 5, "公里") == ("晨跑 河边", 5.0, "公里")
assert P.clean("喝水", None, "毫升") == ("喝水", None, None)
now = datetime(2026, 10, 14, 4, 0, tzinfo=timezone.utc)  # 上海 12:00
assert P.when(None, now) == now
assert P.when("2026-10-13", now) == datetime(2026, 10, 13, 4, 0, tzinfo=timezone.utc)
assert P.when("2026-10-14 07:30", now) == datetime(2026, 10, 13, 23, 30, tzinfo=timezone.utc)
for bad in ["2026-10-15", "2025-01-01", "昨天"]:
    try:
        P.when(bad, now); raise AssertionError(bad)
    except P.LogError:
        pass
d = now.date()
assert P._streak({d, d - timedelta(1), d - timedelta(2)}, d) == 3
assert P._streak({d - timedelta(1), d - timedelta(2)}, d) == 2  # 今天还没记：从昨天数
assert P._streak({d - timedelta(3)}, d) == 0
assert P._qty(5.0, "公里") == "5 公里" and P._qty(18.5, "¥") == "¥18.5" and P._qty(None, "x") == "—" and P._qty(2.256, "") == "2.26"


async def main():
    async with SessionLocal() as db:
        ctx = ToolContext(db=db, ask=nobody)
        # ---- 2) add ----
        res = await tool.run(ctx, action="add", text="晨跑")
        assert "给 title" in res.content, res.content
        res = await tool.run(ctx, action="add", title="跑步", text="", amount=5)
        assert "text 不能空" in res.content
        assert await db.scalar(select(func.count()).select_from(ScheduledTask)) == 0, "坏参数不建空面板"
        res = await tool.run(ctx, action="add", title="跑步", text="晨跑", amount=5, unit="公里")
        assert "已记到「跑步」" in res.content and "今天合计 5 公里" in res.content and "连续 1 天" in res.content and "id=" in res.content, res.content
        run_task = await db.scalar(select(ScheduledTask).where(ScheduledTask.kind == "log"))
        assert run_task.output == "panel" and run_task.cron == P.CRON
        card = await db.scalar(select(HomeCard).where(HomeCard.task_id == run_task.id))
        assert card.kind == "panel" and card.title == "跑步"
        kinds = [b["type"] for b in card.blocks]
        assert kinds == ["stats", "table"], card.blocks
        assert card.blocks[0]["items"][0] == {"label": "今天", "value": "5 公里"}, card.blocks[0]
        # 同名复用（大小写 / 空白）+ 沿用单位
        res = await tool.run(ctx, action="add", title=" 跑 步 ", text="夜跑", amount=3)
        assert "今天合计 8 公里" in res.content, res.content
        assert await db.scalar(select(func.count()).select_from(ScheduledTask)) == 1
        # 一直记数量，这次没给 → 不记，先问
        res = await tool.run(ctx, action="add", title="跑步", text="又跑了")
        assert "先问用户这次是多少" in res.content and "公里" in res.content, res.content
        assert await P.count(db, run_task.id) == 2
        # 昨天的一笔 → 连续 2 天
        y = (datetime.now(timezone.utc) + timedelta(hours=8) - timedelta(days=1)).strftime("%Y-%m-%d")
        res = await tool.run(ctx, action="add", title="跑步", text="补记", amount=4, at=y)
        assert "连续 2 天" in res.content and "今天合计 8 公里" in res.content, res.content
        # 第二个面板（没数量）
        res = await tool.run(ctx, action="add", title="喝咖啡", text="拿铁")
        assert "今天第 1 笔" in res.content, res.content
        card2 = await db.scalar(select(HomeCard).where(HomeCard.title == "喝咖啡"))
        assert card2.blocks[0]["items"][0] == {"label": "今天", "value": "1 笔"}, card2.blocks
        res = await tool.run(ctx, action="list")
        assert "好几个记录面板" in res.content and "跑步" in res.content and "喝咖啡" in res.content, res.content
        res = await tool.run(ctx, action="list", id=card.id)
        assert "「跑步」" in res.content and res.content.count("- id=") == 3, res.content

        # ---- 3) remove / manage_home ----
        res = await tool.run(ctx, action="remove", title="跑步", entry="last")
        assert "补记" in res.content and "共 2 笔" in res.content, res.content
        first = (await db.scalars(select(PanelEntry).where(PanelEntry.task_id == run_task.id, PanelEntry.text == "晨跑"))).one()
        res = await tool.run(ctx, action="remove", title="跑步", entry=first.id)
        assert "晨跑" in res.content
        res = await tool.run(ctx, action="remove", title="跑步", entry="nope")
        assert "没有这一笔" in res.content
        await db.refresh(card)
        assert card.blocks[0]["items"][0]["value"] == "3 公里", card.blocks
        lst = (await home.run(ctx, action="list")).content
        assert "记录面板" in lst and "panel_log" in lst, lst
        rd = (await home.run(ctx, action="read", id=card.id)).content
        assert "夜跑" in rd and "- id=" in rd, rd
        assert "只能改 title" in (await home.run(ctx, action="update", id=card.id, prompt="查天气")).content
        assert "已" in (await home.run(ctx, action="update", id=card.id, title="跑步记录")).content
        await db.refresh(card)
        assert card.title == "跑步记录"
        return run_task.id, card.id, card2.id

tid, cid, cid2 = asyncio.run(main())

# ---- 4) worker：不调模型，翻篇 ----
async def boom(*a, **k):
    raise AssertionError("记录面板刷新不该调模型")
llm.client.chat.completions.create = boom
from app import worker
async def rollover():
    async with SessionLocal() as db:  # 把所有笔挪到两天前：今天归零、连续断掉
        for e in (await db.scalars(select(PanelEntry).where(PanelEntry.task_id == tid))).all():
            e.at = e.at - timedelta(days=2)
        t = await db.get(ScheduledTask, tid)
        t.run_requested = True
        await db.commit()
    await worker.run_task(tid)
    async with SessionLocal() as db:
        card = await db.get(HomeCard, cid)
        assert card.blocks[0]["items"][0] == {"label": "今天", "value": "0 公里"}, card.blocks
        stats = {i["label"]: i["value"] for i in card.blocks[0]["items"]}
        assert stats["连续"] == "0 天" and stats["近 7 天"] == "3 公里", stats
        run = await db.scalar(select(TaskRun).where(TaskRun.task_id == tid))
        assert run.status == "ok" and run.conversation_id is None
        t = await db.get(ScheduledTask, tid)
        assert t.run_requested is False and t.last_status == "ok"
        assert await db.scalar(select(func.count()).select_from(Conversation)) == 0
asyncio.run(rollover())

# ---- 5) 移除 / 找回 / 过期 / 删除 ----
async def trash():
    async with SessionLocal() as db:
        card = await db.get(HomeCard, cid)
        await panel_trash.remove(db, card)
        assert await db.get(ScheduledTask, tid) is None
        assert await P.count(db, tid) == 1, "移除时笔留着"
        card, task = await panel_trash.revive(db, cid)
        assert task.kind == "log" and task.id != tid
        assert await P.count(db, task.id) == 1 and await P.count(db, tid) == 0
        # 过期清掉
        await panel_trash.remove(db, card)
        card.removed_at = datetime.now(timezone.utc) - timedelta(days=40)
        await db.commit()
        assert await panel_trash.purge(db) == 1
        assert await db.scalar(select(func.count()).select_from(PanelEntry).where(PanelEntry.text == "夜跑")) == 0
        # 任务直接删
        c2 = await db.get(HomeCard, cid2)
        t2 = await db.get(ScheduledTask, c2.task_id)
        assert await P.count(db, t2.id) == 1
        await task_store.remove(db, t2)
        assert await db.scalar(select(func.count()).select_from(PanelEntry)) == 0
asyncio.run(trash())

# ---- 6) 接口规则 ----
try:
    script_tasks.check("log", "x", None); raise AssertionError("log 只在聊天里建")
except ValueError as e:
    assert "聊天里" in str(e)
script_tasks.check("log", "x", None, "panel")

# ---- 7) 一轮（模拟模型）----
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
            yield chunk(tool=[NS(index=i, id=f"p{len(script)}-{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
async def seed():
    async with SessionLocal() as db:
        c = Conversation(title="t")
        db.add(c)
        await db.flush()
        db.add(Message(conversation_id=c.id, role="user", blocks=text_to_blocks("记一下，今天喝了 300 毫升水")))
        await db.commit()
        return c.id
conv = asyncio.run(seed())
async def _ask(_id, _form):
    return None
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, conv), emit=lambda ev: asyncio.sleep(0), ask=_ask)
script.extend([[("panel_log", {"action": "add", "title": "喝水", "text": "喝水", "amount": 300, "unit": "毫升"})],
               "记下了，今天合计 300 毫升。"])
reply = asyncio.run(turn())
assert "panel_log" in seen[0]["tools"], seen[0]["tools"]
assert not script, "不该被 claimed_action 拦（多一次调用会把 script 用光报错）"
assert [(x["tool"], x["state"]) for x in reply.steps] == [("panel_log", "done")], reply.steps
tool_msgs = [m for m in seen[1]["messages"] if m.get("role") == "tool"]
assert "今天合计 300 毫升" in str(tool_msgs[-1]["content"]), tool_msgs
print("smoke_panel_log ok")
