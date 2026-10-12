"""定时任务的运行记录与失败提醒：worker 写、/api/tasks/{id}/runs 读，二者只经过这里。

一次运行 = task_runs 一行：start() 开头落一行 running（客户端能看到“正在运行”），finish() 收尾写
ok / error、错误原因、耗时、对话 id，并更新 scheduled_tasks.last_status（列表页一眼看到“上次失败”）。
每个任务只留最近 KEEP 条，旧的在 finish() 里顺手删。

失败提醒（走 system_alerts，去处 task:<id>）：
- 只在“连续失败的第一次”发卡（fail_streak 从 0 变 1：上次成功、从没跑过、或刚被重新启用）；接着失败不再打扰，卡上写的是第一次的原因；
- 卡挂在任务上（target="tasks" + task_id，客户端“查看任务”直达该任务详情），删任务时一起删；
- 下一次成功 → 收起这个任务的失败卡（恢复了就不该还挂着）。
连续失败升级（对标“连续失败自动暂停”）：fail_streak 记连着失败几次（成功归零；中断不算）。
- 重复任务连续失败 PAUSE_AFTER 次 → 自动暂停（active=False, paused_reason="failures"），
  同主体的首次失败卡被一张“已暂停”卡顶替（once="paused"），卡上直达任务、可交给助手分析；
- 用户在任务上重新启用（task_store.after_patch）或手动“立即运行”成功 → 恢复、归零、收起卡；
- 一次性任务跑一次就完，不涉及暂停。
worker 中途被杀会留下 running 行：recover_stale() 在 worker 启动时把它们标成 error（定时脚本的后台任务还在跑的除外）。"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import system_alerts
from .config import settings
from .models import Conversation, HomeCard, ScheduledTask, TaskRun
from .wire_time import iso

KEEP = 30
ERROR_MAX = 500
NO_OUTPUT = "没有产出内容"
INTERRUPTED = "运行被中断（后台进程重启）"
PAUSE_AFTER = 3
PAUSED_BY_FAILURES = "failures"


async def start(db: AsyncSession, task: ScheduledTask, now: datetime) -> TaskRun:
    run = TaskRun(task_id=task.id, trigger="manual" if task.run_requested else "schedule", status="running",
                  started_at=now)
    db.add(run)
    return run


async def finish(db: AsyncSession, task: ScheduledTask, run: TaskRun, error: str | None,
                 conversation_id: str | None, now: datetime | None = None) -> HomeCard | None:
    """收尾一条运行并提交；首次失败返回新放的提醒卡。"""
    now = now or datetime.now(timezone.utc)
    run.status = "error" if error else "ok"
    run.error = error[:ERROR_MAX] if error else None
    run.finished_at, run.conversation_id = now, conversation_id
    task.last_status = run.status
    await _prune(db, task.id)
    card = None
    if error is None:
        task.fail_streak = 0
        if task.paused_reason == PAUSED_BY_FAILURES:  # 暂停后手动试跑成功 = 修好了，按计划接着跑
            task.active, task.paused_reason = True, None
        await system_alerts.clear(db, f"task:{task.id}")
    else:
        task.fail_streak = (task.fail_streak or 0) + 1
        if task.fail_streak >= PAUSE_AFTER and task.cron and task.active:
            task.active, task.paused_reason = False, PAUSED_BY_FAILURES
            card = await _paused_alert(db, task, run)
        elif task.fail_streak == 1:
            card = await _alert(db, task, run, now)
    await db.commit()
    return card


async def _prune(db: AsyncSession, task_id: str) -> None:
    keep = select(TaskRun.id).where(TaskRun.task_id == task_id).order_by(TaskRun.started_at.desc()).limit(KEEP)
    await db.flush()
    await db.execute(delete(TaskRun).where(TaskRun.task_id == task_id, TaskRun.id.not_in(keep)))


async def _alert(db: AsyncSession, task: ScheduledTask, run: TaskRun, now: datetime) -> HomeCard | None:
    local = now.astimezone(ZoneInfo(settings.timezone))
    what = "面板没刷新成功，上面还是上一次的内容。" if task.output == "panel" else "这次的报告没有出来。"
    text = (f"{local:%m月%d日 %H:%M} 那次运行失败：{run.error}\n\n"
            f"{what}之后仍按计划重试；连着失败不会重复提醒，恢复后这张卡自动收起。")
    # 键含运行 id：同一次运行收尾两遍也只有一张
    return await system_alerts.post(
        db, subject=f"task:{task.id}", once=run.id, title=f"定时任务「{task.name}」没跑成功", text=text, open=f"task:{task.id}",
        prompt=(f"我的定时任务「{task.name}」刚才运行失败了，错误是：{run.error}。"
                f"它的提示词是：{task.prompt}。帮我看看原因，需要的话建议怎么改提示词或时间。"))


async def _paused_alert(db: AsyncSession, task: ScheduledTask, run: TaskRun) -> HomeCard | None:
    text = (f"已经连着失败 {task.fail_streak} 次，我先把它暂停了，免得一直白跑。最近一次的原因：{run.error}\n\n"
            "改好提示词或时间后在任务页重新启用；也可以先点“立即运行”试一次，成功了会自动恢复。")
    return await system_alerts.post(
        db, subject=f"task:{task.id}", once="paused", title=f"定时任务「{task.name}」连续失败，已暂停", text=text,
        open=f"task:{task.id}",
        prompt=(f"我的定时任务「{task.name}」连续失败了 {task.fail_streak} 次，已被自动暂停。最近的错误是：{run.error}。"
                f"它的提示词是：{task.prompt}。帮我找出原因，改好后再帮我重新启用。"))


async def resumed(db: AsyncSession, task: ScheduledTask) -> None:
    """用户（或智能体替用户）重新启用了一个因连续失败暂停的任务：归零并收起提醒（不 commit）。"""
    task.paused_reason, task.fail_streak = None, 0
    await system_alerts.clear(db, f"task:{task.id}")


async def recover_stale(db: AsyncSession, now: datetime | None = None) -> int:
    """worker 启动时调用：上次被杀时还在跑的运行一律算失败（不发提醒：不是任务本身的问题）。"""
    from .script_tasks import live_run_ids  # 定时脚本的后台任务在沙盒里接着跑：不算中断，结束时照常收尾
    now = now or datetime.now(timezone.utc)
    live = await live_run_ids(db)
    stale = [r for r in (await db.scalars(select(TaskRun).where(TaskRun.status == "running"))).all() if r.id not in live]
    for run in stale:
        run.status, run.error, run.finished_at = "error", INTERRUPTED, now
        task = await db.get(ScheduledTask, run.task_id)
        if task is not None:
            task.last_status = "error"
    await db.commit()
    return len(stale)


async def remove_for(db: AsyncSession, task_id: str) -> None:
    await db.execute(delete(TaskRun).where(TaskRun.task_id == task_id))


async def history(db: AsyncSession, task_id: str, limit: int = KEEP) -> list[dict]:
    """新的在前。对话已被删的 conversation_id 置 null（客户端据此决定能不能点开）。"""
    rows = (await db.execute(
        select(TaskRun, Conversation.id)
        .outerjoin(Conversation, Conversation.id == TaskRun.conversation_id)
        .where(TaskRun.task_id == task_id)
        .order_by(TaskRun.started_at.desc())
        .limit(limit)
    )).all()
    return [_wire(run, conv_id) for run, conv_id in rows]


_iso = iso


def _wire(run: TaskRun, conversation_id: str | None) -> dict:
    duration = None
    if run.finished_at is not None:
        a = run.started_at if run.started_at.tzinfo else run.started_at.replace(tzinfo=timezone.utc)
        b = run.finished_at if run.finished_at.tzinfo else run.finished_at.replace(tzinfo=timezone.utc)
        duration = max(int((b - a).total_seconds() * 1000), 0)
    return {"id": run.id, "trigger": run.trigger, "status": run.status, "error": run.error, "job_id": run.job_id,
            "conversation_id": conversation_id, "started_at": _iso(run.started_at),
            "finished_at": _iso(run.finished_at), "duration_ms": duration}
