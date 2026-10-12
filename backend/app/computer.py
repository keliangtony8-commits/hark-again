"""工作区“电脑”状态的唯一入口：项目页 / 我的电脑页看的那一块（对标 Hark：每段对话背后有一台云电脑，用户看得到它在不在跑、在忙什么）。

status(db, ws) 把三处事实拼在一起，只读不启动：
  - 沙盒容器（sandbox_client.status）：running 运行中 / stopped 空闲休眠了 / none 还没开过机 / unreachable 沙盒服务连不上；
    运行中带内存已用/上限、开机时间、镜像是否过期（下次用到会自动换新）；
  - 工作区占用的磁盘（含隐藏的 .home 装的包、.jobs 日志——这些都真占 VPS 的盘）；
  - 正在跑的后台任务（jobs.wire，带日志尾巴，前端可取消、看日志）。
restart(db, ws)：用户觉得电脑卡死了（内存打满、进程失控）时的出路——先按“用户取消”停掉后台任务（结论是“已取消”，
助手照常在原对话接一句），再删掉容器；文件和装过的包都在工作区里，下次用到自动重建，所以重启不丢东西。
"""
import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import jobs, sandbox_client, workspaces
from .models import Job
from .storage import project_dir
from .wire_time import iso

DISK_SCAN_MAX = 200_000  # 最多数这么多个文件（node_modules 很大时也别把接口拖死），超过标 disk_partial


class ComputerError(RuntimeError):
    """给用户看的中文原因。"""


def disk_usage(root: Path, limit: int = DISK_SCAN_MAX) -> tuple[int, bool]:
    """(字节数, 是否只数了一部分)。不跟随符号链接（.venv 里一堆链接不重复算）。"""
    total, seen, stack = 0, 0, [str(root)]
    while stack:
        try:
            with os.scandir(stack.pop()) as it:
                for e in it:
                    seen += 1
                    if seen > limit:
                        return total, True
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total, False


def _ts(v) -> str | None:
    return iso(datetime.fromtimestamp(v, timezone.utc)) if isinstance(v, (int, float)) else None


def sandbox_wire(raw: dict | None) -> dict:
    """沙盒服务的原始状态 → 客户端字段。None = 连不上。"""
    if raw is None:
        return {"state": "unreachable"}
    state = raw.get("state") if raw.get("state") in ("running", "stopped", "none") else "none"
    return {"state": state, "memory_used": raw.get("memory_used"), "memory_limit": raw.get("memory_limit"),
            "started_at": _ts(raw.get("started_at")), "last_used_at": _ts(raw.get("last_used")),
            "idle_minutes": raw.get("idle_minutes"), "outdated": bool(raw.get("outdated"))}


async def running_jobs(db: AsyncSession, ws: str) -> list[Job]:
    rows = (await db.scalars(select(Job).where(Job.project_id == ws, Job.state == "running")
                             .order_by(Job.created_at.desc()))).all()
    for job in rows:
        await jobs.refresh(db, job)  # 只看磁盘：刚结束的别还挂着
    return [j for j in rows if j.state == "running"]


async def status(db: AsyncSession, ws: str) -> dict:
    name = await workspaces.name(db, ws)
    if name is None:
        raise LookupError("没有这个工作区")
    try:
        raw = await sandbox_client.status(ws)
    except httpx.HTTPError:
        raw = None
    used, partial = await asyncio.to_thread(disk_usage, project_dir(ws))
    return {"workspace": ws, "name": name, "sandbox": sandbox_wire(raw), "disk_used": used, "disk_partial": partial,
            "running_jobs": [jobs.wire(j, chars=600) for j in await running_jobs(db, ws)]}


async def restart(db: AsyncSession, ws: str) -> dict:
    """停后台任务 → 删容器。沙盒连不上就整件不做（抛 ComputerError），不留半截状态。"""
    if await workspaces.name(db, ws) is None:
        raise LookupError("没有这个工作区")
    try:
        await sandbox_client.status(ws)  # 先确认沙盒服务在，免得任务停了一半
    except httpx.HTTPError as e:
        raise ComputerError("沙盒服务连不上，没能重启") from e
    for job in await running_jobs(db, ws):
        try:
            await jobs.stop(db, job, "user")
        except jobs.JobError as e:
            raise ComputerError(str(e)) from e
    try:
        await sandbox_client.restart(ws)
    except httpx.HTTPError as e:
        raise ComputerError("沙盒服务没响应，没能重启") from e
    for job in await running_jobs(db, ws):  # 容器删了，进程肯定没了
        await jobs.settle(db, job, *(jobs.observe(job) or ("lost", None)))
    return await status(db, ws)
