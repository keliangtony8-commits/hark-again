from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import chat_search, conversation_share, conversation_status, conversation_title, model_router, plan_mode, project_chat, quota, reasoning, reply_quote, run_conversations, turn_changes, turn_journal, usage, workspaces
from ..agent import context
from ..auth import require_user
from ..config import settings
from ..db import get_session
from ..models import Conversation, Message, Project
from ..wire_time import iso
from .inbox import mark_read

router = APIRouter(prefix="/api/conversations", tags=["conversations"], dependencies=[Depends(require_user)])


def _summary(c: Conversation, hit: tuple[str, str] | None = None, project_name: str | None = None) -> dict:
    """hit = (命中的消息 id, 摘录)：客户端据此打开对话后滚到那条消息并闪一下。
    project_name 只在搜索结果里给：命中的是某个项目那段对话（带 project_id，客户端跳进那个项目）。"""
    out = {"id": c.id, "title": c.title, "pinned": c.pinned, "model": c.model, "reasoning": c.reasoning,
           "routed_model": c.routed_model, "mode": c.mode or "default", "updated_at": iso(c.updated_at)}
    if hit:
        out["message_id"], out["snippet"] = hit
    if project_name is not None:
        out["project_id"], out["project_name"] = c.project_id, project_name
    return out


@router.get("")
async def list_conversations(project_id: str | None = None, q: str = "", db: AsyncSession = Depends(get_session)):
    """不带 project_id = 主聊天的对话（q = 按标题和消息内容搜索，空格分开的词都要有；置顶在前；
    v3.2.1 搜索范围 = 全部（主聊天 + 各项目），项目那段对话的结果带 project_id / project_name）。
    带 project_id = 这个项目的那段对话（v2.95 项目 = 一段对话：≤1 项、带 status；没有就当场建，幂等；不搜索）。"""
    if project_id:
        project = await db.get(Project, project_id)
        if project is None:
            raise HTTPException(404, "没有这个项目")
        conv = await project_chat.ensure(db, project)
        await db.commit()
        status = await conversation_status.for_list(db, [conv.id])
        return [{**_summary(conv), "status": status.get(conv.id)}]
    q = q.strip()
    if q:  # 规则在 chat_search（拆词 AND、摘录、最佳命中消息）；标题已含全部词的不带摘录/定位
        found = await chat_search.search(db, q, scope=chat_search.ALL, limit=50)
        names = await chat_search.project_names(db, {h.conversation.project_id for h in found})

        def where(c: Conversation) -> str | None:  # 项目那段对话 → 项目名；任务在项目里开的运行对话照旧按 id 直接打开
            return names.get(c.project_id) if c.project_id and not run_conversations.hidden(c) else None
        return [_summary(h.conversation, None if h.title_hit or not h.message_id else (h.message_id, h.snippet), where(h.conversation))
                for h in found]
    rows = (await db.scalars(select(Conversation).where(Conversation.project_id.is_(None), run_conversations.listed())
                             .order_by(Conversation.pinned.desc(), Conversation.updated_at.desc()).limit(100))).all()
    return [_summary(c) for c in rows]


class ConversationPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    pinned: bool | None = None
    model: str | None = None  # 别名；"" = 回到默认
    reasoning: str | None = None  # 思考强度（reasoning.EFFORTS）；"" = 回到模型默认
    mode: str | None = None  # 计划模式（plan_mode.MODES）：default | plan；"" = default


@router.patch("/{cid}")
async def patch_conversation(cid: str, body: ConversationPatch, db: AsyncSession = Depends(get_session)):
    """重命名 / 置顶 / 换模型 / 换思考强度。不改 updated_at，免得整理一下列表顺序就乱了。"""
    values = body.model_dump(exclude_none=True)
    if "model" in values:
        if values["model"] and not model_router.choosable(values["model"]):
            raise HTTPException(422, "没有这个模型")
        values["model"] = values["model"] or None
    if "reasoning" in values:
        if values["reasoning"] and not reasoning.valid(values["reasoning"]):
            raise HTTPException(422, "没有这个思考强度")
        values["reasoning"] = values["reasoning"] or None
    if "mode" in values:
        if values["mode"] and not plan_mode.valid(values["mode"]):
            raise HTTPException(422, "没有这个模式")
        values["mode"] = values["mode"] or plan_mode.DEFAULT
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
        "routed_model": c.routed_model,
        "mode": c.mode or "default",
        "messages": reply_quote.wire_all(list(c.messages)),
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


@router.post("/{cid}/messages/{mid}/changes/undo")
async def undo_changes(cid: str, mid: str, db: AsyncSession = Depends(get_session)):
    """整轮撤销：把这条回复改过的文件恢复到这一轮之前（规则在 turn_changes.py）。
    正在回复 → 409 busy；文件之后又被改过 → 409 {conflicts}（一个都不动）；记录过期 / 已撤销 → 410。返回更新后的消息。"""
    conv = await db.get(Conversation, cid)
    m = await db.get(Message, mid)
    if not conv or not m or m.conversation_id != cid:
        raise HTTPException(404)
    i = next((k for k, b in enumerate(m.blocks or []) if b.get("type") == "changes"), None)
    if i is None:
        raise HTTPException(404, "这条回复没有改动文件")
    if m.blocks[i].get("undone"):
        raise HTTPException(410, "已经撤销过了")
    if await turn_journal.busy(db, cid):
        raise HTTPException(409, {"reason": "busy", "message": "正在回复，等这一轮结束再撤销"})
    ws = workspaces.of(conv.project_id)
    try:
        turn_changes.undo(ws, m.blocks[i].get("token") or "")
    except turn_changes.Conflict as e:
        raise HTTPException(409, {"reason": "conflict", "message": str(e), "conflicts": e.paths}) from None
    except turn_changes.UndoError as e:
        raise HTTPException(410, str(e)) from None
    quota.forget(ws)
    m.blocks = [{**b, "undone": True} if k == i else b for k, b in enumerate(m.blocks)]  # 整体赋值，JSON 列才会被标脏
    await db.commit()
    return m.to_wire()


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
    if c and await run_conversations.busy(db, c):
        raise HTTPException(409, "这个定时任务还在跑，跑完再删")
    if c and not project_chat.deletable(c):
        raise HTTPException(409, "项目的对话随项目一起删除")
    if c:
        await db.delete(c)
        await db.commit()
    return {"ok": True}
