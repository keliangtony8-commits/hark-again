"""对话里管理定时任务与一次性提醒：“明早 8 点提醒我交作业”“每周一早上给我本周计划”“把早报改到 7 点”“取消那个提醒”。
计划校验在 app/schedule.py check()，增删在 app/task_store.py（与接口同一套规则）；面板另有 create_panel。"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ... import schedule, script_tasks, task_store
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
    if t.paused_reason == "failures":
        state = f"连续失败 {t.fail_streak} 次已自动暂停（修好后 update active=true 恢复）"
    elif not t.active:
        state = "已暂停"
    else:
        state = "" if schedule.is_done(t) else f"下次 {_local(schedule.next_run_at(t))}"
        if t.last_status == "error":
            state += f" · 已连续失败 {t.fail_streak} 次" if t.fail_streak > 1 else " · 上次失败"
    if script_tasks.is_script(t):
        kind = f"脚本（{script_tasks.NOTIFY_LABELS.get(t.notify, t.notify)}）`{t.prompt[:80]}`"
    else:
        kind = "面板" if t.output == "panel" else "报告"
    return f"- id={t.id}「{t.name}」{kind} · {_plan(t)}" + (f" · {state}" if state else "")


def _when(run_at: str | None) -> datetime | None:
    return schedule.parse_local(run_at) if run_at else None


@tool("schedule_task", "正在安排任务",
      "管理定时任务和一次性提醒。action=create：cron（重复，5 段，用户时区）与 run_at（一次性，用户时区 'YYYY-MM-DD HH:MM'）二选一；"
      "prompt 是到点时独立执行的指令（看不到当前对话，写全要做什么；纯提醒就写“提醒我：……”），结果进 Home 收件箱。"
      "定时脚本：create 时给 command（不给 prompt）= 到点直接在当前工作区跑这条 shell 命令，不调用模型、不花 token，"
      "适合备份、定时抓取/爬虫、跑测试、清理文件这类固定步骤（复杂的先写成脚本文件放工作区再调用）；"
      "notify：failure 只在失败时告诉用户（默认）/ always 每次 / change 输出和上次不一样时（监控网页、价格用这个）。"
      "需要判断、总结、搜索的事才用 prompt 交给助手。"
      "action=list 看现有任务和 id；update 按 id 改 name/prompt/command/notify/cron/run_at/active（换成一次性传 run_at，换回重复传 cron）；cancel 按 id 删除。"
      "要反复看的数据（价格、比分）用 create_panel，不用这个。",
      {"type": "object", "properties": {
          "action": {"type": "string", "enum": ["create", "list", "update", "cancel"]},
          "id": {"type": "string", "description": "update/cancel 用，先 list 拿到"},
          "name": {"type": "string", "description": "几个字，如：交作业提醒"},
          "prompt": {"type": "string"},
          "command": {"type": "string", "description": "定时脚本的 shell 命令（在工作区根目录跑）"},
          "notify": {"type": "string", "enum": list(script_tasks.NOTIFY)},
          "cron": {"type": "string"},
          "run_at": {"type": "string", "description": "如 2026-10-12 08:00"},
          "active": {"type": "boolean"}},
       "required": ["action"]})
async def schedule_task(ctx: ToolContext, action: str, id: str | None = None, name: str | None = None,
                        prompt: str | None = None, cron: str | None = None, run_at: str | None = None,
                        active: bool | None = None, command: str | None = None, notify: str | None = None) -> ToolResult:
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
        if not name or not (prompt or command):
            return ToolResult("create 需要 name，以及 prompt（交给助手）或 command（定时脚本）二选一。")
        if prompt and command:
            return ToolResult("prompt 和 command 只给一个：要助手判断/总结用 prompt，固定命令用 command。")
        try:
            if command:
                t = await task_store.create(db, name=name, prompt=command, cron=cron or "", run_at=when, kind="script",
                                            notify=notify or "failure", project_id=ctx.project_id)
            else:
                t = await task_store.create(db, name=name, prompt=prompt, cron=cron or "", run_at=when)
        except ValueError as e:
            return ToolResult(str(e))
        where = "失败或按 notify 该告诉用户时结果进 Home 收件箱" if command else "到点结果会出现在 Home 收件箱"
        return ToolResult(f"已安排：{_line(t)}。{where}，用户可在“我的 → 定时任务”里改。")

    t = await db.get(ScheduledTask, id) if id else None
    if t is None:
        return ToolResult("没找到这个任务，先用 action=list 查 id。")
    if action == "cancel":
        await task_store.remove(db, t)
        return ToolResult(f"已删除「{t.name}」。")
    if action == "update":
        if command is not None and not script_tasks.is_script(t):
            return ToolResult("这是交给助手的任务，不能改成脚本：取消后用 command 重建。")
        if prompt is not None and script_tasks.is_script(t):
            return ToolResult("这是定时脚本，改命令用 command。")
        changes = {k: v for k, v in {"name": name, "prompt": command if command is not None else prompt,
                                      "active": active, "notify": notify}.items() if v is not None}
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
