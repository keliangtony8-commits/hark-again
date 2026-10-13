# 冒烟（v2.31，E2E B7）：定时任务自己运行时不能改计划（app/task_brief.fire_refusal 唯一规则，模拟模型）。
# 复现原 bug：喝水提醒运行里 schedule_task update cron → 现在被拒、cron 不变；run_now / skip / 删别的 / 面板 update·refresh·移除·找回 拒；
# list / runs / set_runbook / note / create / cancel 自己 允许；聊天里（无 task_id）一切照旧；brief 里有这条规矩。
# 运行：python tests/smoke_fire_plan.py
import os, sys, asyncio, subprocess, tempfile
from datetime import datetime, timedelta, timezone
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from app import task_brief, worker
from app.agent.tools import ToolContext, load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import HomeCard, ScheduledTask

load_builtin()
from app.agent.builtin.tasks import schedule_task
from app.agent.builtin.home import manage_home

# 纯规则
R = task_brief.fire_refusal
assert R(None, "update") is None and R(None, "cancel", "x") is None, "聊天里不管"
for a in ("list", "runs", "read", "set_runbook", "note", "report_wall", "create", "snooze", "dismiss"):
    assert R("me", a) is None, a
for a in ("update", "run_now", "skip_next", "unskip", "refresh", "revive"):
    assert R("me", a, "me") == task_brief.FIRE_REFUSED, a
assert R("me", "cancel") is None and R("me", "cancel", "me") is None and R("me", "cancel", "other")
assert R("me", "dismiss", "p", removes_task=True)

class Reply:
    def __init__(self, text): self.blocks = text_to_blocks(text)

seen, out = [], {}

async def seed():
    async with SessionLocal() as db:
        water = ScheduledTask(name="喝水提醒", prompt="提醒我：喝一杯水", cron="0 8 * * *")
        other = ScheduledTask(name="机票盯价", prompt="看看机票价格", cron="0 9 * * *")
        panel = ScheduledTask(name="汇率面板", prompt="美元汇率", cron="0 * * * *", output="panel")
        db.add_all([water, other, panel]); await db.commit()
        card = HomeCard(kind="panel", title="汇率", task_id=panel.id, blocks=[])
        db.add(card); await db.commit()
        return water.id, other.id, panel.id, card.id

wid, oid, pid, cid = asyncio.run(seed())

async def fire(db, conv, emit=None, task_id=None, brief=None, **kw):
    seen.append(brief)
    ctx = ToolContext(db=db, task_id=task_id)
    st = lambda **a: schedule_task(ctx, **a)
    out["update"] = (await st(action="update", cron="0 8,10,12,14,16,18,20 * * *", notify="always")).content
    out["update_other"] = (await st(action="update", id=oid, active=False)).content
    out["run_now"] = (await st(action="run_now", id=oid)).content
    out["skip"] = (await st(action="skip_next", id=wid)).content
    out["cancel_other"] = (await st(action="cancel", id=oid)).content
    out["list"] = (await st(action="list")).content
    out["note"] = (await st(action="note", text="用户只要一句话")).content
    out["create"] = (await st(action="create", name="明早再提醒", prompt="提醒我：喝水", run_at=(datetime.now() + timedelta(hours=20)).strftime("%Y-%m-%d %H:%M"))).content
    mh = lambda **a: manage_home(ctx, **a)
    out["p_update"] = (await mh(action="update", id=cid, cron="*/5 * * * *")).content
    out["p_refresh"] = (await mh(action="refresh", id=cid)).content
    out["p_dismiss"] = (await mh(action="dismiss", id=cid)).content
    out["p_revive"] = (await mh(action="revive", id=cid)).content
    out["p_read"] = (await mh(action="read", id=cid)).content
    return Reply("该喝水了，来一杯。")

worker.run_turn = fire
asyncio.run(worker.run_task(wid))

for k in ("update", "update_other", "run_now", "skip", "cancel_other", "p_update", "p_refresh", "p_dismiss", "p_revive"):
    assert out[k] == task_brief.FIRE_REFUSED, (k, out[k])
assert "喝水提醒" in out["list"] and "已记下" in out["note"] and "已安排" in out["create"] and "汇率" in out["p_read"], out
assert "计划" in seen[-1] and "不要改任何任务" in seen[-1], seen[-1]

async def check():
    async with SessionLocal() as db:
        w, o, p = [await db.get(ScheduledTask, x) for x in (wid, oid, pid)]
        c = await db.get(HomeCard, cid)
        assert w.cron == "0 8 * * *" and w.skip_at is None and w.note == "用户只要一句话", (w.cron, w.skip_at)
        assert o is not None and o.active and not o.run_requested
        assert p is not None and p.cron == "0 * * * *" and c is not None and c.removed_at is None
asyncio.run(check())

# 指令要求时可以结束自己（cancel 不给 id）
async def end_self(db, conv, emit=None, task_id=None, brief=None, **kw):
    out["self"] = (await schedule_task(ToolContext(db=db, task_id=task_id), action="cancel")).content
    return Reply("降价了，任务已结束。")
worker.run_turn = end_self
asyncio.run(worker.run_task(oid))
assert "已结束「机票盯价」" in out["self"], out["self"]
async def ended():
    async with SessionLocal() as db:
        o = await db.get(ScheduledTask, oid)
        assert o is not None and not o.active and o.paused_reason == task_brief.ENDED and o.last_status == "ok", "停用不删，这次照常交付"
        r = (await schedule_task(ToolContext(db=db), action="list")).content
        assert "已按指令结束" in r, r
asyncio.run(ended())

# 聊天里照旧能改
async def chat():
    async with SessionLocal() as db:
        r = (await schedule_task(ToolContext(db=db), action="update", id=wid, cron="0 9 * * *")).content
        assert "已更新" in r, r
        assert (await db.get(ScheduledTask, wid)).cron == "0 9 * * *"
asyncio.run(chat())
print("smoke_fire_plan OK")
