"""智能体放到 Home 上的“我可以帮你做这件事”建议卡：唯一入口（工具 offer_on_home 只调这里）。

一张建议卡 = HomeCard(kind=action, origin=agent)：标题说事、正文一两句为什么现在做、主按钮写清点了会做什么
（action_label，空 = “去做”），点按钮 = 客户端把 action_prompt 发进新对话并把卡收起（只对 origin=agent 的卡这样做，
系统提醒恢复后会自己收起，所以点了不拿掉）。

规则：
- 同一标题的建议还在 Home 上 → 原地更新（正文/按钮/指令换新、重新未读、顶到最前），不叠两张。
- 同时在 Home 上的智能体建议最多 MAX_LIVE 张；再多就把最旧的一张收起（dismissed），系统提醒不算也不动。
- 稍后提醒中的卡也算“在 Home 上”（同标题会被叫回来更新）。
- 按钮字 ≤ LABEL_MAX；标题 ≤ TITLE_MAX；指令必须写（点了要能独立执行，看不到当前对话）。
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .blocks import text_to_blocks
from .models import HomeCard

ORIGIN = "agent"
MAX_LIVE = 5
LABEL_MAX = 12
TITLE_MAX = 60
REASON_MAX = 400


def _clean(title: str, reason: str, prompt: str, label: str | None) -> tuple[str, str, str, str | None]:
    title, reason, prompt = (title or "").strip(), (reason or "").strip(), (prompt or "").strip()
    label = (label or "").strip() or None
    if not title:
        raise ValueError("建议要有标题。")
    if len(title) > TITLE_MAX:
        raise ValueError(f"标题太长了，{TITLE_MAX} 字以内。")
    if not prompt:
        raise ValueError("要写 prompt：用户点按钮后发给助手的完整指令。")
    if label and len(label) > LABEL_MAX:
        raise ValueError(f"按钮上的字太长了，{LABEL_MAX} 字以内，比如“帮我订”“起草回复”。")
    if label == "去做":
        label = None
    return title, reason[:REASON_MAX], prompt, label


async def live(db: AsyncSession) -> list[HomeCard]:
    """Home 上还在的智能体建议（含稍后提醒中的），最新在前。"""
    q = (select(HomeCard).where(HomeCard.kind == "action", HomeCard.origin == ORIGIN, HomeCard.dismissed.is_(False))
         .order_by(HomeCard.updated_at.desc()))
    return list((await db.scalars(q)).all())


async def offer(db: AsyncSession, title: str, reason: str, prompt: str, label: str | None = None,
                now: datetime | None = None) -> tuple[HomeCard, str, list[HomeCard]]:
    """放一张建议卡；返回 (卡, "created"|"updated", 被挤下去的旧卡)。不合格抛 ValueError（中文，给模型看）。自己 commit。"""
    title, reason, prompt, label = _clean(title, reason, prompt, label)
    now = now or datetime.now(timezone.utc)
    cards = await live(db)
    card = next((c for c in cards if c.title == title), None)
    status = "updated" if card else "created"
    if card is None:
        card = HomeCard(kind="action", origin=ORIGIN, title=title, created_at=now)
        db.add(card)
    card.blocks = text_to_blocks(reason) if reason else []
    card.action_prompt, card.action_label = prompt, label
    card.unread, card.snoozed_until, card.updated_at = True, None, now
    retired = []
    others = [c for c in cards if c is not card]
    for old in others[MAX_LIVE - 1:]:  # 新卡占一个位置
        old.dismissed, old.unread, old.snoozed_until = True, False, None
        retired.append(old)
    await db.commit()
    return card, status, retired
