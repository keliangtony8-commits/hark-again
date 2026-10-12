"""常驻服务（keep_alive 后台任务，v1.80）的“健康”视图和手动重启（v1.82）——唯一入口：
  - health(job)：up 在跑 / restarting 进程退出了、等自动重启 / gave_up 连续崩溃放弃了（或别的意外结束）。
  - listing(db, ws, ports)：“这台电脑”里的常驻服务一节：在跑的 + 最近 GONE_HOURS 小时里意外结束的（放弃了不能悄悄消失），
    每个带本次运行多久、它在监听哪些端口（端口的进程组 = run.sh 记下的 pid，即 timeout 那个组长）。
  - restart(db, job)：在跑 → 整组杀掉后马上重新起（改了代码/配置要生效）；等重启中 → 不等了现在起；
    已结束 → 重新拉起（清掉崩溃计数，像 systemctl reset-failed + start）。不算崩溃、不通知助手。
规则（什么算意外、等多久、何时放弃）仍只在 job_restart.py；启动/杀/结算仍只在 jobs.py。

参考（只借语义）：systemd `systemctl restart`（运行中先停再起）/ `reset-failed`（放弃之后手动清零再起），
PM2 `pm2 restart` 计入 restarts，Docker `docker restart`。deepseek-harness / Codex / Gemini CLI 没有服务监护，无代码可搬。
"""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import job_usage, jobs, quota, sandbox_client
from .config import settings
from .models import Job

GONE_HOURS = 24      # 意外结束的服务在“这台电脑”里留多久（让用户看见、点“重新启动”）
LIST_MAX = 10
KILL_WAIT_S = 4.0    # 杀完等 run.sh 写出退出码的上限（沙盒的整组杀本身最多等 5 秒才 KILL）
HOLD_S = 15          # 手动重启期间先把 restart_at 推到这么久以后：worker 这段时间不会抢着结算/拉起
GONE_STATES = ("failed", "lost", "timed_out")


class ServiceError(RuntimeError):
    """给用户/模型看的中文原因。"""


def health(job: Job) -> str:
    if job.state == "running":
        return "restarting" if job.restart_at is not None else "up"
    return "gave_up"


def owned_ports(job: Job, ports: list[dict]) -> list[int]:
    """这个服务在监听的端口：端口进程的进程组 = 任务的组长 pid。等重启中的不算（进程已经没了，pid 可能被复用）。"""
    if health(job) != "up" or (g := job_usage.pgid(job)) is None:
        return []
    return sorted({p["port"] for p in ports if p.get("pgid") == g})


def wire(job: Job, ports: list[dict], now: datetime | None = None, usage: dict | None = None) -> dict:
    h = health(job)
    return {**jobs.wire(job, chars=600), "health": h, "ports": owned_ports(job, ports), "usage": usage,
            "uptime": int(jobs.run_seconds(job, now)) if h == "up" else None, "crash_streak": job.crash_streak or 0}


async def listing(db: AsyncSession, ws: str, running: list[Job], ports: list[dict],
                  usage: dict[str, dict] | None = None) -> list[dict]:
    """running = computer.running_jobs 刚对过的运行中任务（省一次查询）。在跑的在前（新的在前），再是意外结束的。
    usage = job_usage.for_jobs 的结果（v1.90，computer.status 一次问齐）。"""
    since = datetime.now(timezone.utc) - timedelta(hours=GONE_HOURS)
    gone = (await db.scalars(select(Job).where(Job.project_id == ws, Job.keep_alive.is_(True),
                                               Job.state.in_(GONE_STATES), Job.finished_at >= since)
                             .order_by(Job.finished_at.desc()).limit(LIST_MAX))).all()
    rows = [j for j in running if j.keep_alive] + list(gone)
    return [wire(j, ports, usage=(usage or {}).get(j.id)) for j in rows[:LIST_MAX]]


async def restart(db: AsyncSession, job: Job) -> Job:
    """手动重启一个常驻服务（见模块说明）。不是常驻任务 / 用户停掉的 / 名额或磁盘不够 → ServiceError。"""
    if not job.keep_alive:
        raise ServiceError("只有常驻服务（keep_alive）能重启；普通任务请重新跑一次命令")
    await jobs.refresh(db, job)
    if job.state == "running":
        if job.restart_at is None:
            await _kill_for_restart(db, job)
        job.crash_streak, job.restart_at = 0, datetime.now(timezone.utc)
        await db.commit()
        return job
    if job.state not in GONE_STATES:
        raise ServiceError("它已经被停掉了（不是意外退出），要用请重新启动一个")
    if (n := await jobs.running_count(db, job.project_id)) >= settings.job_max_running:
        raise ServiceError(f"这个工作区已有 {n} 个后台任务在跑（上限 {settings.job_max_running}），先停一个再重启")
    try:
        await asyncio.to_thread(quota.check, job.project_id)
    except quota.QuotaError as e:
        raise ServiceError(str(e)) from e
    (jobs.job_dir(job) / "cancelled").unlink(missing_ok=True)
    job.state, job.finished_at, job.stop_reason, job.exit_code = "running", None, None, None
    job.crash_streak, job.followup, job.followup_at = 0, "none", None
    job.restart_at = datetime.now(timezone.utc)  # worker 下一轮（≤5 秒）跑 _relaunch：清结论文件、插分隔行、叫沙盒
    await jobs.patch_blocks(db, job)
    await db.commit()
    return job


async def _kill_for_restart(db: AsyncSession, job: Job) -> None:
    """在跑的先整组杀掉。期间 restart_at 先推到 HOLD_S 秒后：worker 看到它就不会把这次退出当崩溃结算、也不会提前拉起；
    等 run.sh 写出退出码（或进程确实没了）再把 restart_at 拉回现在——不然旧 run.sh 晚写的 exit 会把新进程判成结束。"""
    job.restart_at = datetime.now(timezone.utc) + timedelta(seconds=HOLD_S)
    await db.commit()
    try:
        await sandbox_client.cancel_job(job.project_id, job.id)
    except Exception as e:  # noqa: BLE001 — httpx 错误或沙盒异常：撤回，状态不动
        job.restart_at = None
        await db.commit()
        raise ServiceError("沙盒没响应，没能重启，稍后再试") from e
    loop = asyncio.get_running_loop()
    deadline = loop.time() + KILL_WAIT_S
    while jobs.observe(job) is None and loop.time() < deadline:
        await asyncio.sleep(0.2)

