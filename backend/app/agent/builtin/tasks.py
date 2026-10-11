"""对话里管理定时任务与一次性提醒：“明早 8 点提醒我交作业”“每周一早上给我本周计划”“把早报改到 7 点”“取消那个提醒”。
计划校验在 app/schedule.py check()，增删在 app/task_store.py（与接口同一套规则）；面板另有 create_panel。"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ... import schedule, task_store
from ...config import settings
from ...models import ScheduledTask
from ..tools import ToolContext, ToolResult, tool


def _local(t: datetime | None) -> str:
    if t is None:
        return "—"
    t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    return t.astimezone(ZoneInfo(settings.timezone)).strftime("%Y-%m-%d %H:%M")


def _plan(t: ScheduledTask) -> str:
    if schedule.is_once(t):
        return f"一次 {_local(t.run_at)}" + ("（已完成）" if schedule.is_done(t) else "")
    return f"cron {t.cron}"


def _line(t: ScheduledTask) -> str:
    state = "已暂停" if not t.active else ("" if schedule.is_done(t) else f"下次 {_local(schedule.next_run_at(t))}")
    kind = "面板" if t.output == "panel" else "报告"
    return f"- id={t.id}「{t.name}」{kind} · {_plan(t)}" + (f" · {state}" if state else "")


def _when(run_at: str | None) -> datetime | None:
    return schedule.parse_local(run_at) if run_at else None


@tool("schedule_task", "正在安排任务",
      "管理定时任务和一次性提醒。action=create：cron（重复，5 段，用户时区）与 run_at（一次性，用户时区 'YYYY-MM-DD HH:MM'）二选一；"
      "prompt 是到点时独立执行的指令（看不到当前对话，写全要做什么；纯提醒就写“提醒我：……”），结果进 Home 收件箱。"
      "action=list 看现有任务和 id；update 按 id 改 name/prompt/cron/run_at/active（换成一次性传 run_at，换回重复传 cron）；cancel 按 id 删除。"
      "要反复看的数据（价格、比分）用 create_panel，不用这个。",
      {"type": "object", "properties": {
          "action": {"type": "string", "enum": ["create", "list", "update", "cancel"]},
          "id": {"type": "string", "description": "update/cancel 用，先 list 拿到"},
          "name": {"type": "string", "description": "几个字，如：交作业提醒"},
          "prompt": {"type": "string"},
          "cron": {"type": "string"},
          "run_at": {"type": "string", "description": "如 2026-10-12 08:00"},
          "active": {"type": "boolean"}},
       "required": ["action"]})
async def schedule_task(ctx: ToolContext, action: str, id: str | None = None, name: str | None = None,
                        prompt: str | None = None, cron: str | None = None, run_at: str | None = None,
                        active: bool | None = None) -> ToolResult:
    db = ctx.db
    try:
        when = _when(run_at)
    except ValueError:
        return ToolResult(f"run_at 格式不对：{run_at}，要 'YYYY-MM-DD HH:MM'。")
    if when is not None and when < datetime.now(timezone.utc) - timedelta(minutes=1):
        return ToolResult(f"{_local(when)} 已经过去了（现在 {schedule.local_now():%Y-%m-%d %H:%M}）。")

    if action == "list":
        rows = (await db.scalars(select(ScheduledTask).order_by(ScheduledTask.created_at.desc()))).all()
        return ToolResult("\n".join(_line(t) for t in rows) if rows else "还没有定时任务。")

    if action == "create":
        if not name or not prompt:
            return ToolResult("create 需要 name 和 prompt。")
        try:
            t = await task_store.create(db, name=name, prompt=prompt, cron=cron or "", run_at=when)
        except ValueError as e:
            return ToolResult(str(e))
        return ToolResult(f"已安排：{_line(t)}。到点结果会出现在 Home 收件箱，用户可在“我的 → 定时任务”里改。")

    t = await db.get(ScheduledTask, id) if id else None
    if t is None:
        return ToolResult("没找到这个任务，先用 action=list 查 id。")
    if action == "cancel":
        await task_store.remove(db, t)
        return ToolResult(f"已删除「{t.name}」。")
    if action == "update":
        changes = {k: v for k, v in {"name": name, "prompt": prompt, "active": active}.items() if v is not None}
        if when is not None:
            changes.update(run_at=when, cron="")
        elif cron:
            changes.update(cron=cron, run_at=None)
        try:
            await task_store.update(db, t, changes)
        except ValueError as e:
            return ToolResult(str(e))
        return ToolResult(f"已更新：{_line(t)}。")
    return ToolResult(f"未知 action：{action}")
