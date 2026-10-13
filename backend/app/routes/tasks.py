"""定时任务的特殊动作（普通增删改查在 resources.py）。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from .. import schedule, task_brief, task_runs
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


@router.post("/{task_id}/skip")
async def skip_next(task_id: str, db: AsyncSession = Depends(get_session)):
    """跳过下一次（再点一次 = 接着跳再下一次）；一次性 / 已暂停 → 422（规则见 app/task_brief.py）。"""
    task = await db.get(ScheduledTask, task_id)
    if not task:
        raise HTTPException(404)
    try:
        task_brief.skip_next(task)
    except ValueError as e:
        raise HTTPException(422, str(e))
    await db.commit()
    return {"ok": True, **schedule.wire(task)}


@router.delete("/{task_id}/skip")
async def unskip(task_id: str, db: AsyncSession = Depends(get_session)):
    """撤销跳过（还没到的那次）；没跳过也返回 ok。"""
    task = await db.get(ScheduledTask, task_id)
    if not task:
        raise HTTPException(404)
    task_brief.unskip(task)
    await db.commit()
    return {"ok": True, **schedule.wire(task)}
