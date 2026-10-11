"""用量与花费（只读）。记账在 app/usage.py，这里只出报表。"""
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .. import usage
from ..auth import require_user
from ..db import get_session

router = APIRouter(prefix="/api/usage", tags=["usage"], dependencies=[Depends(require_user)])


@router.get("")
async def get_usage(db: AsyncSession = Depends(get_session)):
    return await usage.report(db)


@router.get("/days/{day}")
async def get_usage_day(day: date, db: AsyncSession = Depends(get_session)):
    """某一天的按模型拆分（用量图上点某天）。day = YYYY-MM-DD（服务器 TIMEZONE 的本地日期），格式不对 422。"""
    return await usage.day_report(db, day)
