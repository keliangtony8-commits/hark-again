"""v2.17 移除的面板可以找回（对齐 Hark widget_sdk dismiss / revive：“recently dismissed panels, revivable by their card_id;
its spec returns, its data re-gathers”）。这里是“移除面板 / 最近移除 / 找回”的唯一规则，接口和 manage_home 工具共用。

移除 = 背后的任务连同运行记录、它的提醒/报告卡一起删掉（worker、任务列表、今天日程都不用认识“已移除”这种状态），
面板卡本身留下：dismissed=True、task_id=None、removed_at=现在、revive_spec = 任务的“做法”快照（名字、刷新指令、cron、
模型、思考强度、runbook、note）。KEEP_DAYS 天内可以找回；过期由 worker 每轮 purge 删掉。
找回 = 按快照新建一个 output=panel 的任务（run_requested=True，半分钟内重新取数据），卡接回去、旧内容先留着
（刷新完原地换新）、顶到最前。任务详情页里“删除任务”仍是彻底删除（那里说清了会连卡一起删）。
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from . import panel_log, schedule, task_runs
from .models import HomeCard, ScheduledTask

KEEP_DAYS = 30
LISTED = 10  # 工具 list 里最多列几张最近移除的
# v2.55 + kind（记录面板找回还是记录面板）、id（旧任务 id：找回时把它名下的每一笔接到新任务）
SPEC_KEYS = ("id", "kind", "name", "prompt", "cron", "model", "reasoning", "runbook", "note")


def _aware(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)  # SQLite 读回来没有时区，存的是 UTC


def revivable(card: HomeCard, now: datetime | None = None) -> bool:
    if card.kind != "panel" or not card.dismissed or card.removed_at is None or not card.revive_spec:
        return False
    return _aware(card.removed_at) > (now or datetime.now(timezone.utc)) - timedelta(days=KEEP_DAYS)


def wire(card: HomeCard) -> dict:
    """接口补的只读字段：revivable（客户端只认它决定要不要列进“最近移除”）+ 带时区的 removed_at。快照本身不发。"""
    return {"revivable": revivable(card), "removed_at": _aware(card.removed_at) if card.removed_at else None,
            "revive_spec": None}


async def remove(db, card: HomeCard) -> HomeCard:
    """把面板从 Home 拿掉（可找回）。不是面板 → ValueError；已经移除过 → 原样返回。commit。"""
    if card.kind != "panel":
        raise ValueError(f"「{card.title}」不是面板")
    if card.removed_at is not None:
        return card
    task = await db.get(ScheduledTask, card.task_id) if card.task_id else None
    if task is not None:
        card.revive_spec = {k: getattr(task, k) for k in SPEC_KEYS}
        await db.execute(delete(HomeCard).where(HomeCard.task_id == task.id, HomeCard.id != card.id))  # 它的失败提醒等
        await task_runs.remove_for(db, task.id)
        await db.delete(task)
    card.task_id = None
    card.dismissed = True
    card.unread = False
    card.snoozed_until = None
    card.removed_at = datetime.now(timezone.utc)
    await db.commit()
    return card


async def revive(db, card_id: str) -> tuple[HomeCard, ScheduledTask]:
    """找回：不在 / 不是移除的面板 / 过了 KEEP_DAYS → LookupError（中文原因）。commit。"""
    card = await db.get(HomeCard, card_id)
    if card is None or not revivable(card):
        why = "已经超过 30 天，找不回来了" if card is not None and card.removed_at is not None else "不是最近移除的面板"
        raise LookupError(f"这张卡{why}")
    spec = dict(card.revive_spec)
    cron = (spec.get("cron") or "").strip()
    try:
        schedule.check(cron, None)
    except ValueError:
        cron = "0 8 * * *"  # 快照里的 cron 现在不成立（极少见）：先每天早上刷新，用户可再改
    task = ScheduledTask(name=spec.get("name") or card.title, prompt=spec.get("prompt") or card.title, cron=cron,
                         output="panel", run_requested=True, model=spec.get("model"), reasoning=spec.get("reasoning"),
                         runbook=spec.get("runbook"), note=spec.get("note"), kind=spec.get("kind") or "agent")
    db.add(task)
    await db.flush()
    await panel_log.adopt(db, spec.get("id"), task.id)
    card.task_id = task.id
    card.title = task.name
    card.dismissed = False
    card.removed_at = None
    card.revive_spec = None
    card.updated_at = datetime.now(timezone.utc)  # 顶到最前
    await db.commit()
    return card, task


async def recent(db) -> list[HomeCard]:
    """最近移除、还能找回的面板，新的在前（最多 LISTED 张）。"""
    rows = (await db.scalars(select(HomeCard).where(HomeCard.kind == "panel", HomeCard.removed_at.is_not(None))
                             .order_by(HomeCard.removed_at.desc()))).all()
    return [c for c in rows if revivable(c)][:LISTED]


async def purge(db, now: datetime | None = None) -> int:
    """删掉移除超过 KEEP_DAYS 天的面板卡。返回删了几张；commit。"""
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=KEEP_DAYS)
    old = (await db.scalars(select(HomeCard).where(HomeCard.kind == "panel", HomeCard.removed_at.is_not(None),
                                                   HomeCard.removed_at < cutoff))).all()
    await panel_log.drop(db, [(c.revive_spec or {}).get("id") for c in old])  # 记录面板的每一笔跟着卡走
    if old:  # 按 id 删（已载入会话：按时间比较会在 Python 里拿 naive / aware 比）
        await db.execute(delete(HomeCard).where(HomeCard.id.in_([c.id for c in old])))
    await db.commit()
    return len(old)
