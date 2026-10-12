from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import conversation_share, conversation_title, reasoning, turn_journal, usage
from ..agent import context
from ..auth import require_user
from ..config import settings
from ..db import get_session
from ..models import Conversation, Message
from ..wire_time import iso
from .inbox import mark_read

router = APIRouter(prefix="/api/conversations", tags=["conversations"], dependencies=[Depends(require_user)])

SNIPPET = 36  # 命中位置前后各取多少字


def _summary(c: Conversation, hit: tuple[str, str] | None = None) -> dict:
    """hit = (命中的消息 id, 摘录)：客户端据此打开对话后滚到那条消息并闪一下。"""
    out = {"id": c.id, "title": c.title, "pinned": c.pinned, "model": c.model, "reasoning": c.reasoning,
           "updated_at": iso(c.updated_at)}
    if hit:
        out["message_id"], out["snippet"] = hit
    return out


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def snippet_of(text: str, q: str) -> str:
    """命中词前后一小段，压成一行；找不到就取开头。"""
    flat = " ".join(text.split())
    i = flat.lower().find(q.lower())
    if i < 0:
        return flat[: SNIPPET * 2]
    start, end = max(0, i - SNIPPET), min(len(flat), i + len(q) + SNIPPET)
    return ("…" if start else "") + flat[start:end] + ("…" if end < len(flat) else "")


@router.get("")
async def list_conversations(project_id: str | None = None, q: str = "", db: AsyncSession = Depends(get_session)):
    """不带 project_id = 主聊天的对话；带 = 该项目内的对话。q = 按标题和消息内容搜索。置顶在前。"""
    scope = Conversation.project_id == project_id if project_id else Conversation.project_id.is_(None)
    stmt = select(Conversation).where(scope)
    q = q.strip()
    if q:
        hit = select(Message.conversation_id).where(Message.search_text.ilike(_like(q), escape="\\"))
        stmt = stmt.where(or_(Conversation.title.ilike(_like(q), escape="\\"), Conversation.id.in_(hit)))
    rows = (await db.scalars(
        stmt.order_by(Conversation.pinned.desc(), Conversation.updated_at.desc()).limit(50 if q else 100))).all()
    if not q:
        return [_summary(c) for c in rows]
    # 内容命中的给最近一条命中消息的 id + 摘录（标题已命中的不需要：打开就是了）
    need = [c.id for c in rows if q.lower() not in c.title.lower()]
    found: dict[str, tuple[str, str]] = {}
    if need:
        msgs = await db.execute(
            select(Message.conversation_id, Message.id, Message.search_text)
            .where(Message.conversation_id.in_(need), Message.search_text.ilike(_like(q), escape="\\"))
            .order_by(Message.created_at.desc()))
        for cid, mid, text in msgs.all():
            if cid not in found:
                found[cid] = (mid, snippet_of(text, q))
    return [_summary(c, found.get(c.id)) for c in rows]


class ConversationPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    pinned: bool | None = None
    model: str | None = None  # 别名；"" = 回到默认
    reasoning: str | None = None  # 思考强度（reasoning.EFFORTS）；"" = 回到模型默认


@router.patch("/{cid}")
async def patch_conversation(cid: str, body: ConversationPatch, db: AsyncSession = Depends(get_session)):
    """重命名 / 置顶 / 换模型 / 换思考强度。不改 updated_at，免得整理一下列表顺序就乱了。"""
    values = body.model_dump(exclude_none=True)
    if "model" in values:
        if values["model"] and values["model"] not in settings.chat_models:
            raise HTTPException(422, "没有这个模型")
        values["model"] = values["model"] or None
    if "reasoning" in values:
        if values["reasoning"] and not reasoning.valid(values["reasoning"]):
            raise HTTPException(422, "没有这个思考强度")
        values["reasoning"] = values["reasoning"] or None
    if "title" in values:
        values["title"] = values["title"].strip()
        if not values["title"]:
            raise HTTPException(422, "标题不能为空")
        values["title_source"] = conversation_title.USER  # 用户起的名字自动标题永不覆盖
    if values:
        await db.execute(update(Conversation).where(Conversation.id == cid)
                         .values(**values, updated_at=Conversation.updated_at))
        await db.commit()
    c = await db.get(Conversation, cid, populate_existing=True)
    if not c:
        raise HTTPException(404)
    return _summary(c)


@router.get("/{cid}")
async def get_conversation(cid: str, db: AsyncSession = Depends(get_session)):
    await turn_journal.recover(db, cid)  # 进程崩掉留下的半截回答（心跳停了）→ interrupted 消息，打开就能看到
    c = await db.scalar(select(Conversation).where(Conversation.id == cid).options(selectinload(Conversation.messages)))
    if not c:
        raise HTTPException(404)
    await mark_read(db, conversation_id=cid)  # 打开报告的对话 = 读过它
    await db.commit()
    return {
        "id": c.id,
        "title": c.title,
        "pinned": c.pinned,
        "model": c.model,
        "reasoning": c.reasoning,
        "messages": [m.to_wire() for m in c.messages],
    }


@router.get("/{cid}/usage")
async def conversation_usage(cid: str, db: AsyncSession = Depends(get_session)):
    """本对话累计 token / 花费，按模型拆分。单独一个接口：打开对话不必每次都汇总用量。"""
    if not await db.get(Conversation, cid):
        raise HTTPException(404)
    return await usage.conversation_report(db, cid)


@router.get("/{cid}/context")
async def conversation_context(cid: str, db: AsyncSession = Depends(get_session)):
    """对话记忆的现状：下一轮发给模型的原文多大、多少条已压成滚动摘要（及摘要正文）、还有几条可以手动整理。"""
    if not await db.get(Conversation, cid):
        raise HTTPException(404)
    return await context.context_state(db, cid)


@router.post("/{cid}/compact")
async def compact_conversation(cid: str, db: AsyncSession = Depends(get_session)):
    """手动整理上文：把最后一问之前的原文都并进滚动摘要（Codex /compact）。正在回复 → 409；摘要模型出错 → 502。"""
    if not await db.get(Conversation, cid):
        raise HTTPException(404)
    try:
        return await context.compact_now(db, cid)
    except context.CompactBusy:
        raise HTTPException(409, "正在回复，等这一轮结束再整理") from None
    except LookupError:
        raise HTTPException(404) from None
    except Exception as e:  # noqa: BLE001 — 摘要模型挂了：原文和摘要都没动
        await db.rollback()
        raise HTTPException(502, f"整理失败：{e}") from None


async def _with_messages(db: AsyncSession, cid: str) -> Conversation:
    c = await conversation_share.load(db, cid)
    if not c:
        raise HTTPException(404)
    return c


@router.get("/{cid}/share")
async def share_state(cid: str, db: AsyncSession = Depends(get_session)):
    """分享状态：{shared:false} 或 页面 + stale（快照之后对话又有变化）。逻辑全在 conversation_share。"""
    c = await _with_messages(db, cid)
    return conversation_share.state(c, c.messages)


@router.post("/{cid}/share")
async def share(cid: str, db: AsyncSession = Depends(get_session)):
    """生成 / 更新只读网页快照并公开，同一对话链接不变。"""
    c = await _with_messages(db, cid)
    return conversation_share.share(c, c.messages)


@router.delete("/{cid}/share")
async def unshare(cid: str, db: AsyncSession = Depends(get_session)):
    """停止分享 = 页面下线（链接保留，再分享原链接恢复）。"""
    c = await _with_messages(db, cid)
    return conversation_share.unshare(c, c.messages)


@router.delete("/{cid}")
async def delete_conversation(cid: str, db: AsyncSession = Depends(get_session)):
    c = await db.get(Conversation, cid)
    if c:
        await db.delete(c)
        await db.commit()
    return {"ok": True}
