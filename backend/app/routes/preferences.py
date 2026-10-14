"""偏好设置（我的 → 偏好设置，对标 Hark System preferences）。现在只有回复语言；规则在 app/reply_language.py。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import reply_language
from ..auth import require_user
from ..db import get_session

router = APIRouter(prefix="/api/preferences", dependencies=[Depends(require_user)])


class Patch(BaseModel):
    reply_language: str | None = None


@router.get("")
async def get_preferences(db: AsyncSession = Depends(get_session)):
    return reply_language.wire(await reply_language.get(db))


@router.patch("")
async def patch_preferences(body: Patch, db: AsyncSession = Depends(get_session)):
    if body.reply_language is not None:
        try:
            await reply_language.set(db, body.reply_language)
        except ValueError as e:
            raise HTTPException(422, str(e))
    return reply_language.wire(await reply_language.get(db))
