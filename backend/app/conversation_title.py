# Copyright 2025 Google LLC
# SPDX-License-Identifier: Apache-2.0
#
# Ported from google-gemini/gemini-cli/packages/core/src/services/sessionSummaryService.ts (Apache-2.0), modified:
# 中文标题提示词与清洗规则、标题来源（title_source）锁、按对话只在前几轮尝试、事件推给客户端。
"""对话自动起标题——唯一规则在这里。

新对话先用第一句话的前 40 个字当标题（title_source = "first"）。第一轮回复落库后，后台叫一次便宜模型
（settings.summary_model，最低一档思考）按“用户想做什么”起一个短标题，写回并推 conversation.title 事件。
- 来源：first = 第一句话截取（可被自动标题替换）；auto = 已自动起过；user = 用户改过名（永不覆盖）；
  fixed = 程序给的名字（定时任务对话、旧数据），不碰。只有 first 会被改，写回前在同一事务里再确认一次。
- 只在前 TITLE_TRIES 个用户回合里试（第一次失败 / 超时，下一轮再试；老对话不会被突然改名）。
- 选材照 Gemini：只取用户 / 助手的非空文字，超过 MAX_MESSAGES 条取前一半 + 后一半，每条截 MAX_MESSAGE_LENGTH 字加 “...”。
- 清洗照 Gemini（换行/空白折叠、去首尾引号）+ 中文：去“标题：”前缀、书名号/中文引号、句末标点，截 TITLE_MAX 字。
- 任何失败（超时 TIMEOUT_S、网关错、空回复）→ None，标题保持原样，不打扰用户。
settings.auto_title = False 关闭。"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Awaitable, Callable

from sqlalchemy import select, update

from . import llm, reply_language
from .blocks import blocks_to_text
from .config import settings
from .db import SessionLocal
from .models import Conversation, Message

log = logging.getLogger(__name__)

FIRST, AUTO, USER, FIXED = "first", "auto", "user", "fixed"
SOURCES = (FIRST, AUTO, USER, FIXED)
FIRST_MAX = 40            # 第一句话截取的长度（ws.py 建对话时用 first_title）
DEFAULT_MAX_MESSAGES = 20  # Gemini DEFAULT_MAX_MESSAGES
MAX_MESSAGE_LENGTH = 500   # Gemini MAX_MESSAGE_LENGTH
TIMEOUT_S = 8.0            # Gemini 5 s；我们的网关慢一些
TITLE_MAX = 30
TITLE_TRIES = 3            # 前几个用户回合里试

PROMPT = """用一句话概括用户在这段对话里主要想做的事，作为对话标题（不超过 20 个字，英文对话不超过 60 个字母）。
着眼于用户想完成什么，用用户自己的语言。只输出标题本身，不要引号、不要句号、不要“标题：”。

例子：
- 给 App 加深色模式
- 修登录流程的鉴权 bug
- 搞懂 API 路由怎么走
- 周末去杭州的两天行程
- Debug memory leak in production

对话：
{conversation}

标题："""


def first_title(text: str) -> str:
    """建对话时的临时标题：第一句话折叠空白后的前 FIRST_MAX 个字。"""
    return re.sub(r"\s+", " ", text or "").strip()[:FIRST_MAX] or "新对话"


def select_messages(messages: list[tuple[str, str]], max_messages: int = DEFAULT_MAX_MESSAGES) -> list[tuple[str, str]]:
    """(role, text) → 只留 user/assistant 的非空文字；超过 max 条取前 ceil(max/2) + 后 floor(max/2)（Gemini 滑动窗口）。"""
    kept = [(r, t) for r, t in messages if r in ("user", "assistant") and t.strip()]
    if len(kept) <= max_messages:
        return kept
    first, last = -(-max_messages // 2), max_messages // 2
    return kept[:first] + (kept[-last:] if last else [])


def conversation_text(messages: list[tuple[str, str]]) -> str:
    out = []
    for role, text in messages:
        t = text if len(text) <= MAX_MESSAGE_LENGTH else text[:MAX_MESSAGE_LENGTH] + "..."
        out.append(f"{'用户' if role == 'user' else '助手'}: {t}")
    return "\n\n".join(out)


_PREFIX = re.compile(r"^(?:对话)?(?:标题|题目|title)\s*[:：]\s*", re.I)
_QUOTES = "\"'“”‘’「」『』《》`"
_TAIL = "。．.！!？?；;，,、…~～ "


def clean(raw: str | None) -> str | None:
    """模型输出 → 标题；没法用 → None。"""
    if not raw:
        return None
    s = re.sub(r"\s+", " ", raw.replace("\n", " ")).strip()  # Gemini：折叠换行与空白
    s = _PREFIX.sub("", s).strip()
    s = s.lstrip("-*• ").strip()  # 照着例子输出了列表符号
    for _ in range(2):  # Gemini 只去一层引号；中文模型常见“《…》”外再套引号
        s = s.strip(_QUOTES).strip()
    s = s.rstrip(_TAIL).strip()
    if len(s) > TITLE_MAX:
        s = s[:TITLE_MAX].rstrip(_TAIL + _QUOTES)
    return s or None


async def generate(messages: list[tuple[str, str]], timeout: float = TIMEOUT_S, language: str = "") -> str | None:
    """Gemini generateSummary：没材料 → 不调模型；任何失败 → None（优雅退化）。
    language：reply_language.generated_line（固定回复语言时“用英文写。”；跟随 → 空）。"""
    picked = select_messages(messages)
    if not picked:
        return None
    prompt = PROMPT.replace("{conversation}", conversation_text(picked))
    if language:
        prompt = prompt.replace("\n\n标题：", f"\n\n{language}\n标题：")
    try:
        raw = await asyncio.wait_for(
            llm.complete([{"role": "user", "content": prompt}], model=settings.summary_model, kind="title", max_tokens=60),
            timeout)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # 超时 / 网关错：标题保持原样
        log.debug("auto title failed: %s", e)
        return None
    return clean(raw)


async def _material(db, cid: str) -> tuple[list[tuple[str, str]], int]:
    rows = (await db.execute(select(Message.role, Message.blocks).where(Message.conversation_id == cid)
                             .order_by(Message.created_at))).all()
    msgs = [(r, blocks_to_text(b or [])) for r, b in rows]
    return msgs, sum(1 for r, _ in msgs if r == "user")


async def maybe(db, cid: str) -> str | None:
    """这段对话该起标题就起、写回并返回新标题；不该 / 没起成 → None。调用方在回复落库之后调。"""
    if not settings.auto_title:
        return None
    conv = await db.get(Conversation, cid)
    if conv is None or conv.title_source != FIRST:
        return None
    msgs, users = await _material(db, cid)
    if users == 0 or users > TITLE_TRIES or not any(r == "assistant" and t.strip() for r, t in msgs):
        return None
    language = reply_language.generated_line(await reply_language.get(db))
    await db.commit()  # 读语句也要先结束事务，再去调模型（SQLite：别占着连接）
    title = await generate(msgs, language=language)
    if not title:
        return None
    # 期间用户可能改了名：只在仍是 first 时写（同一条 UPDATE 里判断）；不动 updated_at（列表排序不因起名而变）
    r = await db.execute(update(Conversation).where(Conversation.id == cid, Conversation.title_source == FIRST)
                         .values(title=title, title_source=AUTO, updated_at=Conversation.updated_at))
    await db.commit()
    return title if r.rowcount else None


Emit = Callable[[dict], Awaitable[None]]
_pending: set[asyncio.Task] = set()


def schedule(cid: str | None, emit: Emit) -> asyncio.Task | None:
    """一轮结束后在后台起标题（不挡同一对话排队的下一轮），起好了推 conversation.title。"""
    if not cid or not settings.auto_title:
        return None

    async def run() -> None:
        try:
            async with SessionLocal() as db:
                title = await maybe(db, cid)
            if title:
                await emit({"type": "conversation.title", "conversation_id": cid, "title": title})
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("auto title")

    task = asyncio.create_task(run())
    _pending.add(task)
    task.add_done_callback(_pending.discard)
    return task


async def drain(timeout: float = 5.0) -> None:
    """关机 / 测试：等后台起标题收尾。"""
    if _pending:
        await asyncio.wait(set(_pending), timeout=timeout)

