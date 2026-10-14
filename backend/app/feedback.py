"""反馈的唯一规则（v2.64，对标 Hark 设置 → Feedback 的“报告问题”和回复下的 👍 / 👎）。

自建助手的主人同时是开发者：手机上看到一条答坏的回复，当场点 👎 选个原因，就该留下一份“能复现”的报告——
提问原文、回复原文、这一轮每一步做了什么（时间线 steps）、模型拿到过的工具结果（轨迹 trace，已截短打码）、
用的哪个模型 / 思考强度 / 模式、回复是怎么结束的。之后在“我的 → 反馈”里翻看、标已解决、一键复制成
Markdown 贴给谁修都行。对话删了报告还在（是快照，不是指针）。

- 一条回复只有一份评价：再点一次换原因 = 覆盖（upsert by message_id）；取消 = 删报告、消息上的标记清掉；
- messages.feedback 存当前评价（good / wrong / incomplete / stuck / other），随 to_wire 下发，两端回复下的
  👍 / 👎 直接画实心；
- 没有对应回复的“问题报告”（kind=problem）：用户自己写一段话，必填；
- 报告里的轨迹再过一遍 command_env.scrub（用户保存的环境变量值不会出现在复制出去的文字里）。
"""
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import clock, command_env
from .blocks import blocks_to_text
from .models import Conversation, Feedback, Message
from .wire_time import iso

# 回复下能选的评价（👍 = good，其余是 👎 的原因）；problem = 设置页里自己写的问题报告
MESSAGE_KINDS = {"good": "有用", "wrong": "答错了", "incomplete": "没做完", "stuck": "太慢或卡住了", "other": "别的问题"}
KINDS = {**MESSAGE_KINDS, "problem": "问题报告"}
STATUSES = ("open", "resolved")

NOTE_MAX = 2000      # 用户补充的话
QUESTION_MAX = 1500  # 快照里的提问
ANSWER_MAX = 6000    # 快照里的回复
STEPS_MAX = 40       # 快照里最多几步（留最近的）
TRACE_MAX = 8000     # 快照里工具轨迹的文字（留结尾，最后几步最可能是出事的地方）
EXCERPT_MAX = 80     # 列表一行摘要


class FeedbackError(ValueError):
    """用户能看懂的一句话；路由转 400 / 404。"""

    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _clip(text: str, limit: int, tail: bool = False) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return "…" + text[-limit:] if tail else text[:limit] + "…"


def _note(note: str | None) -> str:
    return _clip(note or "", NOTE_MAX)


def trace_text(trace: list) -> str:
    """工具轨迹（OpenAI 消息形状）→ 可读文字：→ 工具(参数) / ← 结果。超长留结尾。"""
    lines: list[str] = []
    for m in trace or []:
        if not isinstance(m, dict):
            continue
        if m.get("role") == "assistant":
            for c in m.get("tool_calls") or []:
                fn = (c or {}).get("function") or {}
                lines.append(f"→ {fn.get('name', '?')}({fn.get('arguments', '')})")
        elif m.get("role") == "tool":
            content = m.get("content")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            lines.append("← " + content.replace("\n", "\n  "))
    return _clip(command_env.scrub("\n".join(lines)), TRACE_MAX, tail=True)


def _steps(steps: list) -> list[dict]:
    out = []
    for s in (steps or [])[-STEPS_MAX:]:
        if not isinstance(s, dict):
            continue
        row = {k: s[k] for k in ("title", "detail", "state", "ms", "note") if s.get(k) not in (None, "")}
        if row:
            out.append(row)
    return out


def snapshot(conv: Conversation, msg: Message, question: Message | None) -> dict:
    """一条回复的可复现快照。只读已经落库的字段，不碰模型。"""
    return {
        "conversation_title": conv.title,
        "project_id": conv.project_id,  # 项目里的对话：客户端“打开对话”要先切到那个项目
        "question": _clip(blocks_to_text(question.blocks) if question else "", QUESTION_MAX),
        "answer": _clip(blocks_to_text(msg.blocks or []), ANSWER_MAX),
        "status": msg.status or "done",
        "model": conv.model or "",
        "routed_model": conv.routed_model or "",
        "reasoning": conv.reasoning or "",
        "mode": conv.mode or "default",
        "steps": _steps(msg.steps),
        "trace": trace_text(msg.trace),
        "message_at": iso(msg.created_at) if msg.created_at else None,
    }


async def _question_for(db: AsyncSession, msg: Message) -> Message | None:
    """这条回复前面最近的一条用户消息。"""
    rows = (await db.execute(
        select(Message).where(Message.conversation_id == msg.conversation_id, Message.role == "user",
                              Message.created_at <= msg.created_at)
        .order_by(Message.created_at.desc()).limit(1))).scalars().all()
    return rows[0] if rows else None


async def _report_of(db: AsyncSession, message_id: str) -> Feedback | None:
    return (await db.execute(select(Feedback).where(Feedback.message_id == message_id))).scalars().first()


async def rate(db: AsyncSession, message_id: str, kind: str, note: str | None = None) -> Feedback:
    """给一条回复打评价（新建或覆盖）。"""
    if kind not in MESSAGE_KINDS:
        raise FeedbackError("不认识的评价")
    msg = await db.get(Message, message_id)
    if msg is None:
        raise FeedbackError("这条回复不在了", 404)
    if msg.role != "assistant":
        raise FeedbackError("只能评价助手的回复")
    conv = await db.get(Conversation, msg.conversation_id)
    snap = snapshot(conv, msg, await _question_for(db, msg))
    fb = await _report_of(db, message_id)
    if fb is None:
        fb = Feedback(message_id=message_id, conversation_id=msg.conversation_id)
        db.add(fb)
    fb.kind, fb.note, fb.snapshot = kind, _note(note), snap
    fb.status, fb.resolved_at, fb.created_at = "open", None, datetime.now(timezone.utc)
    msg.feedback = kind
    await db.commit()
    await db.refresh(fb)
    return fb


async def unrate(db: AsyncSession, message_id: str) -> bool:
    """取消评价：删报告 + 清消息上的标记。原本就没有 → False。"""
    msg = await db.get(Message, message_id)
    fb = await _report_of(db, message_id)
    if msg is None and fb is None:
        raise FeedbackError("这条回复不在了", 404)
    had = fb is not None or bool(msg and msg.feedback)
    if fb is not None:
        await db.delete(fb)
    if msg is not None:
        msg.feedback = None
    await db.commit()
    return had


async def report(db: AsyncSession, note: str) -> Feedback:
    """设置页的“报告问题”：没有对应回复，用户写的话必填。"""
    text = _note(note)
    if not text:
        raise FeedbackError("说说遇到了什么问题")
    fb = Feedback(kind="problem", note=text, snapshot={})
    db.add(fb)
    await db.commit()
    await db.refresh(fb)
    return fb


async def get(db: AsyncSession, fid: str) -> Feedback:
    fb = await db.get(Feedback, fid)
    if fb is None:
        raise FeedbackError("这份反馈不在了", 404)
    return fb


async def set_status(db: AsyncSession, fid: str, status: str) -> Feedback:
    if status not in STATUSES:
        raise FeedbackError("状态只能是 open 或 resolved")
    fb = await get(db, fid)
    fb.status = status
    fb.resolved_at = datetime.now(timezone.utc) if status == "resolved" else None
    await db.commit()
    await db.refresh(fb)
    return fb


async def delete(db: AsyncSession, fid: str) -> None:
    """删报告；对应回复还在就把它的评价标记也清掉（两边一致）。"""
    fb = await get(db, fid)
    if fb.message_id:
        msg = await db.get(Message, fb.message_id)
        if msg is not None:
            msg.feedback = None
    await db.delete(fb)
    await db.commit()


async def listing(db: AsyncSession, status: str | None = None) -> dict:
    """列表（新的在前）+ 未解决的条数（“我的”入口上的数字）。"""
    rows = (await db.execute(select(Feedback).order_by(Feedback.created_at.desc()))).scalars().all()
    open_n = sum(1 for f in rows if f.status == "open" and f.kind != "good")
    if status in STATUSES:
        rows = [f for f in rows if f.status == status]
    return {"items": [summary(f) for f in rows], "open": open_n}


def excerpt(fb: Feedback) -> str:
    snap = fb.snapshot or {}
    base = fb.note or snap.get("question") or snap.get("answer") or ""
    return _clip(" ".join(base.split()), EXCERPT_MAX)


def summary(fb: Feedback) -> dict:
    return {
        "id": fb.id, "kind": fb.kind, "kind_label": KINDS.get(fb.kind, fb.kind), "excerpt": excerpt(fb),
        "status": fb.status, "message_id": fb.message_id, "conversation_id": fb.conversation_id,
        "project_id": (fb.snapshot or {}).get("project_id"),
        "created_at": iso(fb.created_at) if fb.created_at else None,
        "resolved_at": iso(fb.resolved_at) if fb.resolved_at else None,
    }


def detail(fb: Feedback) -> dict:
    return {**summary(fb), "note": fb.note or "", "snapshot": fb.snapshot or {}, "markdown": markdown(fb)}


def _local(v: datetime) -> str:
    """报告里的时间按服务器时区写成人看的（“2026-10-14 09:47”），接口字段仍是 ISO。"""
    v = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return v.astimezone(clock.zone(None)).strftime("%Y-%m-%d %H:%M")


_STATE = {"done": "✓", "error": "✗", "denied": "没批准", "stopped": "被停下", "running": "进行中"}


def markdown(fb: Feedback) -> str:
    """“复制报告”的文字：贴给谁都看得懂、能照着复现。"""
    snap = fb.snapshot or {}
    out = [f"# 反馈：{KINDS.get(fb.kind, fb.kind)}", ""]
    if fb.created_at:
        out.append(f"- 时间：{_local(fb.created_at)}")
    if snap.get("conversation_title"):
        out.append(f"- 对话：{snap['conversation_title']}")
    model = snap.get("model") or "默认"
    if snap.get("routed_model"):
        model += f"（自动路由到 {snap['routed_model']}）"
    if snap:
        out.append(f"- 模型：{model} · 思考：{snap.get('reasoning') or '默认'} · 模式：{snap.get('mode') or 'default'}")
        if snap.get("status") and snap["status"] != "done":
            out.append(f"- 回复结束方式：{snap['status']}")
    out.append(f"- 状态：{'已解决' if fb.status == 'resolved' else '未解决'}")
    if fb.note:
        out += ["", "## 补充说明", "", fb.note]
    if snap.get("question"):
        out += ["", "## 提问", "", snap["question"]]
    if snap.get("answer"):
        out += ["", "## 回复", "", snap["answer"]]
    if snap.get("steps"):
        out += ["", "## 步骤", ""]
        for i, s in enumerate(snap["steps"], 1):
            line = f"{i}. {s.get('title', '')}"
            if s.get("detail"):
                line += f" `{s['detail']}`"
            line += f" — {_STATE.get(s.get('state', ''), s.get('state', ''))}"
            if s.get("ms") is not None:
                line += f" · {s['ms'] / 1000:.1f}s"
            if s.get("note"):
                line += f"（{s['note']}）"
            out.append(line)
    if snap.get("trace"):
        out += ["", "## 工具轨迹", "", "````", snap["trace"], "````"]  # 四个反引号：轨迹里自带的 ``` 不会把代码块提前关掉
    return "\n".join(out).strip() + "\n"
