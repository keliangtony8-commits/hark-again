"""定时任务（含面板）的增删改唯一写入口：接口的钩子与智能体工具 schedule_task / create_panel / manage_home 共用，
保证“删任务连带删 Home 卡片和运行记录”“面板改名卡片跟着改”只写在这一处。计划校验在 app/schedule.py check()。
面板 = output=panel 的任务 + 一张 kind=panel 的 HomeCard（task_id 相连）；标题以任务 name 为准，卡片 title 是它的镜像。"""
from datetime import datetime

from sqlalchemy import delete, update as sql_update

from . import reasoning, schedule, task_runs
from .config import settings
from .models import Conversation, HomeCard, ScheduledTask


def model_choice(value: object) -> str | None:
    """任务的模型选择（接口收进来时）："" / null = 默认（存 null）；不在 CHAT_MODELS 里 → ValueError（422）。
    存下来以后服务器改了配置也不怕：运行时 llm.chat_model 会回落到默认，和对话一个规则。"""
    if value in (None, ""):
        return None
    if not isinstance(value, str) or value not in settings.chat_models:
        raise ValueError(f"没有这个模型：{value}（可选 {', '.join(settings.chat_models)}）")
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


async def remove(db, task: ScheduledTask) -> None:
    await delete_cascade(db, task)
    await db.delete(task)
    await db.commit()


async def create(db, *, name: str, prompt: str, cron: str = "", run_at: datetime | None = None,
                 output: str = "report") -> ScheduledTask:
    schedule.check(cron, run_at)
    task = ScheduledTask(name=name, prompt=prompt, cron=cron.strip(), run_at=run_at, output=output)
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
    """合并后的计划仍须成立（二选一、cron 合法），否则 ValueError。"""
    schedule.check(changes.get("cron", task.cron), changes.get("run_at", task.run_at))


async def after_patch(db, task: ScheduledTask, changes: dict) -> None:
    """改完字段后的派生同步（不 commit）：面板改名 → 卡片标题跟着改；重新启用自动暂停的任务 → 归零、收起提醒。"""
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
