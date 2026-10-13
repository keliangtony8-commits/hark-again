"""后台任务接口：聊天里的任务卡轮询进度、取消；项目页列出最近的任务。规则在 app/jobs.py。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from .. import job_disk, job_usage, jobs, services
from ..auth import require_user
from ..db import get_session
from ..models import Job

router = APIRouter(prefix="/api/jobs", tags=["jobs"], dependencies=[Depends(require_user)])


@router.get("")
async def list_jobs(project_id: str | None = None, running: bool = False, db=Depends(get_session)):
    q = select(Job).order_by(Job.created_at.desc()).limit(50)
    if project_id:
        q = q.where(Job.project_id == project_id)
    if running:
        q = q.where(Job.state == "running")
    rows = (await db.scalars(q)).all()
    for job in rows:
        await jobs.refresh(db, job)  # 只看磁盘，不问沙盒：便宜
    return [jobs.wire(j, chars=600) for j in rows]


async def _get(db, job_id: str) -> Job:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "没有这个后台任务")
    return job


@router.get("/{job_id}")
async def get_job(job_id: str, tail: int = jobs.TAIL_CHARS, db=Depends(get_session)):
    job = await jobs.refresh(db, await _get(db, job_id))
    # v1.90 运行中的任务卡顺带看到它占多少 CPU / 内存（job_usage 有缓存，卡片轮询不会每次都去采样）
    usage = await job_usage.of(job)
    # v1.92 整台沙盒内存（同一次采样拿到的）：快满时任务卡提醒
    return {**jobs.wire(job, chars=max(200, min(tail, 20000))), "usage": usage,
            "box": job_usage.box(job.project_id) if usage else None,
            "disk": await job_disk.of(db, job)}  # v1.96 运行中现数（有缓存），结束了是结算时的账


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str, db=Depends(get_session)):
    job = await _get(db, job_id)
    try:
        await jobs.cancel(db, job)
    except jobs.JobError as e:
        raise HTTPException(503, str(e))
    return jobs.wire(job)


@router.post("/{job_id}/restart")
async def restart_job(job_id: str, db=Depends(get_session)):
    """常驻服务手动重启（v1.82，规则在 app/services.py）：在跑的杀掉重起、等重启的马上起、放弃了的重新拉起。"""
    job = await _get(db, job_id)
    try:
        await services.restart(db, job)
    except services.ServiceError as e:
        raise HTTPException(409, str(e))
    return jobs.wire(job)
