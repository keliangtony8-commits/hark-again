"""用 CRUD 工厂声明的简单资源。新增一个简单资源 = 在这里加几行。"""
import shutil

from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator

from sqlalchemy import delete, func, select

from ..models import Conversation, HomeCard, Memory, Project, ScheduledTask
from .. import card_snooze, project_brief, sandbox_client, schedule, task_store
from ..storage import PROJECTS
from .crud import crud_router


class ProjectIn(BaseModel):
    name: str
    emoji: str = "📁"
    rules: str = ""


class ProjectPatch(BaseModel):
    name: str | None = None
    emoji: str | None = None
    rules: str | None = None
    brief: str | None = Field(None, max_length=project_brief.BRIEF_MAX)


class MemoryIn(BaseModel):
    content: str
    category: str = "general"


class MemoryPatch(BaseModel):
    content: str | None = None
    category: str | None = None


class TaskIn(BaseModel):
    """cron（重复）与 run_at（一次性）二选一，见 app/schedule.py check()。"""
    name: str
    prompt: str
    cron: str = ""
    run_at: datetime | None = None
    active: bool = True

    @model_validator(mode="after")
    def _plan(self):
        schedule.check(self.cron, self.run_at)  # ValueError → 422
        return self


class TaskPatch(BaseModel):
    """换成一次性：{run_at, cron: ""}；换回重复：{cron, run_at: null}。"""
    name: str | None = None
    prompt: str | None = None
    cron: str | None = None
    run_at: datetime | None = None
    active: bool | None = None


def _check_task_patch(task: ScheduledTask, changes: dict) -> None:
    """合并后的计划仍须成立（二选一、cron 合法），否则 422。"""
    try:
        task_store.check_patch(task, changes)
    except ValueError as e:
        raise HTTPException(422, str(e))


class CardIn(BaseModel):
    kind: str
    title: str
    blocks: list = []
    action_prompt: str | None = None
    target: str | None = None  # 客户端固定去处，如 "usage"
    unread: bool = True  # 经接口新建的卡（主动建议）默认未读


class CardPatch(BaseModel):
    title: str | None = None
    blocks: list | None = None
    dismissed: bool | None = None
    unread: bool | None = None
    snoozed_until: datetime | None = None  # 稍后提醒到这个时刻；null = 现在就放回来。规则见 app/card_snooze.py


def _check_card_patch(card: HomeCard, changes: dict) -> None:
    try:
        card_snooze.on_patch(card, changes)
    except ValueError as e:
        raise HTTPException(422, str(e))


async def _delete_project_conversations(db, project: Project) -> None:
    await db.execute(delete(Conversation).where(Conversation.project_id == project.id))
    shutil.rmtree(PROJECTS / project.id, ignore_errors=True)  # 工作区文件一并删除
    await sandbox_client.remove(project.id)


async def _project_activity(db, projects: list[Project]) -> dict[str, dict]:
    """项目卡片上的“x 个对话 · 更新于…”：对话数 + 最近活动（项目本身或其中任一对话的最后更新）。一条 GROUP BY。"""
    ids = [p.id for p in projects]
    rows = (await db.execute(
        select(Conversation.project_id, func.count(Conversation.id), func.max(Conversation.updated_at))
        .where(Conversation.project_id.in_(ids)).group_by(Conversation.project_id))).all()
    stats = {pid: (n, last) for pid, n, last in rows}
    out = {}
    for p in projects:
        n, last = stats.get(p.id, (0, None))
        times = [(t if t.tzinfo else t.replace(tzinfo=timezone.utc)) for t in (p.updated_at, last) if t is not None]
        out[p.id] = {"conversation_count": n, "last_active_at": max(times) if times else None}
    return out


routers = [
    crud_router("/api/projects", Project, ProjectIn, ProjectPatch, order_by=Project.updated_at.desc(),
                on_delete=_delete_project_conversations, annotate=_project_activity, on_update=project_brief.on_patch),
    crud_router("/api/memories", Memory, MemoryIn, MemoryPatch, order_by=Memory.updated_at.desc()),
    crud_router("/api/tasks", ScheduledTask, TaskIn, TaskPatch, order_by=ScheduledTask.created_at.desc(),
                on_delete=task_store.delete_cascade, extra=schedule.wire, on_update=_check_task_patch,
                after_update=task_store.after_patch),
    crud_router("/api/cards", HomeCard, CardIn, CardPatch, order_by=HomeCard.updated_at.desc(),
                extra=card_snooze.wire, on_update=_check_card_patch),
]
