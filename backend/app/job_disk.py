"""每个后台任务占了多少磁盘（v1.96）——唯一入口。对标 Manus / Hark 云电脑：小 VPS 的磁盘配额有限（quota.py），
“我的电脑”页只能说清“哪一类东西大”（用户文件 / 装的软件 / 任务日志……），这里补上“是哪个任务写的”：
npm install 写了 300 MB node_modules、爬虫落了 2 GB 图片、训练脚本每轮存一份 checkpoint，用户和助手都得看得出来。

一个任务的磁盘账 = 两部分：
  - log：它自己的 .jobs/<id>/（日志 + log.1 轮转尾巴 + 标记文件），确定是它的；
  - written：它运行期间（created_at − SLACK_S 到结束 + SLACK_S）工作区里新写或改过的文件（按 mtime），
    按顶层条目分组（目录带“/”，.home/ = 装的软件），给最大的 TOP_MAX 组。跳过 SKIP（.jobs 已算进 log；.spill/.turns/.git 是后端自己的）。
    改过的文件按全量算（说“新写或改过”，不说“新增”）；不跟随符号链接；最多数 quota.DISK_SCAN_MAX 个文件，超过标 partial。
  - overlap：同一工作区同时段还在跑的其他后台任务个数。mtime 分不清是谁写的，所以有重叠时明说“可能包含它们写的”，不装精确
    （前台命令、助手自己写的文件同理，措辞是“运行期间工作区里”）。

什么时候数：结算时（jobs.settle）数一次存进 jobs.disk（JSON，之后文件被删也不改，是“当时的账”）；
运行中的任务按需数（任务卡轮询 / job_status），每个任务 CACHE_S 秒内用缓存（遍历工作区要碰磁盘）。
同步函数会碰磁盘，异步代码里用 asyncio.to_thread 调。
v1.98 leaders(db, ws)：“我的电脑”页磁盘一节的“谁写得最多”——最近 WINDOW_DAYS 天结束的任务按结算账（written + log）排前 LEADERS_MAX，
只读库里存的账、不重新遍历工作区（页面每次打开都调）；第二项 = 日志目录还在（一键清理能腾出 log 那份，written 是用户文件，不清）。

参考：deepseek-harness / Codex / Gemini CLI 都在本机跑命令，没有逐任务磁盘账，无代码可搬（core-research.md CORE 21）；
口径借 `find -newermt`（按修改时间圈出一段时间内写的文件）+ `du`（按顶层目录汇总）。
"""
import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import quota
from .models import Job
from .storage import project_dir

SLACK_S = 2          # mtime 精度 / 时钟抖动的余量
TOP_MAX = 3          # 给几组“最大的”
NOTE_MIN = 1 << 20   # 给模型的结论里，写入或日志到这么大才提（太小的不占篇幅）
CACHE_S = 30
SKIP = frozenset({".jobs", ".spill", ".turns", ".git"})
WINDOW_DAYS = 7
LEADERS_MAX = 5
LEADERS_SCAN = 500   # 窗口里最多看这么多个结束的任务（按结束时间倒序；正常远不到）
FIELDS = ("log", "written", "files", "top", "overlap", "partial")

_cache: dict[str, tuple[float, dict]] = {}


def _aware(v: datetime) -> datetime:
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def scan(root: Path, since: float, until: float | None, limit: int = quota.DISK_SCAN_MAX) -> tuple[dict[str, int], int, bool]:
    """({顶层条目: 字节}, 文件数, partial)：mtime 落在 [since, until] 的普通文件（until=None 不设上限）。"""
    groups: dict[str, int] = {}
    files = seen = 0
    try:
        top = list(os.scandir(root))
    except OSError:
        return groups, 0, False
    stack: list[tuple[str, str]] = []
    for e in top:
        if e.name in SKIP:
            continue
        try:
            if e.is_dir(follow_symlinks=False):
                stack.append((e.path, e.name + "/"))
                continue
            if not e.is_file(follow_symlinks=False):
                continue
            st = e.stat(follow_symlinks=False)
        except OSError:
            continue
        seen += 1
        if st.st_mtime >= since and (until is None or st.st_mtime <= until):
            groups[e.name] = groups.get(e.name, 0) + st.st_size
            files += 1
    while stack:
        path, key = stack.pop()
        try:
            with os.scandir(path) as it:
                for e in it:
                    seen += 1
                    if seen > limit:
                        return groups, files, True
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append((e.path, key))
                        elif e.is_file(follow_symlinks=False):
                            st = e.stat(follow_symlinks=False)
                            if st.st_mtime >= since and (until is None or st.st_mtime <= until):
                                groups[key] = groups.get(key, 0) + st.st_size
                                files += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return groups, files, False


def measure(ws_root: Path, job_root: Path, start: datetime, end: datetime | None, overlap: int = 0) -> dict:
    log, _ = quota.disk_usage(job_root)
    since = _aware(start).timestamp() - SLACK_S
    until = _aware(end).timestamp() + SLACK_S if end else None
    groups, files, partial = scan(ws_root, since, until)
    top = sorted(groups.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_MAX]
    return {"log": log, "written": sum(groups.values()), "files": files,
            "top": [{"path": p, "size": s} for p, s in top if s > 0], "overlap": max(0, overlap), "partial": partial}


def wire(d) -> dict | None:
    """校验一份磁盘账（库里存的 / 刚数的）；坏的 → None。"""
    if isinstance(d, str):
        try:
            d = json.loads(d)
        except ValueError:
            return None
    if not isinstance(d, dict):
        return None
    try:
        out = {k: int(d[k]) for k in ("log", "written", "files", "overlap")}
        top = [{"path": str(t["path"]), "size": int(t["size"])} for t in d.get("top") or []
               if isinstance(t, dict) and t.get("path")][:TOP_MAX]
    except (KeyError, TypeError, ValueError):
        return None
    if min(out.values()) < 0:
        return None
    return {**out, "top": top, "partial": bool(d.get("partial"))}


def group_name(path: str) -> str:
    return "装的软件（.home）" if path == ".home/" else path


def text(d: dict | None, brief: bool = False) -> str:
    """给模型的一句。brief（结论 / 通知里用）：写入和日志都小于 NOTE_MIN 就不提。"""
    if not d or (brief and d["written"] < NOTE_MIN and d["log"] < NOTE_MIN):
        return ""
    s = quota.size_text
    if d["files"]:
        tops = "、".join(f"{group_name(t['path'])} {s(t['size'])}" for t in d["top"])
        out = f"运行期间工作区里新写或改过 {d['files']} 个文件，共 {s(d['written'])}" + (f"（最大：{tops}）" if tops else "")
        if d["partial"]:
            out += "（文件太多只数了一部分，实际可能更多）"
        if d["overlap"]:
            out += f"（同时段还有 {d['overlap']} 个任务在跑，可能包含它们写的）"
    else:
        out = "运行期间工作区里没有新写文件"
    return f"{out}；日志 {s(d['log'])}"


async def overlap(db: AsyncSession, job: Job, end: datetime | None) -> int:
    """同一工作区与它运行时段重叠的其他后台任务个数。"""
    q = select(func.count()).select_from(Job).where(Job.project_id == job.project_id, Job.id != job.id,
                                                    or_(Job.finished_at.is_(None), Job.finished_at >= job.created_at))
    if end is not None:
        q = q.where(Job.created_at <= end)
    return int(await db.scalar(q) or 0)


def _job_root(job: Job) -> Path:
    return project_dir(job.project_id) / ".jobs" / job.id


async def record(db: AsyncSession, job: Job) -> None:
    """结算时调（jobs.settle，提交之前）：数一次存进 jobs.disk。数不了（工作区没了）就不存。"""
    if not project_dir(job.project_id).is_dir():
        return
    n = await overlap(db, job, job.finished_at)
    d = await asyncio.to_thread(measure, project_dir(job.project_id), _job_root(job), job.created_at, job.finished_at, n)
    job.disk = json.dumps(d, ensure_ascii=False)
    _cache.pop(job.id, None)


async def of(db: AsyncSession, job: Job) -> dict | None:
    """结束了：结算时存的账（老任务没有 → None）；运行中：现数（有缓存）。"""
    if job.state != "running":
        return wire(job.disk) if job.disk else None
    hit = _cache.get(job.id)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    if not project_dir(job.project_id).is_dir():
        return None
    n = await overlap(db, job, None)
    d = await asyncio.to_thread(measure, project_dir(job.project_id), _job_root(job), job.created_at, None, n)
    _cache[job.id] = (time.monotonic(), d)
    return d


def stored(job: Job) -> dict | None:
    """同步读结算时存的账（describe / block 用）。"""
    return wire(job.disk) if job.state != "running" and job.disk else None


def total(d: dict) -> int:
    return d["written"] + d["log"]


async def leaders(db: AsyncSession, ws: str, now: datetime | None = None) -> list[tuple[Job, bool]]:
    """最近 WINDOW_DAYS 天结束的任务里，磁盘账（written + log）最大的 LEADERS_MAX 个 → [(任务, 日志目录还在)]；账为 0 / 坏的不列。"""
    since = (now or datetime.now(timezone.utc)) - timedelta(days=WINDOW_DAYS)
    rows = (await db.scalars(select(Job).where(Job.project_id == ws, Job.state != "running", Job.disk.is_not(None),
                                               Job.finished_at >= since)
                             .order_by(Job.finished_at.desc()).limit(LEADERS_SCAN))).all()
    ranked = [(total(d), job) for job in rows if (d := wire(job.disk)) is not None and total(d) > 0]
    ranked.sort(key=lambda t: (-t[0], t[1].id))
    return [(job, _job_root(job).is_dir()) for _, job in ranked[:LEADERS_MAX]]


def forget(job_id: str | None = None) -> None:
    if job_id is None:
        _cache.clear()
    else:
        _cache.pop(job_id, None)

