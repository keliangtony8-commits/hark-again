"""v2.64 反馈：回复下的 👍 / 👎 + 设置页的问题报告。规则全在 app/feedback.py，这里只做 HTTP 外壳。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import feedback
from ..auth import require_user
from ..db import get_session

router = APIRouter(prefix="/api", tags=["feedback"], dependencies=[Depends(require_user)])


class RateIn(BaseModel):
    kind: str
    note: str | None = None


class ReportIn(BaseModel):
    note: str


class StatusIn(BaseModel):
    status: str


async def _call(coro):
    try:
        return await coro
    except feedback.FeedbackError as e:
        raise HTTPException(e.status, str(e)) from e


@router.post("/messages/{mid}/feedback")
async def rate(mid: str, body: RateIn, db: AsyncSession = Depends(get_session)):
    return feedback.summary(await _call(feedback.rate(db, mid, body.kind, body.note)))


@router.delete("/messages/{mid}/feedback")
async def unrate(mid: str, db: AsyncSession = Depends(get_session)):
    return {"ok": True, "removed": await _call(feedback.unrate(db, mid))}


@router.get("/feedback")
async def listing(status: str | None = None, db: AsyncSession = Depends(get_session)):
    return await feedback.listing(db, status)


@router.post("/feedback")
async def report(body: ReportIn, db: AsyncSession = Depends(get_session)):
    return feedback.detail(await _call(feedback.report(db, body.note)))


@router.get("/feedback/{fid}")
async def detail(fid: str, db: AsyncSession = Depends(get_session)):
    return feedback.detail(await _call(feedback.get(db, fid)))


@router.patch("/feedback/{fid}")
async def set_status(fid: str, body: StatusIn, db: AsyncSession = Depends(get_session)):
    return feedback.detail(await _call(feedback.set_status(db, fid, body.status)))


@router.delete("/feedback/{fid}")
async def delete(fid: str, db: AsyncSession = Depends(get_session)):
    await _call(feedback.delete(db, fid))
    return {"ok": True}
