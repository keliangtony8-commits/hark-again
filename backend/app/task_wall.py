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
客户端只读 wire() 给的 wall_label / wall_fixable / wall_open，不自己解释壁的字符串。"""
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
    """接口给任务补的只读字段（schedule.wire 调用）：客户端只认这三个。"""
    return {"wall_label": label(task.wall), "wall_fixable": fixable(task.wall), "wall_open": open_page(task.wall)}


def brief(task: ScheduledTask) -> str:
    """task_brief.preface 里的一段：怎么报壁 + 上一次还挂着的壁。"""
    text = ("碰到只有用户能解决的障碍（网站要登录 needs_login:<域名>、连接器没连 needs_connector:<名字>、付费墙 paywall:<域名>），"
            "或会自己好的阻碍（页面搬走 source_gone:<域名>、验证码/限流 blocked:<原因>），用 schedule_task action=report_wall "
            "wall=<类>:<对象> text=<一两句发生了什么> 记下，再照常交付已经做完的部分；"
            "不要把“打不开 / 登录不了”当成结果内容。来源能打开只是没新东西，不算碰壁。")
    if task.wall:
        text += f"\n上一次碰壁：{error_text(task.wall, task.wall_reason)}。这次照常再试；还在就再报一次，好了就正常做完（会自动清掉）。"
    return text
