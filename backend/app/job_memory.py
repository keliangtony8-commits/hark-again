"""后台任务的内存规则（v1.92，CORE 19）——唯一入口。4 GB 的小 VPS 上，一个跑飞的任务把整台沙盒内存吃满时，
内核会随手杀进程，常驻的网站 / bot 也可能被带走。这里三层：

  1. 先保服务（零开销）：普通后台任务 run.sh 把 oom_score_adj 调高 jobs.OOM_ADJ，内核挑人时先挑它们（jobs.script）。
  2. 单任务上限（systemd MemoryMax 的语义）：run_command memory_limit="512m" → Job.memory_max；worker 每轮（5 秒）
     采样（job_usage，一个工作区一次沙盒请求），超了就先写 jobs.MEMCAP 标记（内容 = 原因）再整组杀：
     结论“失败：内存超过给它定的上限 …”（普通任务）；常驻服务照崩溃处理，按 job_restart 退避重启（同 systemd Restart=on-failure）。
     沙盒连不上 → 撤回标记，下一轮再来。
  3. 提前提醒：采样顺带记 memory_peak（峰值，结论里写给人和模型）；任务到自己上限 NEAR 以上、或整台沙盒用到 TIGHT 以上，
     job_status 的文字和任务卡上会提示（不另外叫醒模型——省 token）。

parse(v) 接受 "512m" / "2g" / "1.5GB" / "800MiB" / 纯数字（按 MB），夹在 MIN–MAX 之间，不合法抛 ValueError（中文原因）。
采样节奏：工作区里有设了上限的任务 → 每轮都采；否则每 PEAK_EVERY_S 秒采一次（只为记峰值）。

参考：deepseek-harness / Codex / Gemini CLI 都在本机跑命令，没有逐任务内存上限（Codex 的 Linux 沙盒只管文件/网络），
无代码可搬；语义借 systemd（MemoryMax + Restart=on-failure）、Kubernetes（limit 超了 OOMKilled、按 restartPolicy 重启）、
Linux oom_score_adj（调高不需要特权）。没用 ulimit -v：限的是虚拟地址空间，node / JVM / CUDA 一启动就超，误杀多。
"""
import re
import time

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import job_usage, jobs, quota, sandbox_client
from .models import Job

MIN = 64 << 20
MAX = 64 << 30
NEAR = 0.8           # 到自己上限的这个比例就提醒
TIGHT = 0.9          # 整台沙盒用到这个比例就提醒
PEAK_EVERY_S = 15.0  # 没设上限的工作区多久采一次（记峰值、看整台）
PEAK_STEP = 1.05     # 峰值涨过 5% 才写库（别每轮都写）

_UNITS = {"": 1 << 20, "k": 1 << 10, "m": 1 << 20, "g": 1 << 30, "t": 1 << 40}
_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kmgt]?)(?:i?b)?\s*$", re.I)
_sampled: dict[str, float] = {}


def parse(v) -> int | None:
    """memory_limit 参数 → 字节；空 / 0 / None → None（不设限）。"""
    if v is None or v == "" or v == 0:
        return None
    if isinstance(v, bool):
        raise ValueError("memory_limit 要写成 512m、2g 这样的大小")
    if isinstance(v, (int, float)):
        n = int(v * (1 << 20))
    else:
        m = _RE.match(str(v))
        if not m:
            raise ValueError("memory_limit 要写成 512m、2g 这样的大小")
        n = int(float(m.group(1)) * _UNITS[m.group(2).lower()])
    if n == 0:
        return None
    if n < MIN:
        raise ValueError(f"memory_limit 太小（至少 {quota.size_text(MIN)}）")
    if n > MAX:
        raise ValueError(f"memory_limit 太大（最多 {quota.size_text(MAX)}）")
    return n


def reason(cap: int, used: int) -> str:
    return f"{jobs.MEMCAP_PREFIX} {quota.size_text(cap)}（当时约 {quota.size_text(used)}），已强制结束"


def over(job: Job, usage: dict | None) -> bool:
    return bool(job.memory_max and usage and usage["memory"] > job.memory_max)


def near(job: Job, usage: dict | None) -> bool:
    return bool(job.memory_max and usage and usage["memory"] >= job.memory_max * NEAR)


def tight(box: dict | None) -> bool:
    return bool(box and box["used"] >= box["limit"] * TIGHT)


def note(job: Job, usage: dict | None) -> str:
    """job_status 里跟在用量后面的一句（设了上限才有）。"""
    if not job.memory_max:
        return ""
    if usage and near(job, usage):
        pct = round(usage["memory"] * 100 / job.memory_max)
        return f"（上限 {quota.size_text(job.memory_max)}，已到 {pct}%，再涨会被结束）"
    return f"（上限 {quota.size_text(job.memory_max)}）"


def box_note(box: dict | None, biggest: tuple[Job, dict] | None = None) -> str:
    """整台沙盒快满时给模型的一句；不紧张返回空。"""
    if not tight(box):
        return ""
    pct = round(box["used"] * 100 / box["limit"])
    who = ""
    if biggest:
        j, u = biggest
        who = f"，最大的是后台任务 {j.id}「{j.title}」约 {quota.size_text(u['memory'])}"
    return (f"注意：这台电脑内存已用 {pct}%（{quota.size_text(box['used'])} / {quota.size_text(box['limit'])}）{who}。"
            "再涨系统会强制结束进程（先结束普通后台任务，尽量保住常驻服务）；能停的先停，或给大任务设 memory_limit。")


def biggest(rows: list[Job], usage: dict[str, dict]) -> tuple[Job, dict] | None:
    best = max((j for j in rows if j.id in usage), key=lambda j: usage[j.id]["memory"], default=None)
    return (best, usage[best.id]) if best else None


def _due(rows: list[Job], now: float) -> list[Job]:
    """这一轮要采样的任务：有上限的工作区每轮，其余按 PEAK_EVERY_S。"""
    by_ws: dict[str, list[Job]] = {}
    for j in rows:
        by_ws.setdefault(j.project_id, []).append(j)
    out = []
    for ws, js in by_ws.items():
        if any(j.memory_max for j in js) or now - _sampled.get(ws, 0.0) >= PEAK_EVERY_S:
            _sampled[ws] = now
            out += js
    return out


async def _kill(db: AsyncSession, job: Job, used: int) -> bool:
    marker = jobs.job_dir(job) / jobs.MEMCAP
    try:
        marker.write_text(reason(job.memory_max, used), encoding="utf-8")
    except OSError:
        return False
    try:
        await sandbox_client.cancel_job(job.project_id, job.id)
    except httpx.HTTPError:
        marker.unlink(missing_ok=True)  # 没杀成：别让它后来正常退出也被算成超限
        return False
    await jobs.refresh(db, job)  # 杀完多半已写了退出码：普通任务结算，常驻服务排队重启
    return True


async def tick(db: AsyncSession) -> list[str]:
    """worker 每轮调：采样 → 记峰值 → 超上限的结束掉。返回这次因超限被结束的任务 id。"""
    rows = [j for j in (await db.scalars(select(Job).where(Job.state == "running"))).all() if job_usage.live(j)]
    rows = _due(rows, time.monotonic())
    if not rows:
        return []
    usage = await job_usage.for_jobs(rows)
    dirty, killed = False, []
    for j in rows:
        u = usage.get(j.id)
        if not u:
            continue
        if u["memory"] > (j.memory_peak or 0) * PEAK_STEP:
            j.memory_peak, dirty = u["memory"], True
        if over(j, u):
            if dirty:
                await db.commit()
                dirty = False
            if await _kill(db, j, u["memory"]):
                killed.append(j.id)
    if dirty:
        await db.commit()
    return killed


def forget() -> None:
    """测试用：清掉采样节奏记录。"""
    _sampled.clear()
