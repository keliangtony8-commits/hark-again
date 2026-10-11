"""智能体放到 Home 上的“我可以帮你做这件事”建议卡：唯一入口（工具 offer_on_home 只调这里）。

一张建议卡 = HomeCard(kind=action, origin=agent)：标题说事、正文一两句为什么现在做、主按钮写清点了会做什么
（action_label，空 = “去做”）。

点按钮 = POST /api/cards/{id}/start（start()）：服务端开一段新对话（标题 = 卡标题）、把对话 id 记在卡上，
客户端打开它并把 action_prompt 发进去。卡留在 Home 上变成“已交给助手”：主按钮改成“查看对话”回到那段对话，
用户看完自己收起。再点一次只回到同一段对话，不会重发指令（started=False）；那段对话被删了就重新开一段。
系统提醒（origin 空）不走这里：客户端直接把指令发进新对话，恢复后服务端自己收起卡。

规则：
- 同一标题的建议还在 Home 上 → 原地更新（正文/按钮/指令换新、重新未读、顶到最前），不叠两张。
- 同时在 Home 上的智能体建议最多 MAX_LIVE 张；再多就把最旧的一张收起（dismissed），系统提醒不算也不动。
- 稍后提醒中的卡也算“在 Home 上”（同标题会被叫回来更新）。
- 同标题重新提议 = 新的一件事：清掉旧的对话链接，按钮回到“可以替你做”。
- 配图 image / 原页 url 可选，只收 http(s) 且 ≤ URL_MAX；不合格抛 ValueError。配图能不能打开由调用方（工具）先探测，
  这里不联网。同标题重新提议时没给就清掉（新的一件事）。
- 按钮字 ≤ LABEL_MAX；标题 ≤ TITLE_MAX；指令必须写（点了要能独立执行，看不到当前对话）。
"""
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .blocks import text_to_blocks
from .models import Conversation, HomeCard

ORIGIN = "agent"
MAX_LIVE = 5
LABEL_MAX = 12
TITLE_MAX = 60
REASON_MAX = 400
URL_MAX = 1024


def clean_url(v: str | None, what: str) -> str | None:
    v = (v or "").strip()
    if not v:
        return None
    if not v.lower().startswith(("http://", "https://")) or len(v) > URL_MAX or any(ch.isspace() for ch in v):
        raise ValueError(f"{what}要是 http(s) 开头的真实网址（{URL_MAX} 字以内），不要自己拼。")
    return v


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
                now: datetime | None = None, image: str | None = None, url: str | None = None) -> tuple[HomeCard, str, list[HomeCard]]:
    """放一张建议卡；返回 (卡, "created"|"updated", 被挤下去的旧卡)。不合格抛 ValueError（中文，给模型看）。自己 commit。"""
    title, reason, prompt, label = _clean(title, reason, prompt, label)
    image, url = clean_url(image, "配图"), clean_url(url, "原页链接")
    now = now or datetime.now(timezone.utc)
    cards = await live(db)
    card = next((c for c in cards if c.title == title), None)
    status = "updated" if card else "created"
    if card is None:
        card = HomeCard(kind="action", origin=ORIGIN, title=title, created_at=now)
        db.add(card)
    card.blocks = text_to_blocks(reason) if reason else []
    card.action_prompt, card.action_label = prompt, label
    card.image_url, card.link_url = image, url
    card.unread, card.snoozed_until, card.updated_at = True, None, now
    card.conversation_id = None
    retired = []
    others = [c for c in cards if c is not card]
    for old in others[MAX_LIVE - 1:]:  # 新卡占一个位置
        old.dismissed, old.unread, old.snoozed_until = True, False, None
        retired.append(old)
    await db.commit()
    return card, status, retired


async def start(db: AsyncSession, card_id: str) -> tuple[HomeCard, bool]:
    """用户点了建议卡的主按钮：返回 (卡, 是否新开了对话)。新开 = 客户端要把 action_prompt 发进 card.conversation_id；
    否则只打开它。卡不存在 / 不是智能体建议 / 已收起 → LookupError；自己 commit。不改 updated_at（Home 顺序不跳）。"""
    card = await db.get(HomeCard, card_id)
    if card is None or card.kind != "action" or card.origin != ORIGIN or card.dismissed or not card.action_prompt:
        raise LookupError(card_id)
    cid, started = card.conversation_id, False
    if not cid or await db.get(Conversation, cid) is None:
        conv = Conversation(title=card.title[:200])
        db.add(conv)
        await db.flush()
        cid, started = conv.id, True
    # 显式写回 updated_at = 原值：onupdate 不触发，卡在 Home 上的位置不跳
    await db.execute(update(HomeCard).where(HomeCard.id == card.id)
                     .values(conversation_id=cid, unread=False, snoozed_until=None, updated_at=HomeCard.updated_at))
    await db.commit()
    await db.refresh(card)
    return card, started
