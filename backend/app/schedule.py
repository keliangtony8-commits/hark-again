"""定时任务的时刻计算：worker 判断“到点没有”和接口给出“下次什么时候”共用这一处，
保证界面上写的下次时间就是 worker 实际会跑的时间。cron 按用户时区解释。

两种计划二选一：cron（重复）或 run_at（一次性，cron 为空串）。一次性任务跑过一次（last_run_at ≥ run_at）
就“已完成”：不再到点、next_run_at 为 null；把 run_at 改到上次运行之后即重新排上。
check() 是唯一的校验入口：接口（新建/修改）与智能体工具 schedule_task 都走它。"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from croniter import croniter

from .config import settings
from .models import ScheduledTask


def _aware(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)  # SQLite 读回来没有时区，存的是 UTC


def check(cron: str | None, run_at: datetime | None) -> None:
    """计划是否成立：cron 与 run_at 恰好给一个、cron 合法。不成立抛 ValueError（中文原因，直接给用户/模型看）。
    不拒绝过去的 run_at：worker 停过补跑也是这条路；新建时是否太早由调用方决定（见 is_past）。"""
    has_cron = bool((cron or "").strip())
    if has_cron == (run_at is not None):
        raise ValueError("重复（cron）和一次性（run_at）要恰好选一个。")
    if has_cron and not croniter.is_valid(cron):
        raise ValueError(f"cron 表达式无效：{cron}")


def is_once(task: ScheduledTask) -> bool:
    return task.run_at is not None


def is_done(task: ScheduledTask) -> bool:
    """一次性任务已经跑过。"""
    return task.run_at is not None and task.last_run_at is not None and _aware(task.last_run_at) >= _aware(task.run_at)


def due_at(task: ScheduledTask) -> datetime | None:
    """按计划下一次该跑的时刻（从上次运行、没跑过就从创建时算起）；停用、已完成或 cron 无效 → None。
    可能已经过去（worker 停过）：那就是下一轮轮询立刻补跑。"""
    if not task.active:
        return None
    if task.run_at is not None:
        return None if is_done(task) else _aware(task.run_at)
    if not croniter.is_valid(task.cron or ""):
        return None
    tz = ZoneInfo(settings.timezone)
    since = _aware(task.last_run_at or task.created_at or datetime.now(timezone.utc))
    if task.skip_at is not None:  # 跳过下一次（app/task_brief.py）：从被跳过的那一刻之后算
        since = max(since, _aware(task.skip_at))
    since = since.astimezone(tz)
    return croniter(task.cron, since).get_next(datetime)


def is_due(task: ScheduledTask, now: datetime) -> bool:
    if task.run_requested:
        return True
    at = due_at(task)
    return at is not None and at <= _aware(now)


def next_run_at(task: ScheduledTask, now: datetime | None = None) -> datetime | None:
    """给界面看的“下次运行”：过期未跑的显示为现在（马上补跑）；跳过的那次不算（已经从它之后算）。"""
    at = due_at(task)
    if at is None:
        return None
    now = _aware(now or datetime.now(timezone.utc))
    return max(at, now).astimezone(timezone.utc)


def local_now() -> datetime:
    return datetime.now(ZoneInfo(settings.timezone))


def parse_local(text: str) -> datetime:
    """“2026-10-12 08:00” / ISO（带不带时区都行；不带按用户时区）→ UTC。格式不对抛 ValueError。"""
    t = datetime.fromisoformat(text.strip().replace("/", "-"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=ZoneInfo(settings.timezone))
    return t.astimezone(timezone.utc)


def wire(task: ScheduledTask) -> dict:
    """接口给每个任务补的只读字段。"""
    from .task_brief import pending_skip  # 跳过的规则在 task_brief
    return {"next_run_at": next_run_at(task), "done": is_done(task), "skipped_at": pending_skip(task)}
