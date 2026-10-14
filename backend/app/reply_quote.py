"""引用回复（home-redesign §J / §C 的用户侧）：一条用户消息 reply_to = 它回的那条消息的 id。这里是唯一规则：
- valid：只认同一对话里、已落库的 user / assistant 消息；别的（别的对话、不存在、乱写）一律当没引用，不报错。
- wire：协议里的 quote = {id, role, text}（原文截断 SNIPPET 字，给气泡顶上那一行）；原消息已删 → {id, missing: true}。
- render：给模型的前缀——当前这一问给被引原文（截断 PREFIX 字），更早的只留一句记录（RECORD 字），不额外调模型。
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .blocks import blocks_to_text
from .models import Message

SNIPPET = 120   # 气泡顶上引用条 / 输入框引用条
PREFIX = 300    # 当前这一问给模型的被引原文
RECORD = 40     # 更早的消息里留给模型的一句记录
ROLES = ("user", "assistant")


def text_of(blocks: list[dict]) -> str:
    """消息的纯文字（没有文字就用附件名），压成一行。"""
    text = blocks_to_text([b for b in blocks if b.get("type") not in ("file", "skill", "agent", "origin")])
    if not text.strip():
        names = "、".join(b.get("name") or "" for b in blocks if b.get("type") == "file" and b.get("name"))
        text = f"[附件] {names}" if names else ""
    return " ".join(text.split())


def cut(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


async def valid(db: AsyncSession, conversation_id: str | None, reply_to) -> str | None:
    """客户端给的 reply_to → 能用的 id 或 None（新对话、跨对话、不存在、角色不对都丢掉）。"""
    if not conversation_id or not isinstance(reply_to, str) or not reply_to or len(reply_to) > 32:
        return None
    m = await db.get(Message, reply_to)
    return m.id if m is not None and m.conversation_id == conversation_id and m.role in ROLES else None


def quote(rid: str, target: Message | None) -> dict:
    if target is None:
        return {"id": rid, "missing": True}
    return {"id": rid, "role": target.role, "text": cut(text_of(target.blocks), SNIPPET)}


def wire_all(messages: list[Message]) -> list[dict]:
    """一整段对话的协议形状：被引消息在这段里找，找不到 = 已删除。"""
    by_id = {m.id: m for m in messages}
    return [m.to_wire(quote(m.reply_to, by_id.get(m.reply_to)) if m.reply_to else None) for m in messages]


async def wire_one(db: AsyncSession, m: Message) -> dict:
    if not m.reply_to:
        return m.to_wire()
    t = await db.get(Message, m.reply_to)
    return m.to_wire(quote(m.reply_to, t if t is not None and t.conversation_id == m.conversation_id else None))


def render(target: Message | None, current: bool) -> str:
    """接在用户这句话前面给模型看的一行。"""
    if target is None:
        return "（用户在回复一条已经删掉的消息）\n"
    who = "你" if target.role == "assistant" else "用户自己"
    if current:
        return f"（用户在回复{who}之前说的：「{cut(text_of(target.blocks), PREFIX)}」）\n"
    return f"（回复{who}之前说的「{cut(text_of(target.blocks), RECORD)}」）\n"

