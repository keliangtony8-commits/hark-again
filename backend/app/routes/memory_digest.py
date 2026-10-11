"""“我对你的了解”。GET 零模型调用（只看是否过期），POST 才重新生成（一次便宜模型调用）。
单独前缀而不挂在 /api/memories 下：那边的 /{item_id} 会吞掉子路径。"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .. import memory_digest
from ..auth import require_user
from ..db import get_session

router = APIRouter(prefix="/api/memory-digest", tags=["memory"], dependencies=[Depends(require_user)])
log = logging.getLogger("memory_digest")


@router.get("")
async def get_digest(db: AsyncSession = Depends(get_session)):
    return await memory_digest.get(db)


@router.post("")
async def regenerate_digest(db: AsyncSession = Depends(get_session)):
    try:
        return await memory_digest.regenerate(db)
    except Exception:
        log.exception("digest failed")
        raise HTTPException(502, "生成失败，稍后再试")
