"""定时任务（含面板）的增删改唯一写入口：接口的钩子与智能体工具 schedule_task / create_panel / manage_home 共用，
保证“删任务连带删 Home 卡片和运行记录”“面板改名卡片跟着改”只写在这一处。计划校验在 app/schedule.py check()。
面板 = output=panel 的任务 + 一张 kind=panel 的 HomeCard（task_id 相连）；标题以任务 name 为准，卡片 title 是它的镜像。"""
import re
from datetime import datetime, timezone

from sqlalchemy import delete, select, update as sql_update

from . import model_router, panel_log, reasoning, schedule, script_tasks, task_runs
from .config import settings
from .models import Conversation, HomeCard, ScheduledTask


def model_choice(value: object) -> str | None:
    """任务的模型选择（接口收进来时）："" / null = 默认（存 null）；不在 CHAT_MODELS 里 → ValueError（422）。
    存下来以后服务器改了配置也不怕：运行时 llm.chat_model 会回落到默认，和对话一个规则。"""
    if value in (None, ""):
        return None
    if not model_router.choosable(value):
        options = [*([model_router.AUTO] if model_router.enabled() else []), *settings.chat_models]
        raise ValueError(f"没有这个模型：{value}（可选 {', '.join(options)}）")
    return value


def reasoning_choice(value: object) -> str | None:
    """任务的思考强度："" / null = 模型默认；不认识的档 → ValueError。这个模型有没有这档不在这查（换模型后可能又有了），
    运行时 reasoning.resolve 没有就回默认。"""
    if value in (None, ""):
        return None
    if not reasoning.valid(value):
        raise ValueError(f"不认识的思考强度：{value}（可选 {', '.join(reasoning.EFFORTS)}）")
    return value


def conversation_for(task: ScheduledTask, title: str) -> Conversation:
    """每次运行开的新对话：带上任务自己的模型 / 思考强度（worker 只经这里开任务对话）。"""
    return Conversation(title=title, model=task.model, reasoning=task.reasoning)


async def delete_cascade(db, task: ScheduledTask) -> None:
    """删除前的清理：面板/收件箱/失败提醒卡和运行记录跟着任务走（不 commit，不删任务本身）。"""
    await db.execute(delete(HomeCard).where(HomeCard.task_id == task.id))
    await task_runs.remove_for(db, task.id)
    await panel_log.drop(db, [task.id])  # 记录面板的每一笔


async def remove(db, task: ScheduledTask) -> None:
    await delete_cascade(db, task)
    await db.delete(task)
    await db.commit()


async def remove_for_project(db, project_id: str) -> None:
    """删项目前：在它工作区里跑的定时脚本一起删（不 commit 之外的副作用同 remove）。"""
    for task in (await db.scalars(select(ScheduledTask).where(ScheduledTask.project_id == project_id))).all():
        await delete_cascade(db, task)
        await db.delete(task)


def _same_text(a: str | None, b: str | None) -> bool:
    """内容一样：忽略首尾空白、连续空白和句末标点（E2E：同一句提醒模型这次带“。”下次不带）。"""
    norm = lambda s: re.sub(r"\s+", " ", (s or "").strip()).rstrip("。．.！!～~ ")
    return norm(a) == norm(b)


def _utc(t: datetime | None) -> datetime | None:
    if t is None:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).replace(second=0, microsecond=0)


async def twin(db, *, prompt: str, cron: str = "", run_at: datetime | None = None, kind: str = "agent",
               project_id: str | None = None) -> ScheduledTask | None:
    """“同一件事已经安排过了”的唯一规则（v2.41，E2E B14：模型为了加个参数又 create 一遍 → 到点提醒两次）：
    还会再跑的（启用、一次性的没跑过）、同类型、同计划（cron 一样或 run_at 同一分钟）、内容一样（prompt / 命令，空白不计）的
    报告类任务算同一个；名字不看（模型换个说法起名很常见）。面板不在这查（create_panel 自有标题）。
    只给智能体工具用：用户在界面上自己建两个一样的，是他的事。"""
    rows = (await db.scalars(select(ScheduledTask).where(
        ScheduledTask.active.is_(True), ScheduledTask.kind == kind, ScheduledTask.output == "report"))).all()
    for t in rows:
        if schedule.is_done(t) or not _same_text(t.prompt, prompt):
            continue
        if kind == "script" and t.project_id != project_id:
            continue
        if (t.cron or "").split() == (cron or "").split() and _utc(t.run_at) == _utc(run_at):
            return t
    return None


async def create(db, *, name: str, prompt: str, cron: str = "", run_at: datetime | None = None,
                 output: str = "report", kind: str = "agent", notify: str = "failure",
                 project_id: str | None = None) -> ScheduledTask:
    """kind=script：prompt 是命令，project_id 是它的工作区（规则见 app/script_tasks.py）。"""
    schedule.check(cron, run_at)
    script_tasks.check(kind, prompt, notify, output)
    await script_tasks.check_project(db, project_id)
    task = ScheduledTask(name=name, prompt=prompt, cron=cron.strip(), run_at=run_at, output=output, kind=kind,
                         notify=notify, project_id=project_id if kind == "script" else None)
    db.add(task)
    await db.commit()
    return task


async def create_panel(db, *, title: str, prompt: str, cron: str) -> ScheduledTask:
    """面板：任务 + 占位卡，并请求立即跑第一次（worker 半分钟内领走）。"""
    from .blocks import text_to_blocks
    schedule.check(cron, None)
    task = ScheduledTask(name=title, prompt=prompt, cron=cron.strip(), output="panel", run_requested=True)
    db.add(task)
    await db.flush()
    db.add(HomeCard(kind="panel", title=title, task_id=task.id, blocks=text_to_blocks("正在准备第一份数据…")))
    await db.commit()
    return task


def check_patch(task: ScheduledTask, changes: dict) -> None:
    """合并后的计划仍须成立（二选一、cron 合法）、脚本仍有命令、提醒方式合法，否则 ValueError。类型（kind）建好就不变。"""
    schedule.check(changes.get("cron", task.cron), changes.get("run_at", task.run_at))
    script_tasks.check(task.kind, changes.get("prompt", task.prompt), changes.get("notify", task.notify), task.output)


async def after_patch(db, task: ScheduledTask, changes: dict) -> None:
    """改完字段后的派生同步（不 commit）：面板改名 → 卡片标题跟着改；重新启用自动暂停的任务 → 归零、收起提醒。"""
    if "cron" in changes or "run_at" in changes:  # 换了计划：之前“跳过下一次”指的那一次不一定还存在
        task.skip_at = None
    if changes.get("active") is True and task.paused_reason:
        await task_runs.resumed(db, task)
    if "name" in changes and task.output == "panel":
        await db.execute(sql_update(HomeCard).where(HomeCard.task_id == task.id, HomeCard.kind == "panel")
                         .values(title=task.name))


async def update(db, task: ScheduledTask, changes: dict) -> ScheduledTask:
    """工具用的改：校验 → 写字段 → 同步卡片 → commit（接口走 crud 的 on_update/after_update 两个钩子，规则相同）。"""
    check_patch(task, changes)
    for k, v in changes.items():
        setattr(task, k, v)
    await after_patch(db, task, changes)
    await db.commit()
    return task
