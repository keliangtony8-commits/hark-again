"""Home 卡片的“去处”（HomeCard.target）：卡上一颗按钮直达客户端里对应的那一页。唯一入口（工具、系统提醒都只调这里）。

存法：target = 名字，或 名字:id（带具体对象）。task 的 id 存在卡的 task_id 上（老规矩，target 仍是 "tasks"）。
两个客户端各有一张同样的表（App features/home/action_card.dart cardTargets、网页 lib/cardTargets.ts），
不认识的值客户端当没有，所以加新去处 = 三处各加一行，老客户端不出错。

| 模型写的 open      | 存成                         | 客户端打开            |
| usage / memory / connectors / skills / pages / tasks | 同名 | “我的”下对应页（connectors = 连接的账号：OAuth、MCP、网站登录、API Key、环境变量同一页；v2.96 起没有单独的 vault） |
| task:<任务 id>     | target=tasks, task_id=<id>   | 那个任务的详情        |
| project:<项目 id>  | target=project:<id>          | 那个项目（点“去做”开的对话也放进这个项目） |
"""
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Project, ScheduledTask

PAGES = {"usage": "用量", "memory": "记忆", "connectors": "连接的账号",
         "skills": "技能", "pages": "网页", "tasks": "定时任务"}
TARGET_MAX = 64  # home_cards.target 列宽（迁移 0022）
HELP = ("open 只能是 " + " / ".join(PAGES) + "，或 task:<任务 id>、project:<项目 id>（id 先用 manage_tasks / 项目列表查）。")


async def resolve(db: AsyncSession, value: str | None) -> tuple[str | None, str | None]:
    """模型给的 open → (target, task_id)。空 → (None, None)。不认识 / 对象不存在 → ValueError（中文，给模型看）。"""
    v = (value or "").strip()
    if not v:
        return None, None
    name, _, arg = v.partition(":")
    name, arg = name.strip().lower(), arg.strip()
    if name in PAGES and not arg:
        return name, None
    if name == "task" and arg:
        if await db.get(ScheduledTask, arg) is None:
            raise ValueError(f"没有 id={arg} 的定时任务。" + HELP)
        return "tasks", arg
    if name == "project" and arg:
        if await db.get(Project, arg) is None:
            raise ValueError(f"没有 id={arg} 的项目。" + HELP)
        return f"project:{arg}", None
    raise ValueError(f"不认识的去处“{v}”。" + HELP)


def project_of(target: str | None) -> str | None:
    """去处是某个项目 → 项目 id（建议卡开的对话放进这个项目）。"""
    name, _, arg = (target or "").partition(":")
    return (arg or None) if name == "project" else None


def describe(target: str | None, task_id: str | None) -> str:
    """manage_home list 里的一句“去处 …”。"""
    if not target:
        return ""
    if target == "tasks" and task_id:
        return f"task:{task_id}"
    return target
