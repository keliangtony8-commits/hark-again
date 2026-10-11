"""系统提醒：服务器自己发现、需要告诉用户的事，统一成 Home 上的一张 action 卡。唯一入口（预算、任务失败、连接失效都只调这里）。

一张系统提醒 = HomeCard(kind=action, origin=None)：
- 去处 open 走 card_targets.resolve（"usage" / "connectors" / "task:<id>"…），客户端显示直达那一页的按钮；
- prompt 可选：有 = 卡上有“去做”（交给助手分析）；没有 = 只能本人处理的事（重新连接账号），客户端眉题“需要你亲自处理”；
- 去重靠 alerts_sent（key 由调用方定：同一件事只发一次，用户忽略/删卡后也不再打扰）；
- replace=True：同一去处（target + task_id）还挂着的旧系统提醒先收起（新的一档预算顶掉旧的一档）；
- 事情恢复了（任务又成功、账号重新连上）→ clear(open) 收起这一去处的系统提醒。
智能体提议的卡（origin=agent，app/home_offers.py）永远不被这里收起。只 flush 不 commit，事务由调用方收尾。"""
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from . import card_targets
from .blocks import text_to_blocks
from .models import AlertSent, HomeCard


def _same_place(target: str | None, task_id: str | None):
    q = [HomeCard.kind == "action", HomeCard.origin.is_(None), HomeCard.dismissed.is_(False), HomeCard.target == target]
    q.append(HomeCard.task_id == task_id if task_id else HomeCard.task_id.is_(None))
    return q


async def post(db: AsyncSession, *, key: str, title: str, text: str, open: str,
               prompt: str | None = None, replace: bool = True) -> HomeCard | None:
    """发一张系统提醒；这件事（key）发过 → None。open 不认识 / 对象不存在 → ValueError（调用方的错）。"""
    target, task_id = await card_targets.resolve(db, open)
    if target is None:
        raise ValueError("系统提醒必须有去处")
    if await db.get(AlertSent, key):
        return None
    try:
        async with db.begin_nested():  # 并发的另一处同时发同一件事：主键冲突 = 它已经发了
            db.add(AlertSent(key=key))
    except IntegrityError:
        return None
    if replace:
        await db.execute(update(HomeCard).where(*_same_place(target, task_id)).values(dismissed=True))
    card = HomeCard(kind="action", title=title[:200], blocks=text_to_blocks(text), target=target, task_id=task_id,
                    action_prompt=prompt or None, unread=True)
    db.add(card)
    await db.flush()
    return card


async def clear(db: AsyncSession, open: str) -> int:
    """这一去处的事恢复了：收起它还挂着的系统提醒，返回收起几张。对象已不存在 → 0。"""
    try:
        target, task_id = await card_targets.resolve(db, open)
    except ValueError:
        return 0
    r = await db.execute(update(HomeCard).where(*_same_place(target, task_id)).values(dismissed=True))
    return r.rowcount or 0
