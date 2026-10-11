"""收件箱未读：客户端轻量轮询的唯一入口（没有推送时，App 回到前台 / 定时问一句“有新的吗”）。

未读状态在服务端，网页和 App 共享：任一端读过，另一端的角标同步消失。
“读过”= 打开了报告对应的对话（conversations.get 调 mark_read）或点了“全部已读”。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_user
from ..db import get_session
from ..models import HomeCard

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
    latest = await db.scalar(select(HomeCard).where(*_UNREAD).order_by(HomeCard.created_at.desc()).limit(1))
    return {
        "unread": count,
        "latest": None if latest is None else {
            "id": latest.id, "kind": latest.kind, "title": latest.title,
            "headline": latest.headline, "gist": latest.gist,
            "conversation_id": latest.conversation_id, "created_at": latest.created_at.isoformat(),
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
