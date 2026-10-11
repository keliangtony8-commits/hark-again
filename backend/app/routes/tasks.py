"""定时任务的特殊动作（普通增删改查在 resources.py）。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from .. import task_runs
from ..auth import require_user
from ..db import get_session
from ..models import ScheduledTask

router = APIRouter(prefix="/api/tasks", dependencies=[Depends(require_user)])


@router.post("/{task_id}/run")
async def run_now(task_id: str, db: AsyncSession = Depends(get_session)):
    """交给 worker：它下一次轮询（≤15 秒）就会执行。"""
    task = await db.get(ScheduledTask, task_id)
    if not task:
        raise HTTPException(404)
    task.run_requested = True
    await db.commit()
    return {"ok": True}


@router.get("/{task_id}/runs")
async def runs(task_id: str, limit: int = Query(task_runs.KEEP, ge=1, le=task_runs.KEEP),
               db: AsyncSession = Depends(get_session)):
    """最近的运行记录，新的在前（见 app/task_runs.py 的 _wire）。"""
    if not await db.get(ScheduledTask, task_id):
        raise HTTPException(404)
    return await task_runs.history(db, task_id, limit)
