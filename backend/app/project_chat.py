"""v2.95 项目 = 一段对话（用户 2026-10-15 12:48：“一个项目不应该就一个对话吗，hark 就是这样的呀”）——唯一规则。

- 每个项目恰好一段普通对话（task_id 为空）：建项目时一起建；任何“在项目里说话”的入口（ws 新消息、主页建议卡、跨项目转交、
  客户端打开项目）都经 ensure() 取这段，不再新开。数据库兜底：部分唯一索引 uq_conversations_project_chat（迁移 0066）。
- 标题 = 项目名、title_source=fixed：项目页的药丸写项目名，不再自动起总结标题；项目改名时 rename() 跟着改。
- 定时脚本在项目工作区跑开的运行对话（task_id 非空，app/run_conversations.py）不算，不受约束、不进项目页。
- 项目对话不能单独删（随项目删除）：deletable() 给接口判 409。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import conversation_title
from .models import Conversation, Project

TITLE_MAX = 200


def _title(project: Project) -> str:
    return (project.name or "项目")[:TITLE_MAX]


async def of(db: AsyncSession, project_id: str) -> Conversation | None:
    """项目的那段普通对话；没有 → None。"""
    return await db.scalar(select(Conversation).where(Conversation.project_id == project_id, Conversation.task_id.is_(None))
                           .order_by(Conversation.created_at).limit(1))


async def ensure(db: AsyncSession, project: Project) -> Conversation:
    """取项目的那段对话，没有就建（flush，不 commit——随调用方的提交落库）。"""
    conv = await of(db, project.id)
    if conv is None:
        conv = Conversation(project_id=project.id, title=_title(project), title_source=conversation_title.FIXED)
        db.add(conv)
        await db.flush()
    return conv


async def after_create(db: AsyncSession, project: Project) -> None:
    """crud 建项目的钩子：项目和它的对话一起落库。"""
    await db.flush()
    await ensure(db, project)


async def rename(db: AsyncSession, project: Project, changes: dict) -> None:
    """crud 改项目的钩子：改了名字 → 对话标题跟着改（不动 updated_at，列表顺序不跳）。"""
    if "name" not in changes:
        return
    conv = await of(db, project.id)
    if conv is not None:
        conv.title, conv.updated_at = _title(project), conv.updated_at


def deletable(conv: Conversation) -> bool:
    return not (conv.project_id and conv.task_id is None)
