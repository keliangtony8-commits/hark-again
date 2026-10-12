"""后台任务的唯一入口：在工作区沙盒（项目或个人，见 workspaces.py）里跑超过一条命令时限的活（装依赖、训练、爬取、大构建）。

文件约定（工作区 .jobs/<id>/，沙盒和后端看到的是同一个目录）：
  cmd.sh    用户/模型给的命令原文
  run.sh    包装脚本（script()）：timeout 作为进程组组长在后台跑 cmd.sh，pid 写进 pid，
            输出全进 log，结束把退出码原子地写进 exit
  cancelled 取消标记，内容是谁停的：user | agent | guard（stop() 先写它再叫沙盒整组杀，退出码因此算“已取消”）
  oom       run.sh 写的：任务期间容器 cgroup 的 OOM 计数涨了（内存超上限，内核杀了进程）→ 结论里写明原因
沙盒服务只负责启动、查活、整组杀（sandbox/runner.py）；状态从文件读，所以沙盒服务、后端、worker 谁重启都不丢。

护栏（guard_reason()，worker 每轮对运行中的任务查一次）：日志超过 job_log_max_mb → 停（防撑爆磁盘）；
工作区磁盘超过配额（quota.py，v1.31）→ 停，满了也不让启动新任务；
连续 idle_timeout 秒日志没长（mtime 没变；进度条的 \r 刷新也算有输出）→ 判定卡住停掉。停掉的原因记进 stop_reason，
卡片和通知里都写明，助手照常在原对话接着说（它需要知道并决定怎么办）。思路参考了 deepseek-harness（MIT）jobs 的
“kill 带 reason、结算时把原因并进结论”，以及 Codex CLI 的命令无输出超时。

生命周期：start() → running →（文件里出现 exit：observe() / refresh()；或进程没了也没 exit：lost）→ settle()
settle() 记下结论和日志尾巴、把聊天里那张任务卡改成最终状态，并把 followup 置 pending：
worker 的 follow_ups() 随后在原对话里带着结果再跑一轮（像有人告诉助手“你那个任务跑完了”），
模型若已经用 job_status 自己看过结果（followup=seen）就不再打扰。
v1.39 移植自 deepseek-harness tool-jobs（MIT）：job_status 只给上次看过之后的新输出（read_new，游标 read_offset）；
同一对话一起结束的任务并成一轮通知；用户两次发言之间连着叫醒有上限（job_followup_wakes），超出的结论置 held，
用户下次说话时并进那一轮（take_held）。
"""
import asyncio
import secrets
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import quota, sandbox_client
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


# 容器自己的 cgroup OOM 计数（v2 / v1），与 sandbox/runner.py _OOM 同一条；读不到输出空。
OOM_COUNT = ("sed -n 's/^oom_kill //p' /sys/fs/cgroup/memory.events 2>/dev/null || "
             "sed -n 's/^oom_kill //p' /sys/fs/cgroup/memory/memory.oom_control 2>/dev/null")
OOM_REASON = "内存超过这台电脑的上限，被系统强制结束"


def oom_hint(limit: int | None = None) -> str:
    """给模型的出路：一次只处理一部分、换省内存的做法；不要原样重跑。"""
    cap = f"（上限 {limit / 1024 ** 3:g} GB）" if limit else ""
    return (f"内存打满了{cap}：别原样重跑，改成分批/流式处理、减小 batch 或数据量、用更省内存的库；"
            "还不够就告诉用户这台电脑内存不够，可以在 .env 调大 SANDBOX_MEM。")


def script(job_id: str, timeout: int) -> str:
    """run.sh：从工作区根目录跑；timeout 自成进程组（取消时整组杀），-k 5 超时后再给 5 秒强杀。"""
    j = f"{JOBS_DIR}/{job_id}"
    return (
        "#!/bin/bash\n"
        'cd "$(dirname "$0")/../.." || exit 1\n'
        f"J={j}\n"
        f"before=$({OOM_COUNT})\n"
        f'timeout -k 5 {int(timeout)} bash -l "$J/cmd.sh" > "$J/log" 2>&1 < /dev/null &\n'
        'echo $! > "$J/pid"\n'
        "wait $!\n"
        "code=$?\n"
        f'after=$({OOM_COUNT})\n'
        '[ -n "$after" ] && [ "$after" -gt "${before:-0}" ] && touch "$J/oom"\n'
        'echo $code > "$J/exit.tmp" && mv "$J/exit.tmp" "$J/exit"\n'
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
    if (d / "oom").exists():
        return "failed", code
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


def _frames(raw: str) -> str:
    """进度条靠 \\r 原地刷新（pip、wget、tqdm）：每行只留最后一次刷新的样子。"""
    return "\n".join(ln.rsplit("\r", 1)[-1] if "\r" in ln.rstrip("\r") else ln.rstrip("\r") for ln in raw.split("\n"))


def log_tail(job: Job, chars: int = TAIL_CHARS) -> str:
    """日志最后一段（\\r 进度帧折叠）。"""
    p = job_dir(job) / "log"
    try:
        with p.open("rb") as f:
            size = f.seek(0, 2)
            f.seek(max(0, size - chars * 4))  # 中文最多 4 字节一个字
            raw = f.read().decode("utf-8", "replace")
    except FileNotFoundError:
        return ""
    text = _frames(raw)
    return text[-chars:] if len(text) > chars else text


# ---- 只读新输出（移植自 deepseek-harness packages/jobs：jobs-local/src/ring.ts 的 utf8Tail + 绝对偏移游标、
# tool-jobs/src/render.ts 的“读过的不再给、被丢掉的要说清完整输出在哪”；MIT）----
# 那边是内存环形缓冲 + 每个模型一个游标；我们的完整输出本来就在 .jobs/<id>/log，游标就是 Job.read_offset（字节）。

def utf8_start(raw: bytes, i: int = 0) -> int:
    """从 i 往后跳过 UTF-8 续字节（10xxxxxx），返回第一个码点起点（ring.ts utf8Tail 的同一条循环）。"""
    while i < len(raw) and raw[i] & 0xC0 == 0x80:
        i += 1
    return i


def utf8_complete(raw: bytes) -> int:
    """raw 里最后一个完整码点结束的位置：任务正写到一半的多字节字不读，留给下一次（游标永远落在码点边界）。"""
    n = len(raw)
    for back in range(1, min(4, n) + 1):
        b = raw[n - back]
        if b & 0xC0 == 0x80:
            continue  # 续字节，再往前找首字节
        need = 1 if b < 0x80 else 2 if b >> 5 == 0b110 else 3 if b >> 4 == 0b1110 else 4 if b >> 3 == 0b11110 else 1
        return n if back >= need else n - back
    return n  # 全是续字节（坏数据）：照读，decode 会替换掉


def read_new(job: Job, chars: int = TAIL_CHARS) -> tuple[str, int, int]:
    """从 job.read_offset 读到日志当前末尾：返回 (新输出文本, 新游标, 没显示的字节数)。
    新输出超过 chars 只留尾巴（最近的最有用），丢掉的字节数如实返回，调用方提示完整日志路径。
    日志比游标短（被截断/重建）→ 从头读。不改 job，游标由调用方决定写不写回。"""
    p = job_dir(job) / "log"
    try:
        with p.open("rb") as f:
            size = f.seek(0, 2)
            start = job.read_offset if 0 <= (job.read_offset or 0) <= size else 0
            begin = max(start, size - chars * 4)
            f.seek(begin)
            raw = f.read(size - begin)
    except FileNotFoundError:
        return "", job.read_offset or 0, 0
    skip = utf8_start(raw) if begin > start else 0  # 窗口从字中间切进来：跳到下一个码点
    end = utf8_complete(raw)
    text = _frames(raw[skip:end].decode("utf-8", "replace"))
    dropped = begin - start + skip
    if len(text) > chars:
        cut = len(text) - chars
        nl = text.find("\n", cut)
        if 0 <= nl - cut <= chars // 5:  # 就近从整行开始
            cut = nl + 1
        dropped += len(text[:cut].encode("utf-8"))
        text = text[cut:]
    return text, begin + max(end, skip), dropped


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
    if job.stop_reason == OOM_REASON:  # 不是我们停的，是内核：给模型一条出路
        label = f"失败：{OOM_REASON}"
    line = f"{job.id}「{job.title}」：{label}{code}，用时 {duration_text(elapsed(job))}"
    return f"{line}。{oom_hint()}" if job.stop_reason == OOM_REASON else line


def log_path(job: Job) -> str:
    """完整日志相对工作区根的路径（read_file 能按 offset 分段读）。"""
    return f"{JOBS_DIR}/{job.id}/log"


def last_output_at(job: Job) -> datetime:
    try:
        return datetime.fromtimestamp((job_dir(job) / "log").stat().st_mtime, timezone.utc)
    except FileNotFoundError:
        return _aware(job.created_at)


def guard_reason(job: Job, now: datetime | None = None) -> str | None:
    """运行中的任务该不该被护栏停掉；该停返回给人看的原因。会数工作区磁盘（有缓存），异步代码里放线程跑。"""
    now = now or datetime.now(timezone.utc)
    if log_size(job) > settings.job_log_max_mb * 1024 * 1024:
        return f"输出超过 {settings.job_log_max_mb} MB，防止撑爆磁盘"
    if reason := quota.job_reason(job.project_id):
        return reason
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
    try:
        await asyncio.to_thread(quota.check, project_id)
    except quota.QuotaError as e:
        raise JobError(str(e)) from e
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
    if state == "failed" and not job.stop_reason and (job_dir(job) / "oom").exists():
        job.stop_reason = OOM_REASON
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
    elif check_alive and (reason := await asyncio.to_thread(guard_reason, job)):
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


def _brief(job: Job, tail_chars: int) -> str:
    tail = job.tail.strip()[-tail_chars:] or "（没有输出）"
    return f"{describe(job)}\n命令：\n```bash\n{job.command[:500]}\n```\n最后的输出：\n```\n{tail}\n```"


def notice(group: Job | list[Job]) -> str:
    """接着说那一轮里，模型看到的“系统通知”（不落库，不是用户说的话）。同一对话里一起结束的任务并成一条，
    一轮说完（deepseek-harness：一起结束的任务只花一步）。总长有界：每个任务的输出尾巴按个数分 KEEP_TAIL。"""
    group = [group] if isinstance(group, Job) else group
    each = max(300, KEEP_TAIL // len(group))
    head = ("你之前在后台启动的任务已结束：" if len(group) == 1
            else f"你之前在后台启动的 {len(group)} 个任务都已结束：\n")
    body = "\n\n".join(_brief(j, each) for j in group)
    return (f"【系统通知，不是用户说的】{head}{body}\n"
            "根据结果接着把事办完：成功就简短告诉用户结论和产物在哪（要交给他的图表/文件/目录用 display_file 交付）；"
            "失败就说清原因和下一步（能自己修好就直接修了再跑）。用户此刻不一定在看，不要寒暄、不要问“还需要什么”。")


def held_notice(group: list[Job]) -> str:
    """叫醒轮数到上限时压下的结论：用户下次说话，并进那一轮的系统提示（runner.take_held）。"""
    each = max(300, KEEP_TAIL // len(group))
    body = "\n\n".join(_brief(j, each) for j in group)
    return ("【系统通知】用户这次发言之前，你后台启动的这些任务已结束（当时你已连着自动接话好几轮，就没再打扰用户）：\n"
            f"{body}\n先照用户这次说的办；和这些结果有关、或用户还不知道结论的，顺带简短交代。")


def _done(job: Job, at: datetime) -> None:
    job.followup, job.followup_at = "done", at
    job.read_offset = max(job.read_offset or 0, log_size(job))  # 通知里给过尾巴了，job_status 别再重复


async def _wakes(db: AsyncSession, cid: str, since: datetime | None) -> int:
    """用户上次发言之后，任务结束已经连着叫醒了助手几轮（同一轮的任务 followup_at 相同）。
    在 Python 里比时间：SQLite 存的是去掉时区的 UTC，直接在 SQL 里比会和带时区的值错开。"""
    rows = (await db.scalars(select(Job.followup_at).where(Job.conversation_id == cid, Job.followup == "done",
                                                            Job.followup_at.is_not(None)))).all()
    return len({_aware(t) for t in rows if since is None or _aware(t) > since})


async def take_held(db: AsyncSession, cid: str) -> str | None:
    """用户发言的那一轮调：把这个对话里压着的结论取出来（置 done 并提交——SQLite 写锁必须在调模型前放掉）。"""
    held = (await db.scalars(select(Job).where(Job.conversation_id == cid, Job.followup == "held")
                             .order_by(Job.finished_at))).all()
    if not held:
        return None
    now = datetime.now(timezone.utc)
    for job in held:
        job.followup = "done"  # followup_at 不写：这不是一次“叫醒”，不占轮数
        job.read_offset = max(job.read_offset or 0, log_size(job))
    await db.commit()
    return held_notice(list(held))


async def follow_ups(db: AsyncSession) -> int:
    """worker 调：结束了的任务在原对话里接着回一轮（同一对话一起结束的并成一轮）。原对话还有一轮没答完
    （最后一条是用户的）就先等，等太久就放弃（那一轮自己会看到任务卡的结论）。
    用户两次发言之间连着叫醒满 job_followup_wakes 轮就不再叫醒，结论置 held，留到用户下次说话（take_held）。
    返回这次接着说了几轮。"""
    from .agent.runner import run_turn  # 避免 import 环：runner → 工具 → jobs

    groups: dict[str | None, list[Job]] = {}
    for job in (await db.scalars(select(Job).where(Job.followup == "pending").order_by(Job.finished_at))).all():
        groups.setdefault(job.conversation_id, []).append(job)
    n = 0
    for cid, group in groups.items():
        conv = await db.get(Conversation, cid) if cid else None
        if conv is None:
            for job in group:
                job.followup = "none"
            await db.commit()
            continue
        last_user = await db.scalar(select(Message).where(Message.conversation_id == conv.id, Message.role == "user")
                                    .order_by(Message.created_at.desc()).limit(1))
        last = await db.scalar(select(Message).where(Message.conversation_id == conv.id)
                               .order_by(Message.created_at.desc()).limit(1))
        if last is not None and last.role == "user":
            if (datetime.now(timezone.utc) - _aware(last.created_at)).total_seconds() < FOLLOWUP_WAIT:
                continue
            for job in group:
                job.followup = "skipped"
            await db.commit()
            continue
        budget = settings.job_followup_wakes
        if budget > 0 and await _wakes(db, conv.id, _aware(last_user.created_at) if last_user else None) >= budget:
            for job in group:
                job.followup = "held"
            await db.commit()
            continue
        now = datetime.now(timezone.utc)
        for job in group:
            await _patch_blocks(db, job)  # 任务比那一轮先结束时，卡片是那一轮结束才落库的
            _done(job, now)
        await db.commit()
        await run_turn(db, conv, notice=notice(group), task_id=next((j.task_id for j in group if j.task_id), None))
        n += 1
    return n
