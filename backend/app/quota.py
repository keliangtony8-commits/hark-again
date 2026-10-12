"""工作区磁盘配额的唯一规则（v1.31，对标 Hark：每段对话背后那台云电脑的磁盘有上限，满了要说清楚，而不是把整台 VPS 撑爆）。

一个工作区（项目 / 个人“me”）算一份：用户文件 + 装的软件（.home）+ 任务日志（.jobs）+ 长输出存档（.spill）+ 缓存，
就是“我的电脑”页“磁盘”那一节的总数。上限 settings.workspace_disk_mb（0 = 不限）。
  ok     < 85%
  tight  ≥ 85%：写入照常，工具结果里提醒模型少落大文件、用完清理；页面上条变警示色
  full   ≥ 100%：拒绝新写入——write_file、上传、存成文件、启动后台任务；正在跑的后台任务被护栏停掉（jobs.guard_reason），
         前台命令照跑（删文件、看占用都得靠它），但结果里明说满了、该删什么。
沙盒容器本身不设磁盘硬限（Docker 的 storage-opt 需要 xfs+pquota，学生 VPS 的 ext4 用不了），所以靠这里“写之前查、跑的时候盯”。

数一遍工作区要遍历文件（node_modules 能有几十万个），所以按工作区缓存 CACHE_SECONDS 秒；
后端自己写了文件 / 清理过就 forget(ws)，下次重数。所有函数都是同步的（会碰磁盘），异步代码里用 asyncio.to_thread 调。
"""
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .config import settings
from .storage import project_dir

DISK_SCAN_MAX = 200_000  # 最多数这么多个文件，超过标 partial（只会少算，不会误判满）
TIGHT = 0.85
CACHE_SECONDS = 30

_cache: dict[str, tuple[float, int, bool]] = {}


class QuotaError(RuntimeError):
    """给模型 / 用户看的中文原因（满了写不进）。"""


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


def limit_bytes() -> int:
    return max(0, int(settings.workspace_disk_mb)) * 1024 * 1024


def size_text(n: int) -> str:
    """配额用的粗粒度大小：3 GB / 512 MB / 20 KB（与客户端 formatSize 同一习惯，去掉 .0）。"""
    for unit, k in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= k:
            v = f"{n / k:.1f}".removesuffix(".0")
            return f"{v} {unit}"
    return f"{n} B"


@dataclass(frozen=True)
class Quota:
    used: int
    limit: int  # 0 = 不限
    partial: bool = False

    @property
    def level(self) -> str:
        if not self.limit:
            return "off"
        r = self.used / self.limit
        return "full" if r >= 1 else "tight" if r >= TIGHT else "ok"

    @property
    def free(self) -> int | None:
        return None if not self.limit else max(0, self.limit - self.used)

    def wire(self) -> dict:
        return {"disk_limit": self.limit or None, "disk_level": self.level}

    def fits(self, adding: int) -> bool:
        return not self.limit or self.used + max(0, adding) <= self.limit


def state(ws: str, fresh: bool = False) -> Quota:
    now = time.monotonic()
    hit = _cache.get(ws)
    if fresh or hit is None or now - hit[0] > CACHE_SECONDS:
        used, partial = disk_usage(project_dir(ws))
        hit = _cache[ws] = (now, used, partial)
    return Quota(hit[1], limit_bytes(), hit[2])


def remember(ws: str, used: int, partial: bool = False) -> Quota:
    """别处刚完整数过一遍（电脑页的磁盘拆分）：直接记下，省得再数。"""
    _cache[ws] = (time.monotonic(), used, partial)
    return Quota(used, limit_bytes(), partial)


def forget(ws: str | None = None) -> None:
    """后端自己改了工作区（写文件、清理、删项目）后调：下次重数。不给 ws = 全清。"""
    if ws is None:
        _cache.clear()
    else:
        _cache.pop(ws, None)


def full_reason(q: Quota) -> str:
    return (f"工作区磁盘满了（已用 {size_text(q.used)}，上限 {size_text(q.limit)}）。"
            "先删掉不要的文件、清理任务日志和缓存（“我的电脑”页一键清理），再继续")


def check(ws: str, adding: int = 0) -> None:
    """写入前查：放不下就抛 QuotaError。adding = 这次要写的字节数（覆盖同名文件时也按全量算，宁可保守）。"""
    q = state(ws)
    if not q.fits(adding):
        raise QuotaError(full_reason(q) if q.level == "full" else
                         f"放不下：这次要写 {size_text(adding)}，工作区只剩 {size_text(q.free or 0)}"
                         f"（上限 {size_text(q.limit)}）。先删掉不要的文件再写")


def job_reason(ws: str) -> str | None:
    """后台任务护栏用：满了返回停掉的原因（会记进 stop_reason，卡片上给用户看）。"""
    q = state(ws)
    return f"工作区磁盘超过上限 {size_text(q.limit)}，防止撑爆服务器" if q.level == "full" else None


def model_note(ws: str, fresh: bool = False) -> str:
    """跑完命令后附给模型的一句：满了 / 快满了才有，否则空串。"""
    q = state(ws, fresh)
    if q.level == "full":
        return (f"\n（注意：{full_reason(q)}。现在写文件、启动后台任务都会被拒绝；用 du -sh * .[!.]* | sort -h 找大头，"
                "删掉中间产物，并告诉用户。）")
    if q.level == "tight":
        return (f"\n（提醒：工作区磁盘快满了：已用 {size_text(q.used)} / 上限 {size_text(q.limit)}。"
                "别再落大文件，用完的中间产物顺手删掉。）")
    return ""
