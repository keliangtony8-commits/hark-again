"""每个后台任务现在占多少 CPU / 内存（v1.90）——唯一入口。对标 Manus / Hark 云电脑里“哪个程序在吃资源”：
4 GB 的小 VPS 上，用户和助手都得看得出是哪个任务把内存吃满、把 CPU 拉满，才知道该停哪个。

  - pgid(job)：任务的进程组 = run.sh 写下的 pid（timeout 那个组长；services.owned_ports 也用它）。
  - for_jobs(rows) → {job_id: usage}：只问“进程确实在跑”的任务（running 且不在等重启——等重启时 pid 可能已被复用），
    按工作区合并成一次沙盒请求（sandbox /sandboxes/{id}/groups，沙盒内采样 0.5 秒）；
    CACHE_S 秒内同一工作区同一组 pgid 直接用缓存，并发的请求共用一次（任务卡每 2 秒轮询 + 电脑页轮询不会把沙盒打满）。
    沙盒连不上 / 电脑没开 / 进程已经没了 → 这个任务没有 usage（不是 0）。
  - wire(u)：{cpu 占本沙盒 CPU 配额百分比, cpu_seconds 累计 CPU 秒, memory 字节（PSS）, processes 进程数}。
  - text(u)：给模型的一句（job_status 用），例如“现在占 CPU 35%、内存约 120 MB（3 个进程）”。
采样规则（进程组、PSS、含已收走的子进程节拍）在 sandbox/runner.py GROUPS_PY / group_usage。

参考：deepseek-harness / Codex / Gemini CLI 都在本机跑命令，没有逐任务资源统计，无代码可搬；
口径借 `top`（CPU 按两次采样之差）和 `smem`（PSS 摊共享页）。
"""
import asyncio
import time

import httpx

from . import jobs, sandbox_client
from .models import Job

CACHE_S = 3.0
FIELDS = ("cpu", "cpu_seconds", "memory", "processes")

_cache: dict[str, tuple[float, tuple[int, ...], dict[int, dict]]] = {}
_inflight: dict[tuple[str, tuple[int, ...]], asyncio.Future] = {}


def pgid(job: Job) -> int | None:
    try:
        g = int((jobs.job_dir(job) / "pid").read_text().strip())
    except (OSError, ValueError):
        return None
    return g if g > 0 else None


def live(job: Job) -> bool:
    """进程应该在跑：运行中且没在等自动重启。"""
    return job.state == "running" and job.restart_at is None


def wire(u: dict | None) -> dict | None:
    if not isinstance(u, dict):
        return None
    try:
        out = {"cpu": float(u["cpu"]), "cpu_seconds": float(u["cpu_seconds"]), "memory": int(u["memory"]),
               "processes": int(u["processes"])}
    except (KeyError, TypeError, ValueError):
        return None
    return out if out["processes"] > 0 and min(out.values()) >= 0 else None


def size_text(n: int) -> str:
    if n < 1 << 20:
        return f"{max(1, round(n / 1024))} KB"
    if n < 1 << 30:
        return f"{n / (1 << 20):.0f} MB"
    return f"{n / (1 << 30):.1f} GB"


def text(u: dict | None) -> str:
    if not u:
        return ""
    n = f"（{u['processes']} 个进程）" if u["processes"] > 1 else ""
    return f"现在占 CPU {u['cpu']:g}%、内存约 {size_text(u['memory'])}{n}，累计 CPU {jobs.duration_text(int(u['cpu_seconds']))}"


async def _fetch(ws: str, want: tuple[int, ...]) -> dict[int, dict]:
    hit = _cache.get(ws)
    now = time.monotonic()
    if hit and now - hit[0] < CACHE_S and set(want) <= set(hit[1]):
        return hit[2]
    key = (ws, want)
    if key in _inflight:
        return await asyncio.shield(_inflight[key])
    fut = asyncio.get_running_loop().create_future()
    _inflight[key] = fut
    try:
        try:
            raw = await sandbox_client.groups(ws, list(want))
        except (httpx.HTTPError, ValueError):
            raw = {}
        got = {}
        rows = raw.get("groups") if isinstance(raw, dict) else None
        for r in rows if isinstance(rows, list) else []:
            if isinstance(r, dict) and isinstance(r.get("pgid"), int) and (w := wire(r)) is not None:
                got[r["pgid"]] = w
        _cache[ws] = (time.monotonic(), want, got)
        fut.set_result(got)
        return got
    except BaseException as e:
        fut.set_exception(e)
        fut.exception()  # 别让“没人取的异常”刷日志
        raise
    finally:
        _inflight.pop(key, None)


async def for_jobs(rows: list[Job]) -> dict[str, dict]:
    """{job_id: usage}；拿不到的任务不在结果里。"""
    by_ws: dict[str, dict[int, str]] = {}
    for j in rows:
        if live(j) and (g := pgid(j)) is not None:
            by_ws.setdefault(j.project_id, {})[g] = j.id
    out: dict[str, dict] = {}
    if not by_ws:
        return out
    results = await asyncio.gather(*(_fetch(ws, tuple(sorted(m))) for ws, m in by_ws.items()))
    for (ws, m), got in zip(by_ws.items(), results):
        for g, jid in m.items():
            if g in got:
                out[jid] = got[g]
    return out


async def of(job: Job) -> dict | None:
    return (await for_jobs([job])).get(job.id)


def forget(ws: str | None = None) -> None:
    """测试用 / 电脑重启后：丢掉缓存。"""
    if ws is None:
        _cache.clear()
    else:
        _cache.pop(ws, None)
