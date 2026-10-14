"""定时任务 / 面板 / 定时脚本每次运行开的那段对话（v2.75，用户 2026-10-14 13:58：“子对话”跑着的时候挤在主聊天列表里，
删了又冒出来，很乱）——“哪段对话是后台运行的、列表里藏不藏、什么时候清掉”的唯一规则。

- 标记：Conversation.task_id = 开它的任务 id ⇒ 这是一段运行对话。worker / script_tasks 只经 mark() 开它。
- 列表：主聊天和项目的对话列表只列 listed() 为真的（task_id 为空）。运行对话从 Home 的报告卡、任务详情的运行记录点开；
  搜索照常能搜到（搜索是“找”，不是“列”）。
- 接话：用户在运行对话里发了一句（ws 新消息 / 引导）→ promote()：清掉 task_id，从此是一段普通对话，进列表。
  按 Hark 的做法，回复一份报告就是开始聊这件事。
- 删除：任务这次还在跑（同任务有 running 的运行记录）时 busy() 为真，删对话的接口回 409——不然 worker 往一段删掉的对话写
  回复会撞外键（用户 13:58 报的 worker FK 错误）。
- 清理：运行记录只留最近 task_runs.KEEP 条；被裁掉的那几次、或任务被删时，还藏着的运行对话一起删（Home 上还挂着的卡引用的留着），
  免得看不见又删不掉的对话越积越多。被接过话（promote 了）的不动——那是用户自己的对话了。"""
from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Conversation, HomeCard, ScheduledTask, TaskRun


def mark(conv: Conversation, task: ScheduledTask) -> Conversation:
    conv.task_id = task.id
    return conv


def listed() -> ColumnElement[bool]:
    """对话列表的筛选条件：只列普通对话。"""
    return Conversation.task_id.is_(None)


def hidden(conv: Conversation | None) -> bool:
    return conv is not None and conv.task_id is not None


def promote(conv: Conversation) -> bool:
    """用户在这段对话里说话了：变成普通对话。返回是否有变化（不 commit，随这一轮的提交落库）。"""
    if conv.task_id is None:
        return False
    conv.task_id = None
    return True


async def busy(db: AsyncSession, conv: Conversation) -> bool:
    """开它的任务这次还在跑（worker 还要往里写）。"""
    if conv.task_id is None:
        return False
    return await db.scalar(select(TaskRun.id).where(
        TaskRun.task_id == conv.task_id, TaskRun.status == "running").limit(1)) is not None


async def drop(db: AsyncSession, conversation_ids: list[str] | None = None, task_id: str | None = None) -> int:
    """删还藏着的运行对话：按 id（被裁掉的运行记录）或按任务（任务被删）。Home 上没收起的卡还指着的留着。不 commit。"""
    if not conversation_ids and task_id is None:
        return 0
    where = [Conversation.task_id.is_not(None)]
    if conversation_ids:
        where.append(Conversation.id.in_(conversation_ids))
    if task_id is not None:
        where.append(Conversation.task_id == task_id)
    ids = list((await db.scalars(select(Conversation.id).where(*where))).all())
    if not ids:
        return 0
    pinned = set((await db.scalars(select(HomeCard.conversation_id).where(
        HomeCard.conversation_id.in_(ids), HomeCard.dismissed.is_(False)))).all())
    gone = [i for i in ids if i not in pinned]
    if gone:  # 消息等随外键 CASCADE；SQLite 测试库不开外键时 ORM 级联兜底
        for conv in (await db.scalars(select(Conversation).where(Conversation.id.in_(gone)))).all():
            await db.delete(conv)
    return len(gone)
