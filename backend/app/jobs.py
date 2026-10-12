"""后台任务的唯一入口：在工作区沙盒（项目或个人，见 workspaces.py）里跑超过一条命令时限的活（装依赖、训练、爬取、大构建）。

文件约定（工作区 .jobs/<id>/，沙盒和后端看到的是同一个目录）：
  cmd.sh    用户/模型给的命令原文
  run.sh    包装脚本（script()）：timeout 作为进程组组长在后台跑 cmd.sh，pid 写进 pid，
            输出全进 log，结束把退出码原子地写进 exit
  cancelled 取消标记，内容是谁停的：user | agent | guard（stop() 先写它再叫沙盒整组杀，退出码因此算“已取消”）
沙盒服务只负责启动、查活、整组杀（sandbox/runner.py）；状态从文件读，所以沙盒服务、后端、worker 谁重启都不丢。

护栏（guard_reason()，worker 每轮对运行中的任务查一次）：日志超过 job_log_max_mb → 停（防撑爆磁盘）；
连续 idle_timeout 秒日志没长（mtime 没变；进度条的 \r 刷新也算有输出）→ 判定卡住停掉。停掉的原因记进 stop_reason，
卡片和通知里都写明，助手照常在原对话接着说（它需要知道并决定怎么办）。思路参考了 deepseek-harness（MIT）jobs 的
“kill 带 reason、结算时把原因并进结论”，以及 Codex CLI 的命令无输出超时。

生命周期：start() → running →（文件里出现 exit：observe() / refresh()；或进程没了也没 exit：lost）→ settle()
settle() 记下结论和日志尾巴、把聊天里那张任务卡改成最终状态，并把 followup 置 pending：
worker 的 follow_ups() 随后在原对话里带着结果再跑一轮（像有人告诉助手“你那个任务跑完了”），
模型若已经用 job_status 自己看过结果（followup=seen）就不再打扰。
"""
import secrets
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import sandbox_client
from .config import settings
from .models import Conversation, Job, Message
from .storage import project_dir
from .wire_time import iso

JOBS_DIR = ".jobs"
FINAL = ("done", "failed", "timed_out", "cancelled", "lost")
KEEP_TAIL = 1500        # 结束时存进库/卡片的日志尾巴（字符）
TAIL_CHARS = 4000       # 接口默认给客户端的日志尾巴
LOST_GRACE = 20         # 启动后多少秒内不判“丢失”（沙盒可能还在拉起容器）
FOLLOWUP_WAIT = 600     # 原对话里还有一轮没答完时，最多等多久再接着说
LABELS = {"running": "运行中", "done": "已完成", "failed": "失败", "timed_out": "超时被终止",
          "cancelled": "已取消", "lost": "中断了（沙盒重启或进程消失）"}


class JobError(RuntimeError):
    """给模型/用户看的中文原因。"""


def _aware(v: datetime) -> datetime:
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def new_id() -> str:
    return "j" + secrets.token_hex(6)


def job_dir(job: Job) -> Path:
    return project_dir(job.project_id) / JOBS_DIR / job.id


def script(job_id: str, timeout: int) -> str:
    """run.sh：从工作区根目录跑；timeout 自成进程组（取消时整组杀），-k 5 超时后再给 5 秒强杀。"""
    j = f"{JOBS_DIR}/{job_id}"
    return (
        "#!/bin/bash\n"
        'cd "$(dirname "$0")/../.." || exit 1\n'
        f"J={j}\n"
        f'timeout -k 5 {int(timeout)} bash -l "$J/cmd.sh" > "$J/log" 2>&1 < /dev/null &\n'
        'echo $! > "$J/pid"\n'
        "wait $!\n"
        'echo $? > "$J/exit.tmp" && mv "$J/exit.tmp" "$J/exit"\n'
    )


def observe(job: Job) -> tuple[str, int | None] | None:
    """只看磁盘：结束了返回 (state, 退出码)，还没结束返回 None。"""
    d = job_dir(job)
    try:
        code = int((d / "exit").read_text().strip())
    except (FileNotFoundError, ValueError):
        return None
    if (d / "cancelled").exists():
        return "cancelled", code
    if code == 124:
        return "timed_out", code
    return ("done" if code == 0 else "failed"), code


def _read(p: Path) -> str:
    try:
        return p.read_text().strip()
    except FileNotFoundError:
        return ""


def log_size(job: Job) -> int:
    try:
        return (job_dir(job) / "log").stat().st_size
    except FileNotFoundError:
        return 0


def log_tail(job: Job, chars: int = TAIL_CHARS) -> str:
    """日志最后一段。进度条靠 \\r 原地刷新（pip、wget、tqdm），每行只留最后一次刷新的样子。"""
    p = job_dir(job) / "log"
    try:
        with p.open("rb") as f:
            size = f.seek(0, 2)
            f.seek(max(0, size - chars * 4))  # 中文最多 4 字节一个字
            raw = f.read().decode("utf-8", "replace")
    except FileNotFoundError:
        return ""
    lines = [ln.rsplit("\r", 1)[-1] if "\r" in ln.rstrip("\r") else ln.rstrip("\r") for ln in raw.split("\n")]
    text = "\n".join(lines)
    return text[-chars:] if len(text) > chars else text


def elapsed(job: Job, now: datetime | None = None) -> int:
    end = _aware(job.finished_at) if job.finished_at else (now or datetime.now(timezone.utc))
    return max(0, int((end - _aware(job.created_at)).total_seconds()))


def duration_text(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} 秒"
    if seconds < 3600:
        return f"{seconds // 60} 分钟" if seconds % 60 == 0 else f"{seconds // 60} 分 {seconds % 60} 秒"
    return f"{seconds // 3600} 小时 {seconds % 3600 // 60} 分"


def block(job: Job) -> dict:
    """聊天里的任务卡（blocks.JobBlock）。运行中客户端自己轮询 /api/jobs/{id}；结束时 settle() 把它改成终态。"""
    out = {"type": "job", "id": job.id, "title": job.title, "command": job.command, "state": job.state,
           "started_at": iso(job.created_at)}
    if job.state != "running":
        out.update(exit_code=job.exit_code, finished_at=iso(job.finished_at), tail=job.tail)
        if job.stop_reason:
            out["stop_reason"] = job.stop_reason
    return out


def wire(job: Job, chars: int = TAIL_CHARS) -> dict:
    return {"id": job.id, "project_id": job.project_id, "conversation_id": job.conversation_id,
            "title": job.title, "command": job.command, "state": job.state, "exit_code": job.exit_code,
            "followup": job.followup, "started_at": iso(job.created_at), "finished_at": iso(job.finished_at),
            "elapsed": elapsed(job), "log_size": log_size(job), "stop_reason": job.stop_reason,
            "tail": log_tail(job, chars) if job.state == "running" or log_size(job) else job.tail}


def describe(job: Job) -> str:
    code = "" if job.exit_code is None or job.state in ("done", "cancelled") else f"，退出码 {job.exit_code}"
    label = f"被自动停止（{job.stop_reason}）" if job.stop_reason else LABELS.get(job.state, job.state)
    return f"{job.id}「{job.title}」：{label}{code}，用时 {duration_text(elapsed(job))}"


def log_path(job: Job) -> str:
    """完整日志相对工作区根的路径（read_file 能按 offset 分段读）。"""
    return f"{JOBS_DIR}/{job.id}/log"


def last_output_at(job: Job) -> datetime:
    try:
        return datetime.fromtimestamp((job_dir(job) / "log").stat().st_mtime, timezone.utc)
    except FileNotFoundError:
        return _aware(job.created_at)


def guard_reason(job: Job, now: datetime | None = None) -> str | None:
    """运行中的任务该不该被护栏停掉；该停返回给人看的原因。"""
    now = now or datetime.now(timezone.utc)
    if log_size(job) > settings.job_log_max_mb * 1024 * 1024:
        return f"输出超过 {settings.job_log_max_mb} MB，防止撑爆磁盘"
    idle = job.idle_timeout
    if idle and (now - max(last_output_at(job), _aware(job.created_at))).total_seconds() >= idle:
        return f"连续 {duration_text(idle)} 没有任何新输出，判定卡住"
    return None


async def running_count(db: AsyncSession, project_id: str) -> int:
    return await db.scalar(select(func.count()).select_from(Job)
                           .where(Job.project_id == project_id, Job.state == "running")) or 0


def idle_limit(idle_timeout: int | None, timeout: int) -> int:
    """None → 默认 job_idle_seconds；0 → 不判卡住；其余夹在 60 秒到任务时限之间。"""
    if idle_timeout is None:
        idle_timeout = settings.job_idle_seconds
    return 0 if idle_timeout <= 0 or idle_timeout >= timeout else max(60, int(idle_timeout))


async def start(db: AsyncSession, *, project_id: str, command: str, title: str | None = None,
                timeout: int | None = None, idle_timeout: int | None = None, conversation_id: str | None = None,
                task_id: str | None = None) -> Job:
    command = command.strip()
    if not command:
        raise JobError("命令是空的")
    if (n := await running_count(db, project_id)) >= settings.job_max_running:
        raise JobError(f"这个工作区已有 {n} 个后台任务在跑（上限 {settings.job_max_running}），等它们结束或先取消一个")
    limit = max(10, min(int(timeout or settings.job_max_seconds), settings.job_max_seconds))
    job = Job(id=new_id(), project_id=project_id, conversation_id=conversation_id, task_id=task_id,
              title=(title or command.splitlines()[0]).strip()[:60] or "后台任务", command=command, timeout=limit,
              idle_timeout=idle_limit(idle_timeout, limit), created_at=datetime.now(timezone.utc))
    d = job_dir(job)
    d.mkdir(parents=True)
    (d / "cmd.sh").write_text(command + "\n", encoding="utf-8")
    (d / "run.sh").write_text(script(job.id, limit), encoding="utf-8")
    try:
        await sandbox_client.start_job(project_id, job.id)
    except httpx.HTTPError as e:
        for f in d.iterdir():
            f.unlink()
        d.rmdir()
        raise JobError(f"沙盒没响应，后台任务没能启动（{type(e).__name__}）") from e
    db.add(job)
    await db.commit()
    return job


async def _patch_blocks(db: AsyncSession, job: Job) -> None:
    """把对话里这张任务卡改成当前状态（重开对话、换设备看到的就是结论，不用再轮询）。"""
    if not job.conversation_id:
        return
    msgs = (await db.scalars(select(Message).where(Message.conversation_id == job.conversation_id,
                                                   Message.role == "assistant"))).all()
    for m in msgs:
        if any(b.get("type") == "job" and b.get("id") == job.id for b in m.blocks):
            m.blocks = [block(job) if b.get("type") == "job" and b.get("id") == job.id else b for b in m.blocks]


async def settle(db: AsyncSession, job: Job, state: str, exit_code: int | None) -> bool:
    """记下结论（只第一次算数）并提交。返回这次是否真的结了。"""
    if job.state != "running":
        return False
    job.state, job.exit_code = state, exit_code
    job.finished_at = datetime.now(timezone.utc)
    job.tail = log_tail(job, KEEP_TAIL)
    by_agent = state == "cancelled" and _read(job_dir(job) / "cancelled") == "agent"
    if job.followup == "none" and not by_agent and job.conversation_id and await db.get(Conversation, job.conversation_id):
        job.followup = "pending"
    await _patch_blocks(db, job)
    await db.commit()
    return True


async def refresh(db: AsyncSession, job: Job, check_alive: bool = False) -> Job:
    """运行中的任务对一下现状：磁盘上有退出码就结；check_alive（worker 用）再问沙盒进程还在不在，没了就算丢失。
    沙盒服务连不上时不下结论（可能只是它在重启，进程还在跑）。"""
    if job.state != "running":
        return job
    if (obs := observe(job)) is not None:
        await settle(db, job, *obs)
    elif check_alive and (reason := guard_reason(job)):
        try:
            await stop(db, job, "guard", reason)
        except JobError:
            pass  # 沙盒暂时连不上：下一轮再停
    elif check_alive and elapsed(job) >= LOST_GRACE:
        try:
            alive = await sandbox_client.job_alive(job.project_id, job.id)
        except httpx.HTTPError:
            return job
        if not alive:
            await settle(db, job, *(observe(job) or ("lost", None)))  # 查活期间刚好写完退出码
    return job


async def cancel(db: AsyncSession, job: Job, by: str = "user") -> bool:
    """取消运行中的任务。已经结束的返回 False。
    by=agent：模型自己取消的，结束后不再“通知”它（它知道）；用户在卡片上取消的照常通知，让助手接一句。"""
    await refresh(db, job)
    if job.state != "running":
        return False
    await stop(db, job, by)
    return True


async def stop(db: AsyncSession, job: Job, by: str, reason: str | None = None) -> None:
    """先写标记（结论算“已取消”，reason 记进 stop_reason），再叫沙盒整组杀；杀不成就撤回标记并抛 JobError。"""
    marker = job_dir(job) / "cancelled"
    marker.write_text(by)
    try:
        await sandbox_client.cancel_job(job.project_id, job.id)
    except httpx.HTTPError as e:
        marker.unlink(missing_ok=True)
        raise JobError("沙盒没响应，没能停掉，稍后再试") from e
    if reason:
        job.stop_reason = reason[:120]
        await db.commit()
    if (obs := observe(job)) is not None:
        await settle(db, job, *obs)
    elif not await _alive_or_unknown(job):
        await settle(db, job, "cancelled", None)


async def _alive_or_unknown(job: Job) -> bool:
    try:
        return await sandbox_client.job_alive(job.project_id, job.id)
    except httpx.HTTPError:
        return True


async def tick(db: AsyncSession) -> list[str]:
    """worker 每轮调：把所有运行中的任务对一遍，返回这次结掉的任务 id。"""
    out = []
    for job in (await db.scalars(select(Job).where(Job.state == "running"))).all():
        await refresh(db, job, check_alive=True)
        if job.state != "running":
            out.append(job.id)
    return out


def notice(job: Job) -> str:
    """接着说那一轮里，模型看到的“系统通知”（不落库，不是用户说的话）。"""
    tail = job.tail.strip() or "（没有输出）"
    return (f"【系统通知，不是用户说的】你之前在后台启动的任务已结束：{describe(job)}。\n"
            f"命令：\n```bash\n{job.command[:500]}\n```\n最后的输出：\n```\n{tail}\n```\n"
            "根据结果接着把事办完：成功就简短告诉用户结论和产物在哪（要给他看的文件用 read_file / write_file 展示）；"
            "失败就说清原因和下一步（能自己修好就直接修了再跑）。用户此刻不一定在看，不要寒暄、不要问“还需要什么”。")


async def follow_ups(db: AsyncSession) -> int:
    """worker 调：结束了的任务在原对话里接着回一轮。原对话还有一轮没答完（最后一条是用户的）就先等，
    等太久就放弃（那一轮自己会看到任务卡的结论）。返回这次接着说了几次。"""
    from .agent.runner import run_turn  # 避免 import 环：runner → 工具 → jobs

    n = 0
    for job in (await db.scalars(select(Job).where(Job.followup == "pending"))).all():
        conv = await db.get(Conversation, job.conversation_id) if job.conversation_id else None
        if conv is None:
            job.followup = "none"
            await db.commit()
            continue
        last = await db.scalar(select(Message).where(Message.conversation_id == conv.id)
                               .order_by(Message.created_at.desc()).limit(1))
        if last is not None and last.role == "user":
            if (datetime.now(timezone.utc) - _aware(last.created_at)).total_seconds() < FOLLOWUP_WAIT:
                continue
            job.followup = "skipped"
            await db.commit()
            continue
        await _patch_blocks(db, job)  # 任务比那一轮先结束时，卡片是那一轮结束才落库的
        job.followup = "done"
        await db.commit()
        await run_turn(db, conv, notice=notice(job), task_id=job.task_id)
        n += 1
    return n
