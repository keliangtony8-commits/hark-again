"""对话里管理定时任务与一次性提醒：“明早 8 点提醒我交作业”“每周一早上给我本周计划”“把早报改到 7 点”“取消那个提醒”。
计划校验在 app/schedule.py check()，增删在 app/task_store.py（与接口同一套规则）；面板另有 create_panel。"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ... import schedule, script_tasks, task_brief, task_runs, task_store, task_wall
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
    elif t.paused_reason == task_brief.ENDED and not t.active:
        state = "已按指令结束"
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
    if (skipped := task_brief.pending_skip(t)) is not None:
        state += f" · 跳过 {_local(skipped)} 那次"
    if t.wall:
        state += f" · 碰壁：{task_wall.error_text(t.wall, t.wall_reason)}"
    memo = "、".join(w for w, v in (("做法", t.runbook), ("观察", t.note)) if v)
    return (f"- id={t.id}「{t.name}」{kind} · {_plan(t)}" + (f" · {state}" if state else "")
            + (f" · 已记下{memo}" if memo else ""))


def _run(r: dict) -> str:
    when = _local(schedule.parse_local(r["started_at"])) if r["started_at"] else "—"
    how = "手动" if r["trigger"] == "manual" else "定时"
    if r["status"] == "running":
        what = "正在运行"
    elif r["status"] == "error":
        what = ("碰壁" if r.get("wall") else "失败") + f"：{r['error']}"
    elif r["silent_reason"] is not None:
        what = f"没打扰用户：{r['silent_reason']}"
    else:
        what = "成功，已告诉用户"
    took = f"，用时 {r['duration_ms'] // 1000} 秒" if r["duration_ms"] is not None else ""
    return f"- {when}（{how}{took}）{what}"


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
      "runs 看最近几次运行（成功 / 失败原因 / 没打扰用户的原因）；run_now 立刻跑一次；skip_next 跳过下一次（unskip 撤销）。"
      "set_runbook / note（text 整段替换，空串清空）：任务自己的做法与观察，每次运行开头都会读到；"
      "report_wall（只在任务自己的运行里）：碰到只有用户能清掉的障碍或暂时的阻碍时记下 wall=<类>:<对象> 和 text（发生了什么），"
      "用户会看到可修的标记，这次算碰壁失败、面板保留上次内容；之后照常交付已完成的部分。"
      "在定时任务运行里调用时 id 可省略（就是正在跑的这个任务）；运行里不能 update/run_now/skip 任何任务（计划由用户决定，在结果里建议），"
      "只有指令要求时才 create 或 cancel 自己。"
      "要反复看的数据（价格、比分）用 create_panel，不用这个。",
      {"type": "object", "properties": {
          "action": {"type": "string", "enum": ["create", "list", "update", "cancel", "runs", "run_now",
                                                 "skip_next", "unskip", "set_runbook", "note", "report_wall"]},
          "id": {"type": "string", "description": "除 create/list 外都要，先 list 拿到"},
          "text": {"type": "string", "description": "set_runbook（≤16000 字）/ note（≤4000 字）的全文；report_wall 的一两句经过"},
          "wall": {"type": "string", "description": "report_wall 用：needs_login:<域名> / needs_connector:<名字> / paywall:<域名> / source_gone:<域名> / blocked:<原因>"},
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
                        active: bool | None = None, command: str | None = None, notify: str | None = None,
                        text: str | None = None, wall: str | None = None) -> ToolResult:
    db = ctx.db
    try:
        when = _when(run_at)
    except ValueError:
        return ToolResult(f"run_at 格式不对：{run_at}，要 'YYYY-MM-DD HH:MM'。")
    if when is not None and when < datetime.now(timezone.utc) - timedelta(minutes=1):
        return ToolResult(f"{_local(when)} 已经过去了（现在 {schedule.local_now():%Y-%m-%d %H:%M}）。")

    refused = task_brief.fire_refusal(ctx.task_id, action, id)
    if refused:
        return ToolResult(refused)

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

    id = id or (ctx.task_id if action in ("set_runbook", "note", "runs", "report_wall", "cancel") else None)  # 任务运行里：默认就是自己
    t = await db.get(ScheduledTask, id) if id else None
    if t is None:
        return ToolResult("没找到这个任务，先用 action=list 查 id。")
    if action in ("set_runbook", "note"):
        if text is None:
            return ToolResult(f"{action} 需要 text（整段全文；空串 = 清空）。")
        if script_tasks.is_script(t):
            return ToolResult("定时脚本不调用助手，用不上做法和观察。")
        field = "runbook" if action == "set_runbook" else "note"
        try:
            setattr(t, field, task_brief.clean(field, text))
        except ValueError as e:
            return ToolResult(str(e))
        await db.commit()
        what = "做法" if field == "runbook" else "观察"
        return ToolResult(f"已{'清空' if getattr(t, field) is None else '记下'}「{t.name}」的{what}，之后每次运行开头都会读到。")
    if action == "report_wall":
        if t.id != ctx.task_id:
            return ToolResult("report_wall 只能在这个任务自己的运行里用；聊天里排查别的任务用 runs。")
        try:
            w = await task_wall.report(db, t, wall or "", text)
        except ValueError as e:
            return ToolResult(str(e))
        hint = "用户会看到要他处理的标记" if task_wall.fixable(w) else "之后会自动再试"
        return ToolResult(f"已记下碰壁：{task_wall.error_text(w, t.wall_reason)}（{hint}）。接着交付已经做完的部分。")
    if action == "runs":
        rows = await task_runs.history(db, t.id, 10)
        return ToolResult("\n".join(_run(r) for r in rows) if rows else f"「{t.name}」还没运行过。")
    if action == "run_now":
        if t.id == ctx.task_id:
            return ToolResult("这就是正在跑的任务，不能在运行里再叫自己跑一次。")
        t.run_requested = True
        await db.commit()
        return ToolResult(f"「{t.name}」已排队，几秒内开始；结果照常{'刷新面板' if t.output == 'panel' else '进 Home 收件箱'}。")
    if action == "skip_next":
        try:
            at = task_brief.skip_next(t)
        except ValueError as e:
            return ToolResult(str(e))
        await db.commit()
        return ToolResult(f"已跳过 {_local(at)} 那次：{_line(t)}。")
    if action == "unskip":
        done = task_brief.unskip(t)
        await db.commit()
        return ToolResult(f"已撤销跳过：{_line(t)}。" if done else f"「{t.name}」没有待跳过的一次。")
    if action == "cancel" and t.id == ctx.task_id:  # 运行里按指令结束自己：停用，这次照常交付（task_brief.end_self）
        task_brief.end_self(t)
        await db.commit()
        return ToolResult(f"已结束「{t.name}」：这次的结果照常交付，之后不再运行（任务留在列表里，用户可以删掉或重新打开）。")
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
