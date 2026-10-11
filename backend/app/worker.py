"""后台 worker：跑定时任务。独立进程（compose 里的 worker 服务），不占用聊天进程。

每 POLL 秒检查一次：到点的或被点了“立即运行”的任务 → 新建一段对话执行 → 按 task.output 投递：
- report：作为卡片放进 Home 收件箱（同一任务只保留最新一张），对话保留，点开可追问
- panel：原地更新面板卡的内容，执行用的对话随即删除（面板每小时刷新，不能把聊天列表刷满）
顺带叫醒“稍后提醒”到点的 Home 卡片（app/card_snooze.py）。
每次运行都记在 task_runs（成功/失败原因/耗时，首次失败在 Home 放提醒卡），见 app/task_runs.py。
无人值守，所以高风险操作一律拒绝（deny_all）。
单用户场景用 Postgres 当队列足够；需要多 worker 时再引入 Redis。
"""
import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, or_, select, update

from .agent.runner import run_turn
from .agent.tools import load_builtin
from .blocks import text_to_blocks
from .config import settings
from . import card_snooze, task_runs
from .db import SessionLocal
from .models import Conversation, HomeCard, Message, ScheduledTask
from .schedule import is_due  # 与接口的 next_run_at 共用同一套时刻计算

POLL = 15
log = logging.getLogger("worker")


PANEL_STYLE = ("【这是 Home 面板的刷新】只输出面板内容本身：一眼能看完，优先用表格或三五行要点，"
               "标出变化（↑↓、新增），不要寒暄、不要提问。几个一眼要看的数字（气温、价格、数量）用 show_stats 展示。\n\n")


async def _deliver_report(db, task: ScheduledTask, conv: Conversation, blocks: list[dict]) -> None:
    # 只收起旧报告；失败提醒卡（action）由 task_runs 管，不能被下一份报告顺手收掉
    await db.execute(update(HomeCard).where(HomeCard.task_id == task.id, HomeCard.kind == "report")
                     .values(dismissed=True))
    db.add(HomeCard(kind="report", title=task.name, conversation_id=conv.id, task_id=task.id, unread=True,
                    blocks=blocks or text_to_blocks("这次没有跑成功，稍后会按计划再试。")))


async def _deliver_panel(db, task: ScheduledTask, conv: Conversation, blocks: list[dict]) -> None:
    card = await db.scalar(select(HomeCard).where(HomeCard.task_id == task.id, HomeCard.kind == "panel"))
    if card is None:  # 面板被用户删了卡但任务还在：补一张
        card = HomeCard(kind="panel", title=task.name, task_id=task.id, blocks=[])
        db.add(card)
    if blocks:  # 失败时保留上一次的内容，比空白有用
        card.blocks = blocks
        card.updated_at = datetime.now(timezone.utc)
    await db.execute(delete(Message).where(Message.conversation_id == conv.id))
    await db.delete(conv)


async def run_task(task_id: str) -> None:
    """跑一次任务：开一条运行记录 → 新对话里跑 Agent → 按 output 投递 → 收尾记录（成功/失败原因、失败提醒）。"""
    async with SessionLocal() as db:
        task = await db.get(ScheduledTask, task_id)
        if task is None:
            return
        now = datetime.now(timezone.utc)
        run = await task_runs.start(db, task, now)
        task.last_run_at, task.run_requested = now, False
        local = now.astimezone(ZoneInfo(settings.timezone))
        panel = task.output == "panel"
        conv = Conversation(title=f"面板 · {task.name}" if panel else f"{task.name} · {local:%m月%d日 %H:%M}")
        db.add(conv)
        await db.flush()
        db.add(Message(conversation_id=conv.id, role="user",
                       blocks=text_to_blocks((PANEL_STYLE if panel else "") + task.prompt)))
        await db.commit()

        errors: list[str] = []

        async def emit(ev: dict) -> None:  # 无人在看，只留下错误事件当失败原因
            if ev.get("type") == "error":
                errors.append(str(ev.get("message") or "未知错误"))

        blocks: list[dict] = []
        try:
            reply = await run_turn(db, conv, emit=emit, task_id=task.id)
            blocks = reply.blocks if reply else []
        except Exception as e:  # 工具/库的意外异常：记成失败原因，照常投递和收尾
            log.exception("task %s crashed", task.name)
            await db.rollback()
            errors.append(f"{type(e).__name__}: {e}")
        error = errors[-1] if errors else (None if blocks else task_runs.NO_OUTPUT)
        if panel:
            await _deliver_panel(db, task, conv, blocks)
        else:
            await _deliver_report(db, task, conv, blocks)
        await db.commit()
        await task_runs.finish(db, task, run, error, None if panel else conv.id)
        log.info("task %s (%s) %s", task.name, task.output, "failed: " + error if error else "done")


async def tick() -> None:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        if n := await card_snooze.wake_due(db, now):  # 稍后提醒到点的卡放回 Home
            log.info("woke %d snoozed cards", n)
        tasks = (await db.scalars(select(ScheduledTask).where(
            or_(ScheduledTask.active.is_(True), ScheduledTask.run_requested.is_(True))))).all()
        due = [t.id for t in tasks if is_due(t, now)]
    for tid in due:  # 顺序执行，避免同时打多个模型请求
        try:
            await run_task(tid)
        except Exception:
            log.exception("task %s failed", tid)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    load_builtin()
    async with SessionLocal() as db:
        if n := await task_runs.recover_stale(db):
            log.warning("marked %d interrupted task runs as failed", n)
    while True:
        await tick()
        await asyncio.sleep(POLL)


if __name__ == "__main__":
    asyncio.run(main())
