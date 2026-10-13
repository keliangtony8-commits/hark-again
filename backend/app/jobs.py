"""后台任务的唯一入口：在工作区沙盒（项目或个人，见 workspaces.py）里跑超过一条命令时限的活（装依赖、训练、爬取、大构建）。

文件约定（工作区 .jobs/<id>/，沙盒和后端看到的是同一个目录）：
  cmd.sh    用户/模型给的命令原文
  run.sh    包装脚本（script()）：timeout 作为进程组组长在后台跑 cmd.sh，pid 写进 pid，
            输出全进 log，结束把退出码原子地写进 exit
  cancelled 取消标记，内容是谁停的：user | agent | guard（stop() 先写它再叫沙盒整组杀，退出码因此算“已取消”）
  oom       run.sh 写的：任务期间容器 cgroup 的 OOM 计数涨了（内存超上限，内核杀了进程）→ 结论里写明原因
  memcap    v1.92 app/job_memory.py 写的：超过给它单独定的内存上限（memory_max），先写它再整组杀；内容就是给人看的原因。
            结论算失败（常驻任务照崩溃处理、按 job_restart 退避重启），不是“已取消”
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
v1.92 内存：普通后台任务 run.sh 把自己的 oom_score_adj 调高 OOM_ADJ（子进程继承），整台沙盒内存打满时内核先杀它们、
保住常驻服务；单任务上限与“快满了”的提醒见 app/job_memory.py。
v2.04 前台转后台（移植 deepseek-harness tool-bash promoteOnTimeout 的语义，MIT）：run_command 前台命令先问 admission，
能收就带 promote_slot() 给沙盒；到点没跑完沙盒不杀，现场登记 .jobs/<id>/（同上约定，没有 run.sh），adopt() 建行接着监护。
收不下（满了 / 磁盘满）就照旧到点杀掉。
v1.80 常驻任务（keep_alive，对标 Manus Cloud Computer 的“常开进程 / 24 小时 bot”）：不限时（timeout 0）、不判卡住；
进程意外退出（非零 / OOM / 容器重启进程没了）→ job_restart.decide 给出等待秒数，restart_at 到点由 worker 的 tick 重新叫沙盒
跑同一个 run.sh（日志追加，中间插一行“第 N 次重启”）；正常退出（0）照普通任务结算；连续很快就崩到上限 → 结算为失败并通知助手。
整个监护期间 state 一直是 running（占运行名额、电脑不会因空闲被停）；日志超过上限不停服务，而是轮转（留尾巴进 log.1）。
“这台电脑”重启时常驻任务不停，删完容器立刻排队重启（after_restart）。
"""
import asyncio
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import command_credentials, command_env, egress_note, glyph_note, job_changes, missing_env, job_disk, job_restart, quota, sandbox_client, term_text
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
STOPPERS = ("user", "agent", "guard")  # v2.25 .jobs/<id>/cancelled 里写的是谁停的；结算时记进 jobs.stopped_by
USER_STOP = "已被用户手动停止（这是用户的决定：除非用户再要求，不要重新启动它，也不要换个方式再跑）"
LABELS = {"running": "运行中", "done": "已完成", "failed": "失败", "timed_out": "超时被终止",
          "cancelled": "已取消", "lost": "中断了（沙盒重启或进程消失）"}
ROTATE_KEEP = 256 * 1024  # 常驻任务日志轮转时留进 log.1 的尾巴（字节）


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
OOM_ADJ = 500           # 普通后台任务的 oom_score_adj（调高不需要特权；常驻服务保持 0）
MEMCAP = "memcap"
MEMCAP_PREFIX = "内存超过给它定的上限"  # job_memory.reason() 的开头：describe 据此给出路


def memcap_hint() -> str:
    return "超过了给它单独定的内存上限：改成分批/流式处理、减小 batch，确实需要更多就把 memory_limit 调大再跑。"


def oom_hint(limit: int | None = None) -> str:
    """给模型的出路：一次只处理一部分、换省内存的做法；不要原样重跑。"""
    cap = f"（上限 {limit / 1024 ** 3:g} GB）" if limit else ""
    return (f"内存打满了{cap}：别原样重跑，改成分批/流式处理、减小 batch 或数据量、用更省内存的库；"
            "还不够就告诉用户这台电脑内存不够，可以在 .env 调大 SANDBOX_MEM。")


def script(job_id: str, timeout: int, keep_alive: bool = False) -> str:
    """run.sh：从工作区根目录跑；timeout 自成进程组（取消时整组杀），-k 5 超时后再给 5 秒强杀。
    timeout 0 = 不限时（GNU timeout 的 0 就是关掉计时，仍做进程组组长）——常驻任务用。
    日志用 >> 追加：常驻任务重启接着写同一份；轮转时后端直接截断它（O_APPEND 写入跟着新末尾走）。
    普通任务先把自己的 oom_score_adj 调高（子进程继承）：内存打满时内核优先杀它们，常驻服务留下。"""
    j = f"{JOBS_DIR}/{job_id}"
    return (
        "#!/bin/bash\n"
        'cd "$(dirname "$0")/../.." || exit 1\n'
        f"J={j}\n"
        + ("" if keep_alive else f"echo {OOM_ADJ} > /proc/self/oom_score_adj 2>/dev/null\n") +
        f"before=$({OOM_COUNT})\n"
        f'timeout -k 5 {int(timeout)} bash -l "$J/cmd.sh" >> "$J/log" 2>&1 < /dev/null &\n'
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
    if (d / MEMCAP).exists() or (d / "oom").exists():
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


def _binary(job: Job) -> bool:
    """日志开头就是二进制（后台 cat 了个压缩包之类）：不把乱码给人和模型看。"""
    try:
        with (job_dir(job) / "log").open("rb") as f:
            return term_text.is_binary(f.read(term_text.BINARY_SAMPLE))
    except FileNotFoundError:
        return False


def log_tail(job: Job, chars: int = TAIL_CHARS) -> str:
    """日志最后一段（term_text.clean：去颜色转义、\\r 进度帧折叠）；二进制日志换成一句说明。"""
    p = job_dir(job) / "log"
    try:
        with p.open("rb") as f:
            size = f.seek(0, 2)
            f.seek(max(0, size - chars * 4))  # 中文最多 4 字节一个字
            raw = f.read().decode("utf-8", "replace")
    except FileNotFoundError:
        return ""
    if _binary(job):
        return term_text.binary_note(size)
    text = command_env.scrub(term_text.clean(raw))  # 用户的命令环境变量值打码（app/command_env.py）
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
    if _binary(job):  # 二进制日志：游标直接跳到末尾，只说一句
        return (term_text.binary_note(size) if size > start else ""), size, 0
    skip = utf8_start(raw) if begin > start else 0  # 窗口从字中间切进来：跳到下一个码点
    end = utf8_complete(raw)
    text = command_env.scrub(term_text.clean(raw[skip:end].decode("utf-8", "replace")))
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
    if job.keep_alive:
        out.update(keep_alive=True, restarts=job.restarts)
    if job.memory_max:
        out["memory_max"] = job.memory_max
    if job.promoted:
        out["promoted"] = True
    if borrowed := credentials(job):
        out["credentials"] = command_credentials.labels(borrowed)
    if job.state != "running":
        if job.memory_peak:
            out["memory_peak"] = job.memory_peak
        out.update(exit_code=job.exit_code, finished_at=iso(job.finished_at), tail=job.tail)
        if job.stop_reason:
            out["stop_reason"] = job.stop_reason
        if job.stopped_by:
            out["stopped_by"] = job.stopped_by
        if (d := job_disk.stored(job)) is not None:
            out["disk"] = d  # v1.96 结算时数的磁盘账
        if (c := job_changes.wire(job)) is not None:
            out["changes"] = c  # v2.18 它改了哪些文件（可撤销）
    return out


def wire(job: Job, chars: int = TAIL_CHARS) -> dict:
    return {"id": job.id, "project_id": job.project_id, "conversation_id": job.conversation_id,
            "title": job.title, "command": job.command, "state": job.state, "exit_code": job.exit_code,
            "followup": job.followup, "started_at": iso(job.created_at), "finished_at": iso(job.finished_at),
            "elapsed": elapsed(job), "log_size": log_size(job), "stop_reason": job.stop_reason,
            "stopped_by": job.stopped_by,
            "tail": log_tail(job, chars) if job.state == "running" or log_size(job) else job.tail,
            "keep_alive": bool(job.keep_alive), "restarts": job.restarts or 0,
            "restart_at": iso(job.restart_at) if job.state == "running" else None,
            "memory_max": job.memory_max, "memory_peak": job.memory_peak, "disk": job_disk.stored(job),
            "promoted": bool(job.promoted), "changes": job_changes.wire(job),
            "credentials": command_credentials.labels(credentials(job))}


def _log_tail(job: Job) -> bytes:
    """日志最后 glyph_note.TAIL_BYTES 字节；没有 / 读不了 → 空。"""
    try:
        with open(job_dir(job) / "log", "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - glyph_note.TAIL_BYTES))
            return f.read()
    except OSError:
        return b""


def describe(job: Job) -> str:
    code = "" if job.exit_code is None or job.state in ("done", "cancelled") else f"，退出码 {job.exit_code}"
    label = f"被自动停止（{job.stop_reason}）" if job.stop_reason else LABELS.get(job.state, job.state)
    if job.state == "cancelled" and job.stopped_by == "user":
        label = USER_STOP
    if job.stop_reason == OOM_REASON:  # 不是我们停的，是内核：给模型一条出路
        label = f"失败：{OOM_REASON}"
    elif (job.stop_reason or "").startswith(MEMCAP_PREFIX):
        label = f"失败：{job.stop_reason}"
    if job.keep_alive and job.state == "running":
        label = "常驻，进程刚退出、等待自动重启" if job.restart_at else "常驻，运行中"
    if job.keep_alive and job.restarts:
        label += f"（已自动重启 {job.restarts} 次）"
    line = f"{job.id}「{job.title}」{'（前台命令转入后台）' if job.promoted else ''}：{label}{code}，用时 {duration_text(elapsed(job))}"
    if job.memory_peak and job.state != "running":
        line += f"，内存峰值约 {quota.size_text(job.memory_peak)}"
    if disk := job_disk.text(job_disk.stored(job), brief=True):
        line += f"；{disk}"
    if changed := job_changes.text(job_changes.wire(job)):
        line += f"；{changed}"
    if blocked := egress_note.note(egress_note.read_job(job_dir(job)), "job"):  # v2.37 沙盒服务记的出网被拦
        line += f"。\n{blocked.rstrip()}"
    if job.state != "running" and (glyphs := glyph_note.note_tail(_log_tail(job))):  # v2.40 画图缺字形
        line += f"。\n{glyphs.rstrip()}"
    if job.state == "failed" and (absent := missing_env.note(_log_tail(job).decode("utf-8", "replace"), command_env.RESERVED)):  # v2.54
        line += f"。\n{absent.rstrip()}"
    if job.stop_reason == OOM_REASON:
        return f"{line}。{oom_hint()}"
    return f"{line}。{memcap_hint()}" if (job.stop_reason or "").startswith(MEMCAP_PREFIX) else line



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
    if not job.keep_alive and log_size(job) > settings.job_log_max_mb * 1024 * 1024:
        return f"输出超过 {settings.job_log_max_mb} MB，防止撑爆磁盘"
    if reason := quota.job_reason(job.project_id):
        return reason
    idle = job.idle_timeout
    if idle and (now - max(last_output_at(job), _aware(job.created_at))).total_seconds() >= idle:
        return f"连续 {duration_text(idle)} 没有任何新输出，判定卡住"
    return None


def rotate_log(job: Job) -> bool:
    """常驻任务日志超过 job_log_max_mb：最后 ROTATE_KEEP 字节存进 log.1（覆盖上一份），log 截断到 0，读游标归零。
    进程用 >> 打开的日志，截断后接着从新末尾写，不用重启它。没超或不是常驻返回 False。"""
    if not job.keep_alive or log_size(job) <= settings.job_log_max_mb * 1024 * 1024:
        return False
    log = job_dir(job) / "log"
    with log.open("r+b") as f:
        size = f.seek(0, 2)
        f.seek(max(0, size - ROTATE_KEEP))
        tail = f.read()
        (job_dir(job) / "log.1").write_bytes(tail[utf8_start(tail):])
        f.truncate(0)
    job.read_offset = 0
    return True


def run_seconds(job: Job, now: datetime | None = None) -> float:
    """这一次进程跑了多久（常驻任务按最近一次启动算）。"""
    start = _aware(job.run_started_at or job.created_at)
    return max(0.0, ((now or datetime.now(timezone.utc)) - start).total_seconds())


async def running(db: AsyncSession, ws: str) -> list[Job]:
    """这个工作区还在跑的任务（新的在前）；先看一眼磁盘，刚结束的别还挂着（电脑页 / memory_view 共用）。"""
    rows = (await db.scalars(select(Job).where(Job.project_id == ws, Job.state == "running")
                             .order_by(Job.created_at.desc()))).all()
    for job in rows:
        await refresh(db, job)
    return [j for j in rows if j.state == "running"]


async def running_count(db: AsyncSession, project_id: str) -> int:
    return await db.scalar(select(func.count()).select_from(Job)
                           .where(Job.project_id == project_id, Job.state == "running")) or 0


def idle_limit(idle_timeout: int | None, timeout: int) -> int:
    """None → 默认 job_idle_seconds；0 → 不判卡住；其余夹在 60 秒到任务时限之间。"""
    if idle_timeout is None:
        idle_timeout = settings.job_idle_seconds
    return 0 if idle_timeout <= 0 or idle_timeout >= timeout else max(60, int(idle_timeout))


async def admission(db: AsyncSession, project_id: str) -> str | None:
    """还能不能在这个工作区再跑一个后台任务；不能就给原因。start 和前台转后台（adopt 之前问）共用这一条。"""
    if (n := await running_count(db, project_id)) >= settings.job_max_running:
        return f"这个工作区已有 {n} 个后台任务在跑（上限 {settings.job_max_running}），等它们结束或先取消一个"
    try:
        await asyncio.to_thread(quota.check, project_id)
    except quota.QuotaError as e:
        return str(e)
    return None


def promote_slot() -> tuple[str, int]:
    """前台命令带给沙盒的转后台参数：(预先定好的任务 id, 转后台后最长跑多久)。"""
    return new_id(), settings.job_max_seconds


async def adopt(db: AsyncSession, *, job_id: str, project_id: str, command: str, seconds: float,
                conversation_id: str | None = None, task_id: str | None = None,
                credentials: list[str] | None = None) -> Job:
    """v2.04 前台命令到点没跑完、沙盒已把它登记成 .jobs/<job_id>/（cmd.sh、pid、log，结束时写 exit）：建这一行，
    从此和 start() 起的普通后台任务一样被监护（护栏、查活、取消、结束通知）。开始时间往前推 seconds（它已经跑了这么久），
    读游标放在现在的日志末尾：到目前的输出已经在这次的工具结果里给过模型，job_status 只给之后的
    （deepseek-harness promoteOnTimeout 的“一次消费读”）。到点那一刻刚好结束的，下一次 refresh 照常结算。"""
    limit = settings.job_max_seconds
    start_at = datetime.now(timezone.utc) - timedelta(seconds=max(0.0, seconds))
    job = Job(id=job_id, project_id=project_id, conversation_id=conversation_id, task_id=task_id,
              title=(command.strip().splitlines() or [""])[0].strip()[:60] or "后台任务", command=command.strip(),
              timeout=limit, idle_timeout=idle_limit(None, limit), created_at=start_at, run_started_at=start_at,
              promoted=True, credentials=",".join(credentials or []) or None)
    job.read_offset = log_size(job)
    await job_changes.begin(project_id, job_id)  # v2.18 从转后台这一刻起记它改的文件（之前的归那一轮的改动卡）
    db.add(job)
    await db.commit()
    return job


async def start(db: AsyncSession, *, project_id: str, command: str, title: str | None = None,
                timeout: int | None = None, idle_timeout: int | None = None, conversation_id: str | None = None,
                task_id: str | None = None, keep_alive: bool = False, memory_max: int | None = None,
                credentials: list[str] | None = None) -> Job:
    command = command.strip()
    if not command:
        raise JobError("命令是空的")
    if refusal := await admission(db, project_id):
        raise JobError(refusal)
    limit = 0 if keep_alive else max(10, min(int(timeout or settings.job_max_seconds), settings.job_max_seconds))
    now = datetime.now(timezone.utc)
    job = Job(id=new_id(), project_id=project_id, conversation_id=conversation_id, task_id=task_id,
              title=(title or command.splitlines()[0]).strip()[:60] or "后台任务", command=command, timeout=limit,
              idle_timeout=0 if keep_alive else idle_limit(idle_timeout, limit), created_at=now,
              keep_alive=keep_alive, run_started_at=now, memory_max=memory_max or None,
              credentials=",".join(credentials or []) or None)
    d = job_dir(job)
    d.mkdir(parents=True)
    (d / "cmd.sh").write_text(command + "\n", encoding="utf-8")
    (d / "run.sh").write_text(script(job.id, limit, keep_alive), encoding="utf-8")
    await job_changes.begin(project_id, job.id, keep_alive)  # v2.18 启动前记基线（结算时出改动区）
    try:
        await _launch(db, project_id, job.id, credentials)
    except httpx.HTTPError as e:
        job_changes.drop(project_id, job.id)
        for f in d.iterdir():
            f.unlink()
        d.rmdir()
        raise JobError(f"沙盒没响应，后台任务没能启动（{type(e).__name__}）") from e
    db.add(job)
    await db.commit()
    return job


async def _launch(db: AsyncSession, workspace: str, job_id: str, borrowed: list[str] | None = None) -> None:
    """叫沙盒跑 run.sh：每次（含自动 / 手动重启）都现取用户的命令环境变量，改了变量重启就生效。"""
    env = await command_env.load(db)
    if borrowed:  # v2.20 借用的连接：每次启动现取（会续期），借不到就不带
        env = {**env, **(await command_credentials.grant(db, borrowed)).env}
    await sandbox_client.start_job(workspace, job_id, **({"env": env} if env else {}))


def credentials(job: Job) -> list[str]:
    return [p for p in (job.credentials or "").split(",") if p]


async def patch_blocks(db: AsyncSession, job: Job) -> None:
    """把对话里这张任务卡改成当前状态（重开对话、换设备看到的就是结论，不用再轮询）。"""
    if not job.conversation_id:
        return
    msgs = (await db.scalars(select(Message).where(Message.conversation_id == job.conversation_id,
                                                   Message.role == "assistant"))).all()
    for m in msgs:
        if any(b.get("type") == "job" and b.get("id") == job.id for b in m.blocks):
            m.blocks = [block(job) if b.get("type") == "job" and b.get("id") == job.id else b for b in m.blocks]


async def current_blocks(db: AsyncSession, blocks: list[dict]) -> list[dict]:
    """v2.27 一轮落库前：任务卡一律按 Job 表现状重画（这一轮里就结束/被取消的任务，settle 那时消息还没落库、
    patch_blocks 找不到卡；不在这里补，卡片会永远停在 running）。表里找不到的卡原样留着。唯一入口。"""
    if not any(b.get("type") == "job" and b.get("id") for b in blocks):
        return blocks
    out = []
    for b in blocks:
        job = await db.get(Job, b["id"]) if b.get("type") == "job" and b.get("id") else None
        if job is not None:
            await db.refresh(job)  # 别的会话（worker / 接口）可能刚结掉它：读库里最新的
        out.append(block(job) if job is not None else b)
    return out


async def settle(db: AsyncSession, job: Job, state: str, exit_code: int | None) -> bool:
    """记下结论（只第一次算数）并提交。返回这次是否真的结了。"""
    if job.state != "running":
        return False
    job.state, job.exit_code = state, exit_code
    job.finished_at = datetime.now(timezone.utc)
    job.restart_at = None
    if state == "failed" and not job.stop_reason:
        if cap := _read(job_dir(job) / MEMCAP):
            job.stop_reason = cap[:120]
        elif (job_dir(job) / "oom").exists():
            job.stop_reason = OOM_REASON
    job.tail = log_tail(job, KEEP_TAIL)
    await job_disk.record(db, job)  # v1.96 磁盘账：结算时数一次
    await job_changes.record(db, job)  # v2.18 它改了哪些文件 + 撤销记录
    job.stopped_by = stopper(job, state)
    if job.followup == "none" and job.stopped_by != "agent" and job.conversation_id \
            and await db.get(Conversation, job.conversation_id):
        # v2.25 用户自己停的：不叫醒助手（卡片已写明，叫醒了模型常会当成失败去“修”、把服务又拉起来）；
        # 结论压着，等用户下次说话并进那一轮（take_held），助手才知道是用户停的
        job.followup = "held" if job.stopped_by == "user" else "pending"
    await patch_blocks(db, job)
    await db.commit()
    return True


def stopper(job: Job, state: str) -> str | None:
    """取消是谁做的（只认 STOPPERS；不是取消、标记没了或认不出 → None）。"""
    if state != "cancelled":
        return None
    by = _read(job_dir(job) / "cancelled")
    return by if by in STOPPERS else None


async def refresh(db: AsyncSession, job: Job, check_alive: bool = False) -> Job:
    """运行中的任务对一下现状：磁盘上有退出码就结；check_alive（worker 用）再问沙盒进程还在不在，没了就算丢失。
    沙盒服务连不上时不下结论（可能只是它在重启，进程还在跑）。"""
    if job.state != "running":
        return job
    if job.restart_at is not None:  # 常驻任务进程已退出，在等重启：只有 worker（check_alive）到点才动手
        if check_alive and datetime.now(timezone.utc) >= _aware(job.restart_at):
            await _relaunch(db, job)
        return job
    if (obs := observe(job)) is not None:
        await _end(db, job, *obs)
    elif check_alive and await asyncio.to_thread(rotate_log, job):
        await db.commit()
    elif check_alive and (reason := await asyncio.to_thread(guard_reason, job)):
        try:
            await stop(db, job, "guard", reason)
        except JobError:
            pass  # 沙盒暂时连不上：下一轮再停
    elif check_alive and run_seconds(job) >= LOST_GRACE:
        try:
            alive = await sandbox_client.job_alive(job.project_id, job.id)
        except httpx.HTTPError:
            return job
        if not alive:
            await _end(db, job, *(observe(job) or ("lost", None)))  # 查活期间刚好写完退出码
    return job


async def _end(db: AsyncSession, job: Job, state: str, exit_code: int | None) -> None:
    """进程结束了：普通任务直接结算；常驻任务意外退出按 job_restart 排队重启，或放弃（结算为失败）。"""
    if job.keep_alive and job.state == "running":
        v = job_restart.decide(state, run_seconds(job), job.crash_streak or 0)
        if v.delay is not None:
            job.crash_streak, job.exit_code = v.streak, exit_code
            job.restart_at = datetime.now(timezone.utc) + timedelta(seconds=v.delay)
            await db.commit()
            return
        if v.give_up:
            job.crash_streak, job.stop_reason = v.streak, v.give_up[:120]
            state = "failed"
    await settle(db, job, state, exit_code)


def _relaunch_files(job: Job) -> None:
    """重启前清掉上一次进程留下的结论文件，日志里插一行分隔（接着追加）。"""
    d = job_dir(job)
    why = _read(d / MEMCAP) or (OOM_REASON if (d / "oom").exists() else "")
    for name in ("exit", "exit.tmp", "oom", MEMCAP, "pid"):
        (d / name).unlink(missing_ok=True)
    with (d / "log").open("a", encoding="utf-8") as f:
        f.write(f"\n—— 第 {job.restarts + 1} 次重启{f'（上次：{why}）' if why else ''} ——\n")


async def _relaunch(db: AsyncSession, job: Job) -> None:
    """restart_at 到点：取消标记出现了就按取消结算；工作区满了不再起；否则叫沙盒再跑一次 run.sh。
    沙盒连不上不算一次崩溃，过 FIRST_S 秒再试。"""
    if (obs := observe(job)) is not None and obs[0] == "cancelled":
        await settle(db, job, *obs)
        return
    if reason := await asyncio.to_thread(quota.job_reason, job.project_id):
        job.stop_reason = reason[:120]
        await settle(db, job, "cancelled", job.exit_code)
        return
    await asyncio.to_thread(_relaunch_files, job)
    now = datetime.now(timezone.utc)
    try:
        await _launch(db, job.project_id, job.id, credentials(job))
    except httpx.HTTPError:
        job.restart_at = now + timedelta(seconds=job_restart.FIRST_S)
        await db.commit()
        return
    job.restarts = (job.restarts or 0) + 1
    job.run_started_at, job.restart_at = now, None
    await db.commit()


async def after_restart(db: AsyncSession, job: Job) -> None:
    """“这台电脑”被用户重启（容器删了，进程肯定没了）：常驻任务马上排队重启，不算崩溃。"""
    if job.state == "running" and job.keep_alive:
        job.restart_at = datetime.now(timezone.utc)
        await db.commit()


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
    if job.restart_at is not None:  # 常驻任务正等着重启：进程本来就没了，不用叫沙盒杀（pid 可能已被别的进程复用）
        if reason:
            job.stop_reason = reason[:120]
        await settle(db, job, "cancelled", job.exit_code)
        return
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
    await command_env.ensure(db)  # 读日志尾巴要打码：worker 进程里的值缓存定期刷新
    out = []
    for job in (await db.scalars(select(Job).where(Job.state == "running"))).all():
        await refresh(db, job, check_alive=True)
        if job.state != "running":
            out.append(job.id)
    return out


def _brief(job: Job, tail_chars: int) -> str:
    tail = job.tail.strip()[-tail_chars:] or "（没有输出）"
    return f"{describe(job)}\n命令：\n```bash\n{job.command[:500]}\n```\n最后的输出：\n```\n{tail}\n```"


def notice(group: Job | list[Job], extra: str = "") -> str:
    """接着说那一轮里，模型看到的“系统通知”（不落库，不是用户说的话）。同一对话里一起结束的任务并成一条，
    一轮说完（deepseek-harness：一起结束的任务只花一步）。总长有界：每个任务的输出尾巴按个数分 KEEP_TAIL。"""
    group = [group] if isinstance(group, Job) else group
    each = max(300, KEEP_TAIL // len(group))
    head = ("你之前在后台启动的任务已结束：" if len(group) == 1
            else f"你之前在后台启动的 {len(group)} 个任务都已结束：\n")
    body = "\n\n".join(_brief(j, each) for j in group) + (f"\n{extra}" if extra else "")
    return (f"【系统通知，不是用户说的】{head}{body}\n"
            "根据结果接着把事办完：成功就简短告诉用户结论和产物在哪（要交给他的图表/文件/目录用 display_file 交付）；"
            "失败就说清原因和下一步（能自己修好就直接修了再跑）。用户此刻不一定在看，不要寒暄、不要问“还需要什么”。")


def held_notice(group: list[Job]) -> str:
    """叫醒轮数到上限时压下的结论：用户下次说话，并进那一轮的系统提示（runner.take_held）。"""
    each = max(300, KEEP_TAIL // len(group))
    body = "\n\n".join(_brief(j, each) for j in group)
    return ("【系统通知】用户这次发言之前，你后台启动的这些任务已结束（没有当场叫醒你：用户自己停的，或你已连着自动接话好几轮）：\n"
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


async def _oom_note(db: AsyncSession, group: list[Job]) -> str:
    """v2.00 有任务是被系统因内存杀掉的：通知里带上现在谁在占（memory_view.note；避免 import 环，现用现导）。"""
    oomed = next((j for j in group if j.stop_reason == OOM_REASON), None)
    if oomed is None:
        return ""
    from . import memory_view
    return memory_view.note(await memory_view.current(db, oomed.project_id), after_oom=True)


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
            await patch_blocks(db, job)  # 任务比那一轮先结束时，卡片是那一轮结束才落库的
            _done(job, now)
        await db.commit()
        extra = await _oom_note(db, group)
        await run_turn(db, conv, notice=notice(group, extra), task_id=next((j.task_id for j in group if j.task_id), None))
        n += 1
    return n
