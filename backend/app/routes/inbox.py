"""收件箱未读：客户端轻量轮询的唯一入口（没有推送时，App 回到前台 / 定时问一句“有新的吗”）。

未读状态在服务端，网页和 App 共享：任一端读过，另一端的角标同步消失。
“读过”= 打开了报告对应的对话（conversations.get 调 mark_read）或点了“全部已读”。
latest = 最近“来到”收件箱的未读：按 updated_at 排——新报告、到点叫醒的“稍后再看”（card_snooze.wake_due 把 updated_at
设成叫醒时刻）、重新提议的建议都算刚到，客户端横幅照样弹；mark_read 不改 updated_at，所以“读过”不会让别的条目冒成最新。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_user
from ..db import get_session
from ..models import HomeCard
from ..wire_time import iso

router = APIRouter(prefix="/api/inbox", tags=["inbox"], dependencies=[Depends(require_user)])

_UNREAD = (HomeCard.unread.is_(True), HomeCard.dismissed.is_(False))


async def mark_read(db: AsyncSession, *, ids: list[str] | None = None, conversation_id: str | None = None) -> None:
    """标记已读，不改 updated_at（列表顺序不因“读过”而变）。都不传 = 全部已读。"""
    q = update(HomeCard).where(HomeCard.unread.is_(True)).values(unread=False, updated_at=HomeCard.updated_at)
    if ids is not None:
        q = q.where(HomeCard.id.in_(ids))
    if conversation_id is not None:
        q = q.where(HomeCard.conversation_id == conversation_id)
    await db.execute(q)


async def summary(db: AsyncSession) -> dict:
    count = await db.scalar(select(func.count()).select_from(HomeCard).where(*_UNREAD)) or 0
    latest = await db.scalar(select(HomeCard).where(*_UNREAD).order_by(HomeCard.updated_at.desc(), HomeCard.created_at.desc()).limit(1))
    return {
        "unread": count,
        "latest": None if latest is None else {
            "id": latest.id, "kind": latest.kind, "title": latest.title,
            "headline": latest.headline, "gist": latest.gist,
            "conversation_id": latest.conversation_id, "created_at": iso(latest.created_at),
        },
    }


@router.get("")
async def get_inbox(db: AsyncSession = Depends(get_session)):
    return await summary(db)


class ReadIn(BaseModel):
    ids: list[str] | None = None  # 不传 = 全部已读


@router.post("/read")
async def read(body: ReadIn, db: AsyncSession = Depends(get_session)):
    await mark_read(db, ids=body.ids)
    await db.commit()
    return await summary(db)
