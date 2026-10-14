"""工作区“电脑”状态的唯一入口：项目页 / 我的电脑页看的那一块（对标 Hark：每段对话背后有一台云电脑，用户看得到它在不在跑、在忙什么）。

status(db, ws) 把三处事实拼在一起，只读不启动：
  - 沙盒容器（sandbox_client.status）：running 运行中 / stopped 空闲休眠了 / none 还没开过机 / unreachable 沙盒服务连不上；
    运行中带内存已用/上限、开机时间、镜像是否过期（下次用到会自动换新）；
  - 工作区占用的磁盘（含隐藏的 .home 装的包、.jobs 日志——这些都真占 VPS 的盘）；
  - 正在跑的后台任务（jobs.wire，带日志尾巴，前端可取消、看日志）；
  - 磁盘配额（v1.31，quota.py）：disk_limit / disk_level ok|tight|full|off，满了写不进、后台任务被停；
  - 在监听的端口（v1.30，只在运行中时问沙盒；旁边“预览”按钮走 POST …/computer/preview，规则在 preview.py）；
  - 内存去哪了（v1.94，memory_view.py）：按后台任务 / 常驻服务 / 零散程序排出谁占的内存，余下归“其它”；
  - 磁盘谁写得最多（v1.98，job_disk.leaders）：最近 7 天结束的后台任务按结算时的磁盘账排前 5（disk_jobs：jobs.wire + log_kept）。
v1.27 补齐“像一台电脑”的那几样：CPU（占配额的百分比）、正在跑的程序（按 CPU 排前 8）、内存打满被系统杀过几次（OOM）、
磁盘按用途拆开（文件 / 装的软件 / 任务日志 / 长输出存档 / 下载缓存）、装过的工具清单（pip / npm 用户级安装，直接读工作区
~/.local，不用开机）；cleanup(db, ws) 一键清掉能安全删的：长输出存档 .spill、已结束任务的日志目录（卡片和结论里的
日志尾巴存在库里，不受影响）、下载缓存（工作区 .home/.cache 和容器 /tmp 里的 pip/npm 缓存）。
restart(db, ws)：用户觉得电脑卡死了（内存打满、进程失控）时的出路——先按“用户取消”停掉后台任务（结论是“已取消”，
助手照常在原对话接一句），再删掉容器；文件和装过的包都在工作区里，下次用到自动重建，所以重启不丢东西。
"""
import asyncio
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from . import job_disk, job_usage, jobs, machine, memory_view, preview, quota, sandbox_client, services, workspaces
from .models import Job
from .storage import project_dir
from .wire_time import iso

disk_usage = quota.disk_usage  # 数法只有一份（quota.py），这里沿用旧名


class ComputerError(RuntimeError):
    """给用户看的中文原因。"""


HOME = workspaces.HOME_DIR
CACHE = f"{HOME}/.cache"
TOOLS_MAX = 200  # 工具清单最多列这么多（用户级装几百个包也不至于）
PROCESS_MAX = 8
# 沙盒停机原因（sandbox/runner.py stopped_by / 命令结果 woke）→ 给模型的那句话。两端的文案在各自 computer 模型里
WAKE_TEXT = {"idle": "空闲太久自动休眠过", "room": "为给其它工作区腾内存休眠过"}


def wake_note(reason) -> str:
    """命令把休眠的电脑开起来时附在结果后面：之前前台起的程序（开发服务器等）都已经停了。"""
    if reason not in WAKE_TEXT:
        return ""
    return (f"\n（这台电脑刚才{WAKE_TEXT[reason]}，这条命令把它重新开机了：文件和装过的软件都在，"
            "但之前在前台起的程序（开发服务器、nohup 的进程）已经停了，需要的话重新启动；"
            "要一直开着的服务用 background=true + keep_alive=true，停机重启后会自己拉起）")


def storage_breakdown(root: Path, running: set[str] = frozenset()) -> dict:
    """磁盘按用途拆开（字节）。cleanable = 一键清理能腾出的：存档 + 已结束任务日志 + 缓存。"""
    out = {"files": 0, "installed": 0, "logs": 0, "spill": 0, "cache": 0, "cleanable": 0, "partial": False}

    def add(key: str, path: Path) -> int:
        n, part = disk_usage(path) if path.is_dir() else (path.stat().st_size if path.is_file() else 0, False)
        out[key] += n
        out["partial"] |= part
        return n
    try:
        top = list(os.scandir(root))
    except OSError:
        return out
    for e in top:
        p = Path(e.path)
        if e.is_symlink():
            continue
        if e.name == HOME:
            for sub in _children(p):
                add("cache" if sub.name == ".cache" else "installed", sub)
        elif e.name == jobs.JOBS_DIR:
            for sub in _children(p):
                n = add("logs", sub)
                if sub.name not in running:
                    out["cleanable"] += n
        elif e.name == ".spill":
            out["cleanable"] += add("spill", p)
        else:  # 用户的文件（含 .git）
            add("files", p)
    out["cleanable"] += out["cache"]
    return out


def _children(p: Path) -> list[Path]:
    try:
        return [Path(x.path) for x in os.scandir(p) if not x.is_symlink()]
    except OSError:
        return []


def installed_tools(root: Path) -> list[dict]:
    """用户级装的东西（不含预装）：pip（~/.local/lib/python*/site-packages/*.dist-info）和 npm -g（~/.local/lib/node_modules）。"""
    local = root / HOME / ".local"
    out: list[dict] = []
    for info in sorted(local.glob("lib/python*/site-packages/*.dist-info")):
        name, _, ver = info.name[:-len(".dist-info")].rpartition("-")
        if name:
            out.append({"kind": "pip", "name": name.replace("_", "-"), "version": ver})
    nm = local / "lib" / "node_modules"
    pkgs = [d for d in _children(nm) if not d.name.startswith(".")]
    pkgs = [x for d in pkgs for x in (_children(d) if d.name.startswith("@") else [d])]
    for d in sorted(pkgs):
        try:
            meta = json.loads((d / "package.json").read_text())
        except (OSError, ValueError):
            continue
        if isinstance(meta, dict) and meta.get("name"):
            out.append({"kind": "npm", "name": str(meta["name"]), "version": str(meta.get("version") or "")})
    out.sort(key=lambda t: (t["kind"], t["name"].lower()))
    return out[:TOOLS_MAX]


def _ts(v) -> str | None:
    return iso(datetime.fromtimestamp(v, timezone.utc)) if isinstance(v, (int, float)) else None


def sandbox_wire(raw: dict | None) -> dict:
    """沙盒服务的原始状态 → 客户端字段。None = 连不上。"""
    if raw is None:
        return {"state": "unreachable"}
    state = raw.get("state") if raw.get("state") in ("running", "stopped", "none") else "none"
    return {"state": state, "memory_used": raw.get("memory_used"), "memory_limit": raw.get("memory_limit"),
            "started_at": _ts(raw.get("started_at")), "last_used_at": _ts(raw.get("last_used")),
            "idle_minutes": raw.get("idle_minutes"), "outdated": bool(raw.get("outdated")),
            # v1.74 我们停的才有：idle 空闲休眠 / room 给其它工作区腾内存（沙盒服务重启后不记得，为 null）
            "stopped_by": raw.get("stopped_by") if state == "stopped" and raw.get("stopped_by") in WAKE_TEXT else None,
            "stopped_at": _ts(raw.get("stopped_at")) if state == "stopped" else None,
            "cpu_percent": raw.get("cpu_percent"), "oom_kills": int(raw.get("oom_kills") or 0),
            "processes": [p for p in (raw.get("processes") or []) if isinstance(p, dict)][:PROCESS_MAX]}


running_jobs = jobs.running  # v2.00 搬到 jobs.running（memory_view 也要用，避免 import 环）


async def status(db: AsyncSession, ws: str) -> dict:
    name = await workspaces.name(db, ws)
    if name is None:
        raise LookupError("没有这个工作区")
    try:
        raw = await sandbox_client.status(ws)
    except httpx.HTTPError:
        raw = None
    running = await running_jobs(db, ws)
    root = project_dir(ws)
    parts = await asyncio.to_thread(storage_breakdown, root, {j.id for j in running})
    used = sum(parts[k] for k in ("files", "installed", "logs", "spill", "cache"))
    q = quota.remember(ws, used, parts["partial"])  # 刚数过的就是最新的：顺手喂给配额缓存
    ports: list[dict] = []
    usage: dict[str, dict] = {}
    if raw is not None and raw.get("state") == "running":
        try:
            ports = (await preview.listening(ws))["ports"]
        except preview.PreviewError:
            pass
        usage = await job_usage.for_jobs(running)  # v1.90 每个任务占多少（一次沙盒请求问齐）
    return {**q.wire(), "ports": ports, "workspace": ws, "name": name, "sandbox": sandbox_wire(raw), "disk_used": used,
            "disk_partial": parts.pop("partial"), "storage": parts,
            "tools": await asyncio.to_thread(installed_tools, root),
            # v1.82 常驻服务单独一节（services.py：健康、端口、手动重启），running_jobs 只剩普通后台任务
            "running_jobs": [{**jobs.wire(j, chars=600), "usage": usage.get(j.id)} for j in running if not j.keep_alive],
            "services": await services.listing(db, ws, running, ports, usage),
            "memory": memory_view.build(raw, running, usage),  # v1.94 内存去哪了（memory_view.py）
            # v1.98 谁写得最多：任务本身（disk 带结算账）+ log_kept 日志还在（一键清理能腾出那份）
            "disk_jobs": [{**jobs.wire(j, chars=200), "log_kept": kept} for j, kept in await job_disk.leaders(db, ws)],
            # v2.85 整台服务器一行（machine.py）：只在个人工作区给，项目的电脑页不重复
            "machine": await asyncio.to_thread(machine.read, settings.data_dir) if workspaces.is_personal(ws) else None}


def _remove(p: Path) -> int:
    n = disk_usage(p)[0] if p.is_dir() else (p.stat().st_size if p.is_file() else 0)
    shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    return n


def clean_disk(root: Path, running: set[str]) -> int:
    """删能安全删的，返回腾出的字节。运行中任务的目录、用户文件、装的包一律不碰。"""
    freed = _remove(root / ".spill") + _remove(root / CACHE)
    for d in _children(root / jobs.JOBS_DIR):
        if d.name not in running:
            freed += _remove(d)
    return freed


async def cleanup(db: AsyncSession, ws: str) -> dict:
    """一键清理 → {freed, status}。沙盒连不上也照清工作区（只是容器缓存那份没清）。"""
    if await workspaces.name(db, ws) is None:
        raise LookupError("没有这个工作区")
    running = {j.id for j in await running_jobs(db, ws)}
    freed = await asyncio.to_thread(clean_disk, project_dir(ws), running)
    quota.forget(ws)
    try:
        freed += await sandbox_client.cleanup(ws)
    except httpx.HTTPError:
        pass
    return {"freed": freed, "status": await status(db, ws)}


async def restart(db: AsyncSession, ws: str) -> dict:
    """停后台任务 → 删容器 → 常驻任务排队重启（v1.80）。沙盒连不上就整件不做（抛 ComputerError），不留半截状态。"""
    if await workspaces.name(db, ws) is None:
        raise LookupError("没有这个工作区")
    try:
        await sandbox_client.status(ws)  # 先确认沙盒服务在，免得任务停了一半
    except httpx.HTTPError as e:
        raise ComputerError("沙盒服务连不上，没能重启") from e
    for job in await running_jobs(db, ws):
        if job.keep_alive:
            continue  # 常驻任务不停：容器删了之后马上排队重启（像开机自启的服务）
        try:
            await jobs.stop(db, job, "user")
        except jobs.JobError as e:
            raise ComputerError(str(e)) from e
    try:
        await sandbox_client.restart(ws)
    except httpx.HTTPError as e:
        raise ComputerError("沙盒服务没响应，没能重启") from e
    job_usage.forget(ws)
    for job in await running_jobs(db, ws):  # 容器删了，进程肯定没了
        if job.keep_alive:
            await jobs.after_restart(db, job)
        else:
            await jobs.settle(db, job, *(jobs.observe(job) or ("lost", None)))
    return await status(db, ws)
