"""运行中来的用户消息怎么办（v2.90 home-redesign §C 定稿）：唯一入口，一个账本。

原则：按“一件事”回复，不按“一条消息”；分不清就合并（宁少勿多）。
- 空闲时不经过这里：直接开一轮（零额外成本）。
- 正在跑时（routes/ws._intake）：消息先落库、推 turn.steered 认领气泡，然后进本模块的缓冲；静默 QUIET_S 秒后整批分流：
  - 补充 / 拆开说 / 改要求 / 取消 → steering 收件箱，并进正在跑的这一轮，那一轮的回复一起结清；
  - 纯附和（“好的”“嗯”“就这种”）→ 不进模型、不回，挂在这一轮上，回复时一起结清（RIDE）；
  - 问进度（“怎么样了”）→ 不调模型，从 live_turns 这一轮的步骤一句话答（progress_text）；
  - 无关的新问题、带引用回复的 → 并行一路（live_turns.side，同一对话最多 1 主 + 1 并行），整条回复推 message.added。
  判断：先确定性规则（rule），剩下拿不准的整批只问一次 lite 模型（judge，≈200 token）；失败 / 超时 → 补充。
- 账本：messages.answered_by = 结清它的回复 id（settle）。主路回复结清提问 + 读走的补充 + 附和；没读走的另起一轮一起结清；
  服务器重启时 turn_journal 的 interrupted 回复结清那一轮还欠着的（不自动重跑 = 不重发）。
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from . import live_turns, llm, steering
from .blocks import text_to_blocks
from .config import settings
from .db import SessionLocal
from .models import Message

log = logging.getLogger(__name__)

QUIET_S = 1.5        # 连发先等这么久没有新消息再判断（一口气发的几条天然合在一起）
JUDGE_TIMEOUT_S = 10.0
JUDGE_CHARS = 300    # 给 lite 模型看的“正在做的事”和每条新消息最多多少字
JUDGE_TOKENS = 300   # 输出上限：推理型便宜模型先想再答，8 个 token 会被思考吃光、答空（E2E 实测 step-3.7-flash）

STEER, RIDE, PROGRESS, NEW = "steer", "ride", "progress", "new"

_ACK = re.compile(r"^(?:好的?|好滴|好嘞|嗯+|恩+|哦+|噢+|ok|okay|k|行|行吧|可以|收到|明白|懂了|知道了|了解|谢谢|谢了|thx|thanks|"
                  r"对|对的|是的|没错|没问题|就这种|就这样|就这个|就它|辛苦了?|棒|不错|👍|👌|🙏)[\s!！。.~～,，]*$", re.I)
_PROGRESS = re.compile(r"^(?:那个|还有|那|所以)?\S{0,8}?(?:现在|目前)?(?:怎么样了|咋样了|弄得怎么样|做得怎么样|好了没|好没|好了吗|做完了吗|完成了吗|进度|到哪了|做到哪|"
                       r"还要多久|还在吗|在吗|还在做吗|在干嘛|在做什么|在忙什么|是不是(?:又)?(?:停|卡)|卡住了|停了吗|停下来了|怎么没反应|有结果了吗|"
                       r"status|how'?s it going)", re.I)
_SUPPLEMENT = re.compile(r"^(?:对了|另外记得|记得|别忘了|要|不要|别|不用|改成|换成|改为|用|只要|最好|顺便把|再加|加上|去掉|"
                         r"算了|等等|等一下|停|不对|错了|我是说|我的意思是|也就是|就是说|比如|例如|注意|必须|一定要)")


@dataclass
class Arrival:
    message_id: str
    text: str
    content: str | list
    at: datetime
    reply_to: str | None = None
    files: bool = False  # 带了附件 / 工作区文件：不会是“附和”


@dataclass
class _Buffer:
    items: list[Arrival] = field(default_factory=list)
    timer: asyncio.TimerHandle | None = None
    task: asyncio.Task | None = None


_buf: dict[str, _Buffer] = {}
_riders: dict[str, list[str]] = {}  # 挂在正在跑的这一轮上、等它的回复一起结清的消息（附和）

# 由 routes/ws 注册（避免循环导入）：并行一路 / 收尾后另起一轮回答这一批
SideFn = Callable[[str, list[str]], None]
_side: SideFn | None = None
_pending: SideFn | None = None


def set_handlers(side: SideFn, pending: SideFn) -> None:
    global _side, _pending
    _side, _pending = side, pending


def rule(text: str, files: bool = False) -> str | None:
    """确定性规则：这句话是什么（None = 拿不准，交给 judge）。带附件的只可能是补充或新问题。"""
    t = (text or "").strip()
    if files:
        return STEER if not t or _ACK.match(t) or _SUPPLEMENT.match(t) or len(t) <= 12 else None
    if not t:
        return RIDE
    if len(t) <= 12 and _ACK.match(t):
        return RIDE
    if len(t) <= 24 and _PROGRESS.match(t):
        return PROGRESS
    if _SUPPLEMENT.match(t):
        return STEER
    return None


JUDGE_PROMPT = """助手正在做一件事时，用户又发来了消息。判断这些新消息是对正在做的事的补充/修改（SUPPLEMENT），还是一个无关的新问题（NEW）。
拿不准就答 SUPPLEMENT。只输出一个词。

正在做的事（用户原话）：{task}

新消息：
{messages}"""


async def judge(task: str, texts: list[str]) -> str:
    """lite 模型判一次：STEER（补充）或 NEW。任何失败 → STEER（宁少勿多）。"""
    prompt = JUDGE_PROMPT.format(task=task[:JUDGE_CHARS] or "（看不到）",
                                 messages="\n".join(f"- {t[:JUDGE_CHARS]}" for t in texts))
    try:
        raw = await asyncio.wait_for(
            llm.complete([{"role": "user", "content": prompt}], model=settings.router_model or settings.summary_model,
                         kind="intake", max_tokens=JUDGE_TOKENS), JUDGE_TIMEOUT_S)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001 — 判不了就合并
        log.debug("intake judge failed: %s", e)
        return STEER
    return NEW if "NEW" in (raw or "").upper() and "SUPPLEMENT" not in (raw or "").upper() else STEER


def group(items: list[Arrival], unclear: str) -> list[tuple[str, list[Arrival]]]:
    """一批消息 → 几件事。unclear = 拿不准的那几条整体判成什么（judge 的结果）。
    同类的合成一件：补充逐条进收件箱（模型按原样看到每条），附和挂上，进度一句答掉，新问题合成一件交给并行路。"""
    out: dict[str, list[Arrival]] = {}
    for a in items:
        kind = NEW if a.reply_to else (rule(a.text, a.files) or unclear)
        out.setdefault(kind, []).append(a)
    return [(k, out[k]) for k in (STEER, NEW, PROGRESS, RIDE) if k in out]


def arrive(cid: str, item: Arrival) -> None:
    """ws 收下一条运行中的消息（已落库、已认领）：放进缓冲，静默 QUIET_S 秒后整批分流。"""
    b = _buf.setdefault(cid, _Buffer())
    b.items.append(item)
    if b.timer is not None:
        b.timer.cancel()
    if QUIET_S <= 0:
        b.timer = None
        _start(cid)
    else:
        b.timer = asyncio.get_running_loop().call_later(QUIET_S, _start, cid)


def _start(cid: str) -> None:
    b = _buf.get(cid)
    if b is None or not b.items:
        return
    batch, b.items, b.timer = b.items, [], None
    b.task = asyncio.get_running_loop().create_task(_flush(cid, batch))


async def settle_all(cid: str | None = None) -> None:
    """测试用：等缓冲里的都分流完。"""
    for k, b in list(_buf.items()):
        if cid and k != cid:
            continue
        if b.timer is not None:
            b.timer.cancel()
            _start(k)
        if b.task is not None:
            await asyncio.wait({b.task}, timeout=10)


async def _flush(cid: str, batch: list[Arrival]) -> None:
    try:
        unclear = STEER
        need = [a.text for a in batch if not a.reply_to and rule(a.text, a.files) is None]
        if need:
            unclear = await judge(await _task_text(cid), need)
        for kind, items in group(batch, unclear):
            await _route(cid, kind, items)
    except Exception:  # noqa: BLE001 — 分流出错也不能把消息丢了：交给收尾后另起一轮
        log.exception("intake flush failed")
        if _pending is not None:
            _pending(cid, [a.message_id for a in batch])


async def _route(cid: str, kind: str, items: list[Arrival]) -> None:
    ids = [a.message_id for a in items]
    active = steering.active(cid)
    if kind == STEER:
        left = [a for a in items if steering.offer(cid, a.text, a.message_id, a.content, a.at) is None]
        if left and _pending is not None:  # 这一轮已收尾 / 插满：紧接着另起一轮把它们一起回掉
            _pending(cid, [a.message_id for a in left])
    elif kind == RIDE:
        if active:
            _riders.setdefault(cid, []).extend(ids)
        else:  # 这一轮已经说完了：附和不用回，算被上一条回复结清
            async with SessionLocal() as db:
                last = await db.scalar(select(Message.id).where(Message.conversation_id == cid, Message.role == "assistant")
                                       .order_by(Message.created_at.desc()).limit(1))
                if last:
                    await settle(db, ids, last)
                    await db.commit()
    elif kind == PROGRESS:
        if live_turns.running(cid) is None:  # 已经做完了：让模型看着历史答
            if _pending is not None:
                _pending(cid, ids)
            return
        await reply(cid, progress_text(live_turns.running(cid)), ids)
    elif kind == NEW and _side is not None:
        _side(cid, ids)


def riders(cid: str) -> list[str]:
    """这一轮收尾：取走挂在它上面的附和（回复一起结清）。"""
    return _riders.pop(cid, [])


def progress_text(turn) -> str:
    """问进度的一句话（不调模型）：正在做的那一步 + 用了多久 + 做了几步。"""
    if turn is None:
        return "刚做完，结果就在上面。"
    import time
    secs = int(time.monotonic() - turn.started)
    took = f"{secs // 60} 分 {secs % 60} 秒" if secs >= 60 else f"{secs} 秒"
    steps = [s for s in turn.steps if isinstance(s, dict)]
    run = next((s for s in reversed(steps) if s.get("state") == "running"), None)
    if run is not None:
        what = (run.get("title") or "处理").strip()
        detail = (run.get("detail") or "").strip()
        now = f"{what}（{detail[:40]}）" if detail else what
        return f"还在做，现在在{now}。已经 {took}、做了 {len(steps)} 步，好了马上告诉你。"
    if steps:
        return f"快好了，正在整理结果。已经 {took}、做了 {len(steps)} 步。"
    return f"正在想，已经 {took}，马上回你。"


async def reply(cid: str, text: str, ids: list[str]) -> Message:
    """不调模型的一条回复（问进度）：落库、结清、推 message.added。"""
    from . import reply_quote
    async with SessionLocal() as db:
        m = Message(conversation_id=cid, role="assistant", blocks=text_to_blocks(text), status="done", reply_to=ids[0])
        db.add(m)
        await db.flush()
        await settle(db, ids, m.id)
        await db.commit()
        wire = await reply_quote.wire_one(db, m)
    live_turns.publish(cid, {"type": "message.added", "conversation_id": cid, "message": wire})
    return m


async def settle(db: AsyncSession, ids: list[str], reply_id: str) -> None:
    """账本：这些用户消息由 reply_id 结清（已结清的不改）。调用方提交。"""
    ids = [i for i in dict.fromkeys(ids) if i]
    if ids and reply_id:
        await db.execute(update(Message).where(Message.id.in_(ids), Message.role == "user", Message.answered_by.is_(None))
                         .values(answered_by=reply_id))


async def owed(db: AsyncSession, cid: str) -> list[str]:
    """还欠着回复的用户消息 id（按时间）：重启恢复与测试用。"""
    return list((await db.scalars(select(Message.id).where(Message.conversation_id == cid, Message.role == "user",
                                                          Message.answered_by.is_(None)).order_by(Message.created_at))).all())


async def _task_text(cid: str) -> str:
    """正在做的事 = 这个对话最后一条没被结清的、不是运行中插进来的用户消息的文字。"""
    from .reply_quote import text_of
    async with SessionLocal() as db:
        m = await db.scalar(select(Message).where(Message.conversation_id == cid, Message.role == "user",
                                                  Message.status != steering.STEER)
                            .order_by(Message.created_at.desc()).limit(1))
        return text_of(m.blocks) if m is not None else ""


SIDE_BRIEF = ("[并行处理] 你在忙另一件事的同时，用户另外问了最后这条消息。只回答最后这条（以及紧挨着它、同一时间发来的几条）；"
              "前面那件还没回复的事另有一路在处理，不要去做它、也不要提它。这一路看不到审批和表单：需要用户批准或填写的操作不要做，"
              "如实说等手上的事做完再处理。")
