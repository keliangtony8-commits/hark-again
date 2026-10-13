"""v2.35 后台 / 常驻任务的唯一“启动观察”规则（E2E B11）：run_command 起了后台任务后先看它 ~2 秒再回话。

问题（真模型 E2E t2）：服务 41 ms 就 exit 1（端口被占），工具却回“已在后台启动”，模型去 preview_port、换文件重启又撞同样的墙。
真环境一样会有：语法错、缺模块、配置错，一启动就退出。

规则：
  - 启动后最多等 WATCH_S 秒，每 POLL_S 秒看一次磁盘上的退出码（jobs.observe，不打沙盒接口）。
  - 期间退出了 → 现场结算，工具直接回结论 + 退出码 + 日志尾；followup 置 seen（模型已经从工具结果知道了，不再事后叫醒一次）。
    常驻任务启动即崩（非零 / OOM）不进自动重启：这种崩每次重启都一样（端口占用、语法错），拉起 6 次只会刷日志吃 CPU，
    直接结算为失败，交给模型看日志修。常驻任务正常退出（0）照普通结束。
  - 还活着 → 照旧在后台跑，工具结果附上已有的前几行输出（服务的“Listening on …”、启动报警）。
  - 观察期间别的会话（worker）抢先结算了：以库里为准，只把它待发的通知改成 seen。
参考：Codex unified exec 的 yield_time（起进程后先等一会儿，跑完了直接带结果回，否则回会话 id）；
      Gemini CLI 后台命令先看启动输出再交还控制。只借语义，代码自写。
"""
import asyncio
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from . import job_restart, jobs
from .models import Job

WATCH_S = 2.0      # 最多观察多久（秒）；测试里可调小 / 置 0 关掉
POLL_S = 0.25      # 多久看一次
SHOW_CHARS = 1500  # 回给模型的日志尾巴


@dataclass(frozen=True)
class Startup:
    exited: bool       # 观察期内已经结束（任务已结算）
    output: str        # 到目前为止的输出尾巴（可能为空）


def crash_reason(code: int | None) -> str:
    return f"刚启动就退出了（退出码 {code}），没有自动重启" if code is not None else "刚启动就退出了，没有自动重启"


async def watch(db: AsyncSession, job: Job) -> Startup:
    """看它 WATCH_S 秒：退出了就结算（见模块说明）。返回结论供 run_command 组织话术。"""
    waited = 0.0
    while (obs := jobs.observe(job)) is None and waited < WATCH_S:
        await asyncio.sleep(POLL_S)
        waited += POLL_S
    if obs is None:
        return Startup(False, (await asyncio.to_thread(jobs.log_tail, job, SHOW_CHARS)).strip())
    await db.refresh(job)
    if job.state == "running":
        state, code = obs
        if job.keep_alive and job_restart.unexpected(state):
            job.stop_reason = job.stop_reason or crash_reason(code)
            state = "failed"
        job.followup = "seen"  # settle 只在 none 时置 pending：先置 seen，模型从这次工具结果就知道了
        await jobs.settle(db, job, state, code)
    elif job.followup == "pending":
        job.followup = "seen"
        await db.commit()
    return Startup(True, (job.tail or "").strip()[-SHOW_CHARS:])


def text(job: Job, s: Startup) -> str:
    """已退出时给模型的话（还活着的话术在 run_command：照旧 + 附输出）。"""
    out = s.output or "（没有输出）"
    if job.state == "done":
        return f"后台任务 {job.id}「{job.title}」已经跑完了（退出码 0），不会再有结束通知。输出：\n{out}"
    why = job.stop_reason or jobs.LABELS.get(job.state, job.state)
    code = f"退出码 {job.exit_code}" if job.exit_code is not None else "没有退出码"
    return (f"后台任务 {job.id}「{job.title}」没在跑：启动不到 {WATCH_S:g} 秒就结束了（{jobs.LABELS.get(job.state, job.state)}，{code}"
            f"{'；' + why if job.stop_reason else ''}）。日志最后几行：\n{out}\n"
            "先按日志把问题修好再重新启动（端口被占就换一个端口），别对它用 preview_port / job_status，它已经不在了。")


def alive_note(s: Startup) -> str:
    return f"\n已经有的输出：\n{s.output}" if s.output else ""
