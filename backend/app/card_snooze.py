"""Home 卡片的“稍后提醒”：唯一入口。接口 PATCH、智能体工具 manage_home、worker 叫醒都走这里。

规则：
- 只有建议（action）和收件箱（report）能推迟；面板本身就按计划刷新，不推迟。
- 推迟到的时刻必须在将来、且不超过 MAX_DAYS 天；推迟时清掉未读（收起来的卡不该再顶着角标）。
- 到点由 worker 每轮 wake_due()：清空 snoozed_until、重新标未读、updated_at=现在（排到最前，像新来的一样）。
- 客户端只看 snoozed_until 是否为空来决定藏不藏，不比本机时钟——叫醒的时刻以服务端为准。
- 忽略（dismissed）一张推迟中的卡：一并清掉 snoozed_until，免得过后又被叫醒。
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import HomeCard

KINDS = ("action", "report")
MAX_DAYS = 30


def _aware(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)  # SQLite 读回来没有时区，存的是 UTC


def check(card: HomeCard, until: datetime, now: datetime | None = None) -> datetime:
    """能否把 card 推迟到 until；不行抛 ValueError（中文原因，给用户/模型看）。返回 UTC 时刻。"""
    now = _aware(now or datetime.now(timezone.utc))
    if card.kind not in KINDS:
        raise ValueError("面板会按计划自己刷新，不能稍后提醒。")
    if card.dismissed:
        raise ValueError("这张卡已经忽略了。")
    until = _aware(until).astimezone(timezone.utc)
    if until <= now:
        raise ValueError("提醒时间要在将来。")
    if until > now + timedelta(days=MAX_DAYS):
        raise ValueError(f"最多推迟 {MAX_DAYS} 天。")
    return until


def snooze(card: HomeCard, until: datetime, now: datetime | None = None) -> None:
    card.snoozed_until = check(card, until, now)
    card.unread = False


def on_patch(card: HomeCard, changes: dict) -> None:
    """crud on_update 钩子：校验 snoozed_until，推迟时顺带清未读；忽略时清掉推迟。ValueError → 由路由转 422。"""
    if changes.get("dismissed"):
        changes["snoozed_until"] = None
    elif changes.get("snoozed_until") is not None:
        changes["snoozed_until"] = check(card, changes["snoozed_until"])
        changes["unread"] = False


async def wake_due(db: AsyncSession, now: datetime | None = None) -> int:
    """叫醒到点的卡，返回叫醒了几张。worker 每轮调一次；自己 commit。"""
    now = now or datetime.now(timezone.utc)
    r = await db.execute(update(HomeCard)
                         .where(HomeCard.snoozed_until.is_not(None), HomeCard.snoozed_until <= now,
                                HomeCard.dismissed.is_(False))
                         .values(snoozed_until=None, unread=True, updated_at=now))
    await db.commit()
    return r.rowcount or 0


def wire(card: HomeCard) -> dict:
    """接口补的只读字段：snoozed_until 统一成带时区的 UTC（SQLite 读回来是裸时间，客户端会误当本地时间）。"""
    return {"snoozed_until": _aware(card.snoozed_until) if card.snoozed_until else None}
