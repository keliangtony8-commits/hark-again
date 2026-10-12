"""定时脚本（v1.84）的唯一规则：到点不叫模型，直接在工作区沙盒里跑一条 shell 命令（对标 Manus / 云电脑的 cron：
定时备份、定时抓取、每晚跑一遍测试）。省 token：成功又没什么可说时一个 token 都不花。

任务：ScheduledTask.kind == "script"，prompt 就是命令原文；project_id = 在哪个项目的工作区跑（null = 个人工作区）。
执行：worker 到点调 launch() → 开一条 task_runs（running）→ jobs.start() 当后台任务跑（时限、卡住护栏、OOM、日志轮转、
重启恢复全部复用 jobs.py）；TaskRun.job_id 记下是哪个后台任务。job 没有 conversation_id，所以结束后不会叫醒模型。
收尾：worker 每轮 settle_ready() 找“记录还在 running、后台任务已结束”的 → settle()：
- 成功（退出码 0）= ok；其余（失败 / 超时 / 被护栏停 / 丢失）= error，原因写进运行记录，首次失败照常由 task_runs 发提醒卡；
- 何时告诉用户（notify）：failure = 只在失败时（默认）；always = 每次；change = 输出和上次成功那次不一样时（第一次算变化）；
- 告诉 = 开一段对话（用户消息是命令，助手消息是任务卡 + 一句结论）+ Home 收件箱报告卡；用户点开可以接着问“为什么失败”。
  不告诉时不开对话，聊天列表不被每小时一次的脚本刷满。
重叠：上一次还在跑就跳过这次（不开记录、不算失败，只把 last_run_at 推到现在，按计划等下一次）。
项目删了：它的脚本任务跟着删（routes/resources 删项目时调 task_store.remove_for_project）；万一后台任务记录先没了，
settle_ready 把这条运行记成失败，不会永远挂在“正在运行”。"""
import hashlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from . import jobs, report_gist, task_runs, workspaces
from .blocks import text_to_blocks
from .config import settings
from .models import Conversation, HomeCard, Job, Message, Project, ScheduledTask, TaskRun

KINDS = ("agent", "script")
NOTIFY = ("failure", "always", "change")
NOTIFY_LABELS = {"failure": "失败时告诉我", "always": "每次都告诉我", "change": "输出变了告诉我"}
COMMAND_MAX = 4000
DIGEST_CHARS = 200_000  # 比对“输出变没变”看的日志长度（尾部）


def is_script(task: ScheduledTask) -> bool:
    return task.kind == "script"


def check(kind: str | None, command: str | None, notify: str | None, output: str = "report") -> None:
    """新建 / 修改后的任务是否成立；不成立抛 ValueError（中文原因）。agent 任务只校验 kind 与 notify 合法。"""
    kind = kind or "agent"
    if kind not in KINDS:
        raise ValueError(f"不认识的任务类型：{kind}（可选 {', '.join(KINDS)}）")
    if (notify or "failure") not in NOTIFY:
        raise ValueError(f"不认识的提醒方式：{notify}（可选 {', '.join(NOTIFY)}）")
    if kind != "script":
        return
    if output == "panel":
        raise ValueError("面板要靠助手整理内容，不能是脚本。")
    cmd = (command or "").strip()
    if not cmd:
        raise ValueError("定时脚本要有命令。")
    if len(cmd) > COMMAND_MAX:
        raise ValueError(f"命令太长（{len(cmd)} 字，上限 {COMMAND_MAX}）：写成脚本文件放进工作区，这里只调用它。")


async def check_project(db: AsyncSession, project_id: str | None) -> None:
    if project_id and await db.get(Project, project_id) is None:
        raise ValueError("没有这个项目。")


def _digest(job: Job) -> str:
    return hashlib.sha256(jobs.log_tail(job, DIGEST_CHARS).encode("utf-8", "replace")).hexdigest()


async def _busy(db: AsyncSession, task: ScheduledTask) -> bool:
    """这个脚本上一次还在跑（记录 running 且后台任务仍在跑）。"""
    row = await db.scalar(select(TaskRun.id).join(Job, Job.id == TaskRun.job_id).where(
        TaskRun.task_id == task.id, TaskRun.status == "running", Job.state == "running"))
    return row is not None


async def launch(db: AsyncSession, task: ScheduledTask, now: datetime | None = None) -> TaskRun | None:
    """到点（或立即运行）：开记录、起后台任务。起不来（沙盒没响应、名额满、磁盘满、项目没了）当场记失败。
    上一次还在跑 → 不开新记录（避免同一脚本叠着跑），返回 None。"""
    now = now or datetime.now(timezone.utc)
    run = None if await _busy(db, task) else await task_runs.start(db, task, now)  # start 按 run_requested 记手动 / 定时
    task.last_run_at, task.run_requested = now, False
    await db.commit()
    if run is None:
        return None
    try:
        await check_project(db, task.project_id)
        job = await jobs.start(db, project_id=workspaces.of(task.project_id), command=task.prompt,
                               title=task.name, task_id=task.id)
    except ValueError:
        await settle_failed_start(db, task, run, "项目已经删除，脚本没地方跑了。")
        return run
    except jobs.JobError as e:
        await settle_failed_start(db, task, run, str(e))
        return run
    run.job_id = job.id
    await db.commit()
    return run


async def settle_failed_start(db: AsyncSession, task: ScheduledTask, run: TaskRun, error: str) -> None:
    conv = await _deliver(db, task, None, f"没能启动：{error}")
    await task_runs.finish(db, task, run, error, conv.id if conv else None)


def _verdict(job: Job) -> str | None:
    """None = 成功；否则给人看的失败原因。"""
    return None if job.state == "done" else jobs.describe(job)


LOST_RECORD = "后台任务的记录不见了（所在项目可能被删除）"


def _line(notify: str | None, error: str | None, first: bool) -> str:
    if error is not None:
        return f"没跑成功：{error}"
    if notify == "change":
        return "第一次运行的结果；之后输出有变化才会告诉你。" if first else "输出和上次不一样了。"
    return "跑完了。"


def should_notify(notify: str, ok: bool, changed: bool) -> bool:
    if not ok:
        return True
    return notify == "always" or (notify == "change" and changed)


async def settle(db: AsyncSession, task: ScheduledTask, run: TaskRun, job: Job | None) -> None:
    error = _verdict(job) if job is not None else LOST_RECORD
    changed = first = False
    if error is None:
        digest = _digest(job)
        first, changed = task.output_digest is None, digest != task.output_digest
        task.output_digest = digest
    conv = None
    if should_notify(task.notify or "failure", error is None, changed):
        conv = await _deliver(db, task, job, _line(task.notify, error, first))
    await task_runs.finish(db, task, run, error, conv.id if conv else None)


async def _deliver(db: AsyncSession, task: ScheduledTask, job: Job | None, line: str) -> Conversation | None:
    """开一段对话（命令 + 任务卡 + 结论）+ 收件箱报告卡（同一任务只留最新一张）。"""
    local = datetime.now(timezone.utc).astimezone(ZoneInfo(settings.timezone))
    conv = Conversation(title=f"{task.name} · {local:%m月%d日 %H:%M}", project_id=task.project_id)
    db.add(conv)
    await db.flush()
    db.add(Message(conversation_id=conv.id, role="user",
                   blocks=text_to_blocks(f"定时脚本「{task.name}」：\n```bash\n{task.prompt[:COMMAND_MAX]}\n```")))
    blocks = text_to_blocks(line) + ([jobs.block(job)] if job is not None else [])
    db.add(Message(conversation_id=conv.id, role="assistant", blocks=blocks))
    await db.execute(update(HomeCard).where(HomeCard.task_id == task.id, HomeCard.kind == "report")
                     .values(dismissed=True))
    headline, gist = report_gist.gist(text_to_blocks(line))
    db.add(HomeCard(kind="report", title=task.name, conversation_id=conv.id, task_id=task.id, unread=True,
                    blocks=text_to_blocks(line), headline=headline, gist=gist))
    await db.flush()
    return conv


async def settle_ready(db: AsyncSession) -> list[str]:
    """worker 每轮调：后台任务已结束、记录还在 running 的脚本运行 → 收尾。返回收掉的任务 id。"""
    rows = (await db.execute(select(TaskRun, Job).outerjoin(Job, Job.id == TaskRun.job_id).where(
        TaskRun.status == "running", TaskRun.job_id.is_not(None),
        or_(Job.id.is_(None), Job.state.in_(jobs.FINAL))))).all()
    out = []
    for run, job in rows:
        task = await db.get(ScheduledTask, run.task_id)
        if task is None:
            continue
        await settle(db, task, run, job)
        out.append(task.id)
    return out


async def live_run_ids(db: AsyncSession) -> set[str]:
    """后台任务仍在跑的脚本运行（worker 重启时不能当成“被中断”）。"""
    return set((await db.scalars(select(TaskRun.id).join(Job, Job.id == TaskRun.job_id).where(
        TaskRun.status == "running", Job.state == "running"))).all())
