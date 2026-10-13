"""定时任务 / 面板“碰壁”的唯一规则（v2.15，对标 Hark 的 report_wall：碰到只有用户能清掉的障碍时
记成一个可修的标记，而不是默默失败或把“我登录不了”当成内容刷上面板）。

壁 = "<类>:<对象>"，对象是小写 slug（[a-z0-9._-]，≤64）：
- needs_login:<域名>      网站要登录（保险箱里没有可用的登录）      用户能修 → 去“保险箱”
- needs_connector:<名字>  连接器没连 / 授权失效                      用户能修 → 去“连接器”
- paywall:<域名>          付费墙                                    用户能修（订阅或换来源）
- source_gone:<域名>      页面搬走 / 改版，按做法找不到了            会自己重新摸索，不算用户的事
- blocked:<原因>          验证码、限流、源站挂了这类暂时的阻碍        之后自己重试
流程：运行里的助手调用 schedule_task action=report_wall → report() 把这次运行（task_runs.wall）和任务的
“当前壁”（scheduled_tasks.wall / wall_reason / wall_at）一起写上并提交；运行结束 worker 调 settle()：
这次报了壁 → 返回失败原因（照常走 task_runs 的失败提醒 / 连续失败暂停），面板保留上一次的内容；
这次没报 → 清掉任务上的旧壁（修好了）。同一次运行报多次，以最后一次为准。
客户端只读 wire() 给的 wall_label / wall_fixable / wall_open / wall_retrying，不自己解释壁的字符串。

v2.19 修好就重跑（对标 Hark：“fixing it re-runs the task”）：用户在保险箱存了某域名的登录 / Key、
连好某个连接器或加了某个 MCP 服务器 → retry_fixed() 找出壁正好是它的任务（needs_login 域名互为子域也算；
needs_connector 比连接器 id / 名字），排一次“立即运行”（run_requested；正在跑的不动——那次跑完自己会清壁或再报），
已因连续失败暂停的也跑（task_runs：手动试跑成功 = 恢复）。不提交，调用方提交。retry_note() 是给用户的那一句。"""
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ScheduledTask, TaskRun

REASON_MAX = 300
SLUG = re.compile(r"^[a-z0-9._-]{1,64}$")
# 类 → (标签模板, 用户能修吗, 客户端去处页 card_targets.PAGES 之一或 None)
CLASSES: dict[str, tuple[str, bool, str | None]] = {
    "needs_login": ("需要登录 {}", True, "vault"),
    "needs_connector": ("需要重新连接 {}", True, "connectors"),
    "paywall": ("{} 要付费订阅", True, None),
    "source_gone": ("{} 的页面变了，正在重新找", False, None),
    "blocked": ("暂时被挡住（{}），之后会再试", False, None),
}
HELP = ("wall 要写成 <类>:<对象>，类只能是 " + " / ".join(CLASSES)
        + "，对象是小写的域名、连接器名或原因（字母数字 . _ -，≤64），如 needs_login:jw.example.edu、"
          "needs_connector:github、blocked:captcha。")


def parse(status: str | None) -> tuple[str, str]:
    """"needs_login:Example.com " → ("needs_login", "example.com")；不合规 → ValueError（中文，给模型看）。"""
    kind, sep, arg = (status or "").strip().lower().partition(":")
    if not sep or kind not in CLASSES or not SLUG.match(arg):
        raise ValueError(HELP)
    return kind, arg


def label(status: str | None) -> str | None:
    if not status:
        return None
    try:
        kind, arg = parse(status)
    except ValueError:
        return status  # 老数据 / 手改的库：原样显示，不崩
    return CLASSES[kind][0].format(arg)


def fixable(status: str | None) -> bool:
    try:
        return CLASSES[parse(status)[0]][1]
    except ValueError:
        return False


def open_page(status: str | None) -> str | None:
    try:
        return CLASSES[parse(status)[0]][2]
    except ValueError:
        return None


def error_text(status: str, reason: str | None) -> str:
    """运行记录 / 失败提醒卡上的那句原因。"""
    head = label(status) or status
    return f"{head}：{reason}" if reason else head


async def report(db: AsyncSession, task: ScheduledTask, status: str, reason: str | None = None,
                 now: datetime | None = None) -> str:
    """运行里报壁：写这次运行 + 任务的当前壁并提交（SQLite：下一次模型调用前必须提交）。返回规整后的壁。
    不在运行里（没有 running 的记录）→ ValueError。"""
    kind, arg = parse(status)
    run = await db.scalar(select(TaskRun).where(TaskRun.task_id == task.id, TaskRun.status == "running")
                          .order_by(TaskRun.started_at.desc()).limit(1))
    if run is None:
        raise ValueError("report_wall 只能在这个任务自己的运行里用（现在它没有在跑）。")
    wall = f"{kind}:{arg}"
    run.wall = wall
    task.wall = wall
    task.wall_reason = " ".join((reason or "").split())[:REASON_MAX] or None
    task.wall_at = now or datetime.now(timezone.utc)
    await db.commit()
    return wall


def settle(task: ScheduledTask, run: TaskRun) -> str | None:
    """运行结束时（不提交）：这次报了壁 → 失败原因；没报 → 清掉任务上的旧壁，返回 None。"""
    if run.wall:
        return error_text(run.wall, task.wall_reason if task.wall == run.wall else None)
    task.wall = task.wall_reason = task.wall_at = None
    return None


def wire(task: ScheduledTask) -> dict:
    """接口给任务补的只读字段（schedule.wire 调用）：客户端只认这四个。wall_retrying = 有壁且已排了重跑。"""
    return {"wall_label": label(task.wall), "wall_fixable": fixable(task.wall), "wall_open": open_page(task.wall),
            "wall_retrying": bool(task.wall and task.run_requested)}


def _norm(name: str) -> str:
    return "-".join((name or "").strip().lower().split())


def _fixes(wall: str | None, kind: str, hosts: list[str], names: list[str]) -> bool:
    try:
        k, arg = parse(wall)
    except ValueError:
        return False
    if k != kind:
        return False
    if kind == "needs_login":
        return any(h and (arg == h or arg.endswith("." + h) or h.endswith("." + arg)) for h in hosts)
    return arg in names


async def retry_fixed(db: AsyncSession, kind: str, *, hosts: list[str] | tuple = (),
                      names: list[str] | tuple = ()) -> list[str]:
    """用户刚修好一类障碍：kind = needs_login（hosts = 存进保险箱的域名）| needs_connector（names = 连接器 id / 名字）。
    壁对得上的任务排一次立即运行，返回它们的名字（不提交）。"""
    hs = [h.strip().lower().lstrip(".") for h in hosts if h and h.strip()]
    ns = [_norm(n) for n in names if n and n.strip()]
    if kind not in ("needs_login", "needs_connector") or not (hs or ns):
        return []
    running = set((await db.scalars(select(TaskRun.task_id).where(TaskRun.status == "running"))).all())
    out = []
    for task in (await db.scalars(select(ScheduledTask).where(ScheduledTask.wall.is_not(None))
                                  .order_by(ScheduledTask.created_at))).all():
        if task.id in running or not _fixes(task.wall, kind, hs, ns):
            continue
        if not task.run_requested:
            task.run_requested = True
        out.append(task.name)
    return out


def retry_note(names: list[str]) -> str | None:
    """“之前卡在这里的「A」「B」已重新运行” —— 没有就 None。"""
    if not names:
        return None
    shown = "、".join(f"「{n}」" for n in names[:3]) + (f"等 {len(names)} 个任务" if len(names) > 3 else "")
    return f"之前卡在这里的{shown}已重新运行"


def brief(task: ScheduledTask) -> str:
    """task_brief.preface 里的一段：怎么报壁 + 上一次还挂着的壁。"""
    text = ("碰到只有用户能解决的障碍（网站要登录 needs_login:<域名>、连接器没连 needs_connector:<名字>、付费墙 paywall:<域名>），"
            "或会自己好的阻碍（页面搬走 source_gone:<域名>、验证码/限流 blocked:<原因>），用 schedule_task action=report_wall "
            "wall=<类>:<对象> text=<一两句发生了什么> 记下，再照常交付已经做完的部分；"
            "不要把“打不开 / 登录不了”当成结果内容。来源能打开只是没新东西，不算碰壁。")
    if task.wall:
        text += f"\n上一次碰壁：{error_text(task.wall, task.wall_reason)}。这次照常再试；还在就再报一次，好了就正常做完（会自动清掉）。"
    return text
