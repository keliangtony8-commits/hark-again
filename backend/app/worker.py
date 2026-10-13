"""后台 worker：跑定时任务。独立进程（compose 里的 worker 服务），不占用聊天进程。

每 POLL 秒检查一次：到点的或被点了“立即运行”的任务 → 新建一段对话执行 → 按 task.output 投递：
- report：作为卡片放进 Home 收件箱（同一任务只保留最新一张），对话保留，点开可追问；
  碰到登录 / 连接器 / 付费墙这类壁时助手用 report_wall 记下：这次算失败，原因是那堵壁，面板保留旧内容（app/task_wall.py）；
  回复以 [[SILENT]] 开头 = 这次没东西可报，不发卡，运行记录写原因（app/task_brief.py；每次开头读到做法 / 观察 / 最近几次）
- panel：原地更新面板卡的内容，执行用的对话随即删除（面板每小时刷新，不能把聊天列表刷满）
kind=log 的记录面板也不调模型：到点按记下的笔重算（app/panel_log.py）。
kind=script 的定时脚本不调模型：到点当后台任务跑命令，结束后按 notify 决定告不告诉用户（app/script_tasks.py）。
顺带叫醒“稍后提醒”到点的 Home 卡片（app/card_snooze.py），并照看项目沙盒里的后台任务（app/jobs.py：结束了就在原对话里接着说一轮）。
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
from . import task_brief, task_wall, card_snooze, panel_log, panel_trash, job_memory, jobs, report_gist, script_tasks, task_runs, task_store, turn_journal
from .db import SessionLocal
from .models import Conversation, HomeCard, Message, ScheduledTask
from .schedule import is_due  # 与接口的 next_run_at 共用同一套时刻计算

POLL = 5  # 后台任务结束后要尽快在对话里接着说；查询本身很轻
log = logging.getLogger("worker")


PANEL_STYLE = ("【这是 Home 面板的刷新】只输出面板内容本身：一眼能看完，优先用表格或三五行要点，"
               "标出变化（↑↓、新增），不要寒暄、不要提问。几个一眼要看的数字（气温、价格、数量）用 show_stats 展示。\n\n")


async def _deliver_report(db, task: ScheduledTask, conv: Conversation, blocks: list[dict]) -> None:
    # 只收起旧报告；失败提醒卡（action）由 task_runs 管，不能被下一份报告顺手收掉
    await db.execute(update(HomeCard).where(HomeCard.task_id == task.id, HomeCard.kind == "report")
                     .values(dismissed=True))
    blocks = blocks or text_to_blocks("这次没有跑成功，稍后会按计划再试。")
    headline, line = report_gist.gist(blocks)  # 收件箱行和横幅上的“一眼”
    db.add(HomeCard(kind="report", title=task.name, conversation_id=conv.id, task_id=task.id, unread=True,
                    blocks=blocks, headline=headline, gist=line))


async def _deliver_panel(db, task: ScheduledTask, conv: Conversation, blocks: list[dict], walled: bool = False) -> None:
    card = await db.scalar(select(HomeCard).where(HomeCard.task_id == task.id, HomeCard.kind == "panel"))
    if card is None:  # 面板被用户删了卡但任务还在：补一张
        card = HomeCard(kind="panel", title=task.name, task_id=task.id, blocks=[])
        db.add(card)
    if blocks and not (walled and card.blocks):  # 失败 / 碰壁时保留上一次的内容，比空白或“登录不了”有用
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
        if script_tasks.is_script(task):  # 定时脚本：起后台任务就走，结束时 tick 里 settle_ready 收尾
            await script_tasks.launch(db, task)
            return
        if panel_log.is_log(task):  # 记录面板：按记下的每一笔重算，不调模型（app/panel_log.py）
            await panel_log.run(db, task)
            return
        now = datetime.now(timezone.utc)
        run = await task_runs.start(db, task, now)
        task.last_run_at, task.run_requested = now, False
        local = now.astimezone(ZoneInfo(settings.timezone))
        panel = task.output == "panel"
        conv = task_store.conversation_for(task, f"面板 · {task.name}" if panel else f"{task.name} · {local:%m月%d日 %H:%M}")
        db.add(conv)
        await db.flush()
        db.add(Message(conversation_id=conv.id, role="user",
                       blocks=text_to_blocks((PANEL_STYLE if panel else "") + task.prompt)))
        brief = await task_brief.preface_for(db, task)  # 在这次提交之前查：之后的事务里只有模型这一轮（崩了回滚不殃及 task/run）
        await db.commit()

        errors: list[str] = []

        async def emit(ev: dict) -> None:  # 无人在看，只留下错误事件当失败原因
            if ev.get("type") == "error":
                errors.append(str(ev.get("message") or "未知错误"))

        blocks: list[dict] = []
        try:
            reply = await run_turn(db, conv, emit=emit, task_id=task.id, brief=brief)
            blocks = reply.blocks if reply else []
        except Exception as e:  # 工具/库的意外异常：记成失败原因，照常投递和收尾
            log.exception("task %s crashed", task.name)
            await db.rollback()
            errors.append(f"{type(e).__name__}: {e}")
        for row in (run, task):  # report_wall 在模型这一轮里写过它们（已提交）；崩了回滚后也要重新载入
            await db.refresh(row)
        walled = task_wall.settle(task, run)  # 报了壁 = 这次算失败（原因是壁）；没报 = 清掉旧壁（task_wall.py）
        error = walled or (errors[-1] if errors else (None if blocks else task_runs.NO_OUTPUT))
        quiet = None if (panel or error) else task_brief.silent(blocks)  # 没东西可报：不进收件箱（task_brief.py）
        if panel:
            await _deliver_panel(db, task, conv, blocks, walled=walled is not None)
        elif quiet is None:
            await _deliver_report(db, task, conv, blocks)
        run.silent_reason = quiet
        await db.commit()
        await task_runs.finish(db, task, run, error, None if panel else conv.id)
        log.info("task %s (%s) %s", task.name, task.output, "failed: " + error if error else "done")


async def tick() -> None:
    now = datetime.now(timezone.utc)
    async with SessionLocal() as db:
        if n := await card_snooze.wake_due(db, now):  # 稍后提醒到点的卡放回 Home
            log.info("woke %d snoozed cards", n)
        if n := await panel_trash.purge(db, now):  # 移除超过 30 天的面板彻底删掉
            log.info("purged %d removed panels", n)
        tasks = (await db.scalars(select(ScheduledTask).where(
            or_(ScheduledTask.active.is_(True), ScheduledTask.run_requested.is_(True))))).all()
        due = [t.id for t in tasks if is_due(t, now)]
    async with SessionLocal() as db:  # 后台任务：对一遍现状，结束的在原对话里接着说一轮
        try:
            if done := await jobs.tick(db):
                log.info("jobs settled: %s", ", ".join(done))
            if capped := await job_memory.tick(db):  # v1.92 采样记峰值；超过自己内存上限的结束掉
                log.info("jobs over memory limit: %s", ", ".join(capped))
            if scripts := await script_tasks.settle_ready(db):  # 定时脚本的后台任务结束了：记结果、按 notify 告诉用户
                log.info("script tasks settled: %s", ", ".join(scripts))
            await jobs.follow_ups(db)
        except Exception:
            log.exception("job follow-up failed")
    for tid in due:  # 顺序执行，避免同时打多个模型请求
        try:
            await run_task(tid)
        except Exception:
            log.exception("task %s failed", tid)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    load_builtin()
    await turn_journal.recover_all("worker")  # 上次被杀时没答完的任务/跟进回答 → interrupted 消息
    async with SessionLocal() as db:
        if n := await task_runs.recover_stale(db):
            log.warning("marked %d interrupted task runs as failed", n)
    while True:
        await tick()
        await asyncio.sleep(POLL)


if __name__ == "__main__":
    asyncio.run(main())
