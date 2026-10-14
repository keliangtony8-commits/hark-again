# Copyright 2025 Google LLC
# SPDX-License-Identifier: Apache-2.0
#
# Ported from google-gemini/gemini-cli/packages/core/src/services/sessionSummaryService.ts (Apache-2.0), modified:
# 中文标题提示词与清洗规则、标题来源（title_source）锁、按对话只在前几轮尝试、事件推给客户端。
"""对话标题（总结标题）——唯一规则在这里。列表、项目首屏、项目对话的标题药丸都读 conversations.title。

新对话先用第一句话的前 40 个字当占位（title_source = "first"）。第一轮回复落库后，后台叫一次便宜模型
（settings.summary_model，最低一档思考）把对话总结成一个名词短语标题，写回并推 conversation.title 事件。
v2.91 §N：标题是**名词短语、≤14 字（英文 ≤40 字母）、无标点、不口语**；话题会变，所以 auto 标题每多约
RETITLE_EVERY 条消息复查一次（conversations.title_at 记上次起标题时的消息数）：模型看当前标题 + 最近几条，
话题没变原样输出（只推进 title_at，不推事件），变了给新标题（写回 + 推事件）。
- 来源：first = 第一句话截取（可被自动标题替换）；auto = 已自动起过（每约 10 条复查）；user = 用户改过名（永不覆盖）；
  fixed = 程序给的名字（定时任务对话、旧数据），不碰。写回前在同一条 UPDATE 里再确认一次来源没变。
- first 只在前 TITLE_TRIES 个用户回合里试（第一次失败 / 超时，下一轮再试）。
- 选材照 Gemini：只取用户 / 助手的非空文字，超过 MAX_MESSAGES 条取前一半 + 后一半，每条截 MAX_MESSAGE_LENGTH 字加 “...”；
  复查只看最近 RECENT_MESSAGES 条。
- 清洗照 Gemini（换行/空白折叠、去首尾引号）+ 中文：去“标题：”前缀、口语开头（帮我 / 请 / 我想…）、全部标点，按 14 字 / 40 字母截。
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
TITLE_MAX = 14            # 中文标题最多几个字（§N：名词短语 ≤14 字）
TITLE_MAX_LATIN = 40      # 纯拉丁文字标题最多几个字母（按词截）
TITLE_TRIES = 3            # first：前几个用户回合里试
RETITLE_EVERY = 10         # auto：每多这么多条消息复查一次话题
RECENT_MESSAGES = 10       # 复查时给模型看最近几条

PROMPT = """把用户在这段对话里主要在做的事总结成一个名词短语，作为对话标题。
要求：不超过 14 个字（英文对话不超过 40 个字母）；用名词短语，不要完整句子；不要任何标点；书面、不口语（不要“帮我”“怎么”“一下”“吗”）；用用户自己的语言。
只输出标题本身，不要引号、不要“标题：”。

例子：
- App 深色模式适配
- 登录鉴权故障排查
- API 路由结构梳理
- 杭州周末两日行程
- Production memory leak

对话：
{conversation}

标题："""

RETITLE_PROMPT = """这段对话现在的标题是：{title}
下面是这段对话最近的内容。判断这个标题作为对话标题是否仍然概括得了整段对话现在的主题：
- 仍然合适：原样输出当前标题，一个字都不改；
- 话题已经变了：输出新的标题。新标题是名词短语，不超过 14 个字（英文不超过 40 个字母），不要任何标点，书面、不口语，用用户自己的语言。
只输出标题本身，不要引号、不要“标题：”、不要解释。

最近的内容：
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


_PREFIX = re.compile(r"^(?:对话)?(?:新)?(?:标题|题目|title)\s*[:：]\s*", re.I)
_QUOTES = "\"'“”‘’「」『』《》`"
_TAIL = "。．.！!？?；;，,、…~～ "
# 无标点（§N）：中英文标点一律去掉；词里的连字符、加号、点（Vue.js、C++、v2.91）不算标点，留着
_PUNCT = re.compile(r"[，。、；：！？…—～·“”‘’「」『』《》〈〉【】（）〔〕\[\]{}()!?;:,\"'`~|]")
_ORAL = re.compile(r"^(?:请问|请你|请|麻烦你?|帮我|帮忙|我想要?|我要|我需要|想要|如何|怎么样?|怎样)\s*")
_CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")


def _fit(s: str) -> str:
    """含中文：按“字”数截到 TITLE_MAX——汉字算 1 个字，拉丁字母 / 数字 / 空格算半个（“App 深色模式适配”= 8 字），
    截点落在英文词中间就退到词前；纯拉丁按 TITLE_MAX_LATIN 个字母在词边界截。"""
    if not _CJK.search(s):
        if len(s) <= TITLE_MAX_LATIN:
            return s
        cut = s[:TITLE_MAX_LATIN + 1].rsplit(" ", 1)[0]
        return (cut if cut else s[:TITLE_MAX_LATIN]).strip()
    width, end = 0.0, len(s)
    for i, ch in enumerate(s):
        width += 1 if ord(ch) > 0x2E7F else 0.5
        if width > TITLE_MAX:
            end = i
            break
    if end < len(s) and s[end].isascii() and s[end] != " " and end > 0 and s[end - 1].isascii() and s[end - 1] != " ":
        j = end
        while j > 0 and s[j - 1].isascii() and s[j - 1] != " ":
            j -= 1
        end = j if j > 0 else end
    return s[:end].strip()


def clean(raw: str | None) -> str | None:
    """模型输出 → 标题（名词短语、无标点、≤14 字）；没法用 → None。"""
    if not raw:
        return None
    s = re.sub(r"\s+", " ", raw.replace("\n", " ")).strip()  # Gemini：折叠换行与空白
    s = _PREFIX.sub("", s).strip()
    s = s.lstrip("-*• ").strip()  # 照着例子输出了列表符号
    for _ in range(2):  # Gemini 只去一层引号；中文模型常见“《…》”外再套引号
        s = s.strip(_QUOTES).strip()
    s = s.rstrip(_TAIL).strip()
    while (t := _ORAL.sub("", s).strip()) != s and t:  # “请问如何…”去两层
        s = t
    s = re.sub(r"\s+", " ", _PUNCT.sub(" ", s)).strip()
    s = re.sub(r"(?<=[\u3400-\u9fff]) (?=[\u3400-\u9fff])", "", s)  # 去标点留下的中文字间空格
    s = _fit(s.rstrip(_TAIL).strip())
    return s or None


async def generate(messages: list[tuple[str, str]], timeout: float = TIMEOUT_S, language: str = "",
                   current: str | None = None) -> str | None:
    """Gemini generateSummary：没材料 → 不调模型；任何失败 → None（优雅退化）。
    current：复查时的当前标题（只给最近 RECENT_MESSAGES 条，模型话题没变就原样输出它）。
    language：reply_language.generated_line（固定回复语言时“用英文写。”；跟随 → 空）。"""
    picked = select_messages(messages)
    if current is not None:
        picked = [m for m in messages if m[0] in ("user", "assistant") and m[1].strip()][-RECENT_MESSAGES:]
    if not picked:
        return None
    text = conversation_text(picked)
    prompt = (RETITLE_PROMPT.replace("{title}", current) if current is not None else PROMPT).replace("{conversation}", text)
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


def due(source: str, users: int, count: int, title_at: int | None) -> bool:
    """该不该叫模型：first 在前 TITLE_TRIES 个用户回合里；auto 在比上次起标题多了 RETITLE_EVERY 条消息之后。"""
    if source == FIRST:
        return 0 < users <= TITLE_TRIES
    if source == AUTO:
        return count - (title_at or 0) >= RETITLE_EVERY
    return False


async def maybe(db, cid: str) -> str | None:
    """这段对话该起 / 该复查标题就做、写回并返回新标题；不该 / 没起成 / 话题没变 → None。调用方在回复落库之后调。"""
    if not settings.auto_title:
        return None
    conv = await db.get(Conversation, cid)
    if conv is None or conv.title_source not in (FIRST, AUTO):
        return None
    source, current, title_at = conv.title_source, conv.title, conv.title_at
    msgs, users = await _material(db, cid)
    count = len(msgs)
    if not due(source, users, count, title_at) or not any(r == "assistant" and t.strip() for r, t in msgs):
        return None
    language = reply_language.generated_line(await reply_language.get(db))
    await db.commit()  # 读语句也要先结束事务，再去调模型（SQLite：别占着连接）
    title = await generate(msgs, language=language, current=current if source == AUTO else None)
    if not title:
        return None
    # 期间用户可能改了名：只在来源没变时写（同一条 UPDATE 里判断）；不动 updated_at（列表排序不因起名而变）
    same = source == AUTO and title == current
    values = {"title_at": count, "updated_at": Conversation.updated_at}
    if not same:
        values.update(title=title, title_source=AUTO)
    r = await db.execute(update(Conversation).where(Conversation.id == cid, Conversation.title_source == source).values(**values))
    await db.commit()
    return title if r.rowcount and not same else None


Emit = Callable[[dict], Awaitable[None]]
_pending: set[asyncio.Task] = set()


def schedule(cid: str | None, emit: Emit) -> asyncio.Task | None:
    """一轮结束后在后台起 / 复查标题（不挡同一对话排队的下一轮），换了才推 conversation.title。"""
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

