"""系统提醒：服务器自己发现、需要告诉用户的事，统一成 Home 上的一张 action 卡。唯一入口（预算、任务失败、连接失效、MCP 连不上都只调这里）。

一张系统提醒 = HomeCard(kind=action, origin=None, alert_subject=<主体>)：
- subject = 出事的那个东西（"budget"、"task:<id>"、"connector:<provider>"、"mcp:<服务器 id>"）——收起、顶替都按主体，
  不按去处：同在连接器页的 GitHub 失效卡和 MCP 连不上卡互不影响；
- 去处 open 走 card_targets.resolve（"usage" / "connectors" / "task:<id>"…），客户端显示直达那一页的按钮；
- prompt 可选：有 = 卡上有“去做”（交给助手分析）；没有 = 只能本人处理的事（重新连接、修服务器），客户端眉题“需要你亲自处理”；
- 去重：alerts_sent 键 = "<subject>:<once>"，同一件事只发一次，用户忽略/删卡后也不再打扰；
- replace=True：同一主体还挂着的旧提醒先收起（新的一档预算顶掉旧的一档）；
- 事情恢复了（任务又成功、账号重连、服务器又通）→ clear(subject)：收起它的提醒，并清掉它的去重键——之后再坏会再提醒一次。
智能体提议的卡（origin=agent，app/home_offers.py）永远不被这里收起。只 flush 不 commit，事务由调用方收尾。"""
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from . import card_targets
from .blocks import text_to_blocks
from .models import AlertSent, HomeCard

SUBJECT_MAX = 96  # home_cards.alert_subject 列宽（迁移 0023）


def _live(subject: str):
    return [HomeCard.kind == "action", HomeCard.origin.is_(None), HomeCard.dismissed.is_(False),
            HomeCard.alert_subject == subject]


def _key(subject: str, once: str) -> str:
    return f"{subject}:{once}"[:96]


async def post(db: AsyncSession, *, subject: str, once: str, title: str, text: str, open: str,
               prompt: str | None = None, replace: bool = True) -> HomeCard | None:
    """发一张系统提醒；这件事（subject + once）发过 → None。open 不认识 / 对象不存在 → ValueError（调用方的错）。"""
    if not subject or len(subject) > SUBJECT_MAX:
        raise ValueError("系统提醒必须有主体")
    target, task_id = await card_targets.resolve(db, open)
    if target is None:
        raise ValueError("系统提醒必须有去处")
    key = _key(subject, once)
    if await db.get(AlertSent, key):
        return None
    try:
        async with db.begin_nested():  # 并发的另一处同时发同一件事：主键冲突 = 它已经发了
            db.add(AlertSent(key=key))
    except IntegrityError:
        return None
    if replace:
        await db.execute(update(HomeCard).where(*_live(subject)).values(dismissed=True))
    card = HomeCard(kind="action", title=title[:200], blocks=text_to_blocks(text), target=target, task_id=task_id,
                    action_prompt=prompt or None, alert_subject=subject, unread=True)
    db.add(card)
    await db.flush()
    return card


async def active(db: AsyncSession, subject: str) -> list[str]:
    """这个主体还没恢复的事（去重键里 subject 之后那段，如 ["down"]）；没有 → []。"""
    keys = (await db.scalars(select(AlertSent.key).where(AlertSent.key.startswith(subject + ":")))).all()
    return [k[len(subject) + 1:] for k in keys]


async def clear(db: AsyncSession, subject: str) -> int:
    """这个主体的事恢复了：收起它还挂着的系统提醒、清掉去重键（再坏再提醒），返回收起几张。"""
    r = await db.execute(update(HomeCard).where(*_live(subject)).values(dismissed=True))
    await db.execute(delete(AlertSent).where(AlertSent.key.startswith(subject + ":")))
    return r.rowcount or 0
