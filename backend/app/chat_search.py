"""在过去的对话里找字：唯一的规则（v2.09 大脑 (at)，对标 Hark“记得以前聊过什么”）。

两个出口共用这一处：
- 历史面板的搜索框（GET /api/conversations?q=，routes/conversations.py）——按主聊天 / 某个项目分范围；
- 模型的 search_history 工具（agent/builtin/history.py）——默认搜全部，可按时间窗口，能翻开某段对话读原文。

规则：
- 查询拆词（terms）：空格分开的每个词都要出现（AND）；引号（"…" / “…” / 「…」）里的当一个整词；大小写不敏感；
  最多 TERMS_MAX 个词，去重；% 和 _ 是字面量。
- 一段对话算命中 = 每个词都出现在标题或这段对话的某条消息里（不要求同一条）；有时间窗口时只看窗口内的消息，
  且这段对话在窗口内至少有一条消息。
- 每段对话挑一条“最佳命中消息”：含的词最多，再按最新；标题已含全部词时不给摘录（打开就是）。
- 摘录（snippet_of）：最早出现的那个词前后各 width 字，压成一行，两头截断处加“…”。
- 排序：调用方给的 order（面板 = 置顶 + 最近更新；工具 = 命中词数 + 最近命中）。
- 读原文（read）：某段对话、某条消息前后几条（没给消息 = 最后几条），每条最多 READ_CHARS 字（中间截），总共 READ_TOTAL 字，
  告诉模型更早 / 更晚的从哪条接着看。
消息纯文本来自 Message.search_text（models.py 监听器维护，JSON 里的中文可能被转义，直接 LIKE 不可靠）。"""
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import Conversation, Message, Project

TERMS_MAX = 6
QUERY_MAX = 200
SNIPPET = 36          # 面板摘录：命中词前后各多少字
TOOL_SNIPPET = 80     # 工具摘录稍长：模型要靠它判断是不是那段
SCAN_MAX = 2000       # 挑最佳命中时最多扫多少条消息（单用户足够；超出的按最新优先）
TOOL_LIMIT = 8        # 工具一次最多列几段对话
READ_BEFORE, READ_AFTER = 3, 6
READ_LAST = 10
READ_CHARS = 1200
READ_TOTAL = 8000

ALL = "*"             # scope：搜全部（主聊天 + 所有项目）
_QUOTE = re.compile(r'"([^"]+)"|“([^”]+)”|「([^」]+)」')


class SearchError(ValueError):
    """查询或时间写法不对：中文原因，直接给模型 / 客户端看。"""


def terms(query: str) -> list[str]:
    q = (query or "").strip()[:QUERY_MAX]
    out: list[str] = []
    for m in _QUOTE.finditer(q):
        out.append(next(g for g in m.groups() if g).strip())
    rest = _QUOTE.sub(" ", q)
    out.extend(rest.split())
    seen, uniq = set(), []
    for t in out:
        k = t.lower()
        if t and k not in seen:
            seen.add(k)
            uniq.append(t)
    return uniq[:TERMS_MAX]


def _like(t: str) -> str:
    return "%" + t.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _has(col, t: str):
    return col.ilike(_like(t), escape="\\")


def snippet_of(text: str, words: list[str] | str, width: int = SNIPPET) -> str:
    """最早出现的那个词前后一小段，压成一行；都找不到就取开头。"""
    words = [words] if isinstance(words, str) else words
    flat = " ".join((text or "").split())
    low = flat.lower()
    found = [(i, w) for w in words if (i := low.find(w.lower())) >= 0]
    if not found:
        return flat[: width * 2] + ("…" if len(flat) > width * 2 else "")
    i, w = min(found)
    start, end = max(0, i - width), min(len(flat), i + len(w) + width)
    return ("…" if start else "") + flat[start:end] + ("…" if end < len(flat) else "")


def count_in(text: str, words: list[str]) -> int:
    low = (text or "").lower()
    return sum(1 for w in words if w.lower() in low)


# ---- 时间窗口 ----
def _zone() -> ZoneInfo:
    try:
        return ZoneInfo(settings.timezone)
    except Exception:  # noqa: BLE001 — 配错时区退回 UTC，不让搜索整个挂掉
        return ZoneInfo("UTC")


def parse_when(value: str | None, end: bool = False) -> datetime | None:
    """YYYY-MM-DD（用户时区的那一天；end=True 时取那天结束）或 ISO 时刻（不带时区 = 用户时区）→ UTC。空 → None。"""
    v = (value or "").strip()
    if not v:
        return None
    try:
        if len(v) == 10:
            d = datetime.fromisoformat(v).date()
            local = datetime.combine(d + timedelta(days=1) if end else d, time(), tzinfo=_zone())
            return local.astimezone(timezone.utc)
        dt = datetime.fromisoformat(v.replace("Z", "+00:00").replace(" ", "T", 1))
    except ValueError:
        raise SearchError(f"时间“{v}”认不出：写 YYYY-MM-DD 或 2026-10-12T14:00") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_zone())
    return dt.astimezone(timezone.utc)


def window(after: str | None, before: str | None) -> tuple[datetime | None, datetime | None]:
    a, b = parse_when(after), parse_when(before, end=True)
    if a and b and a >= b:
        raise SearchError("开始时间要早于结束时间")
    return a, b


def _naive(dt: datetime) -> datetime:
    """SQLite 存的是无时区 UTC；比较前统一成无时区 UTC（Postgres 带时区列也接受）。"""
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _in_window(after: datetime | None, before: datetime | None) -> list:
    out = []
    if after:
        out.append(Message.created_at >= _naive(after))
    if before:
        out.append(Message.created_at < _naive(before))
    return out


# ---- 搜索 ----
@dataclass
class Hit:
    conversation: Conversation
    message_id: str | None = None
    snippet: str | None = None
    role: str | None = None
    at: datetime | None = None
    hits: int = 0                 # 这段对话里含任一词的消息条数（扫描上限内）
    matched: int = 0              # 最佳命中消息含几个词
    title_hit: bool = False       # 标题已含全部词


async def search(db: AsyncSession, query: str, *, scope: str | None = ALL, after: datetime | None = None,
                 before: datetime | None = None, limit: int = 50, order: str = "recent",
                 width: int = SNIPPET, skip: set[str] | None = None) -> list[Hit]:
    """scope：ALL = 全部；None = 主聊天；项目 id = 该项目。order：recent = 置顶 + 最近更新（面板）；best = 命中词数 + 最近命中（工具）。
    skip = 不算命中的消息 id（工具跳过用户这一轮刚说的那句——它当然含这些词）。"""
    words = terms(query)
    if not words:
        return []
    win = _in_window(after, before)
    only = [*win, Message.id.not_in(list(skip))] if skip else win
    conds = []
    for t in words:
        in_msg = select(Message.conversation_id).where(_has(Message.search_text, t), *only)
        conds.append(or_(_has(Conversation.title, t), Conversation.id.in_(in_msg)))
    stmt = select(Conversation).where(and_(*conds))
    if win:
        stmt = stmt.where(Conversation.id.in_(select(Message.conversation_id).where(*win)))
    if scope != ALL:
        stmt = stmt.where(Conversation.project_id == scope if scope else Conversation.project_id.is_(None))
    # 先多取一些候选（best 排序要看命中情况），再在内存里排
    pool = limit if order == "recent" else max(limit * 4, 40)
    convs = list((await db.scalars(
        stmt.order_by(Conversation.pinned.desc(), Conversation.updated_at.desc()).limit(pool))).all())
    hits = {c.id: Hit(c, title_hit=count_in(c.title, words) == len(words)) for c in convs}
    if hits:
        any_word = or_(*(_has(Message.search_text, t) for t in words))
        rows = await db.execute(
            select(Message.conversation_id, Message.id, Message.role, Message.created_at, Message.search_text)
            .where(Message.conversation_id.in_(list(hits)), any_word, *only)
            .order_by(Message.created_at.desc(), Message.id.desc()).limit(SCAN_MAX))
        for cid, mid, role, at, text in rows.all():
            h = hits[cid]
            h.hits += 1
            n = count_in(text, words)
            if n > h.matched:  # 最新优先：同样多的词保留先遇到的（更新的）那条
                h.matched, h.message_id, h.role, h.at = n, mid, role, at
                h.snippet = snippet_of(text, words, width)
    out = [hits[c.id] for c in convs]
    if order == "best":
        def key(h: Hit):
            have = len(words) if h.title_hit else h.matched
            when = h.at or h.conversation.updated_at or datetime.min
            return (-have, -(when.replace(tzinfo=None) - datetime(1970, 1, 1)).total_seconds())
        out.sort(key=key)
    return out[:limit]


async def asking(db: AsyncSession, cid: str | None) -> set[str]:
    """当前对话里用户最新的那条消息（这一轮的问题）：工具搜索时跳过它。"""
    if not cid:
        return set()
    mid = await db.scalar(select(Message.id).where(Message.conversation_id == cid, Message.role == "user")
                          .order_by(Message.created_at.desc(), Message.id.desc()).limit(1))
    return {mid} if mid else set()


# ---- 给模型看 ----
def local_text(dt: datetime | None) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_zone()).strftime("%Y-%m-%d %H:%M")


def _who(role: str | None) -> str:
    return "用户" if role == "user" else "助手"


async def project_names(db: AsyncSession, ids: set[str]) -> dict[str, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict((await db.execute(select(Project.id, Project.name).where(Project.id.in_(ids)))).all())


def for_model(query: str, found: list[Hit], names: dict[str, str], current: str | None,
              total_more: bool) -> str:
    words = terms(query)
    if not found:
        return (f"过去的对话里没找到同时含 {'、'.join(words)} 的。可以少用几个词、换个说法，或去掉时间限制再搜；"
                "别凭印象编造以前说过的话。")
    lines = [f"找到 {len(found)} 段对话{'（只列最相关的这些）' if total_more else ''}，词：{'、'.join(words)}"]
    for i, h in enumerate(found, 1):
        c = h.conversation
        where = f" · 项目「{names[c.project_id]}」" if c.project_id and c.project_id in names else ""
        here = "（就是这段对话，较早的部分可能已不在上文里）" if c.id == current else ""
        when = local_text(h.at or c.updated_at)
        lines.append(f"{i}. 「{c.title}」{where} · {when}{here} · 对话 {c.id}")
        if h.snippet:
            lines.append(f"   {_who(h.role)}：{h.snippet}" + (f"（共 {h.hits} 条消息提到）" if h.hits > 1 else ""))
            lines.append(f"   看原文：search_history conversation=\"{c.id}\" message=\"{h.message_id}\"")
        else:
            lines.append(f"   标题命中；看原文：search_history conversation=\"{c.id}\"")
    lines.append("引用以前的话以原文为准；摘录不够判断时先看原文。")
    return "\n".join(lines)


def _cut(text: str, n: int = READ_CHARS) -> str:
    t = (text or "").strip()
    if len(t) <= n:
        return t
    half = n // 2
    return f"{t[:half]}…（中间省略 {len(t) - n} 字）…{t[-half:]}"


async def read(db: AsyncSession, cid: str, message_id: str | None = None) -> str:
    c = await db.get(Conversation, cid)
    if not c:
        raise SearchError(f"没有这段对话：{cid}（编号从 search_history 的结果里拿）")
    rows = list((await db.execute(
        select(Message.id, Message.role, Message.created_at, Message.search_text)
        .where(Message.conversation_id == cid).order_by(Message.created_at, Message.id))).all())
    total = len(rows)
    if not total:
        return f"「{c.title}」还没有消息。"
    if message_id:
        idx = next((i for i, r in enumerate(rows) if r[0] == message_id), None)
        if idx is None:
            raise SearchError(f"这段对话里没有消息 {message_id}（可能被重答删掉了）；不带 message 看最后几条")
        lo, hi = max(0, idx - READ_BEFORE), min(total, idx + READ_AFTER + 1)
    else:
        idx, lo, hi = None, max(0, total - READ_LAST), total
    parts, used, cut_at = [], 0, hi
    for i in range(lo, hi):
        mid, role, at, text = rows[i]
        body = _cut(text)
        if used + len(body) > READ_TOTAL and parts:
            cut_at = i
            break
        used += len(body)
        mark = " ← 命中" if i == idx else ""
        parts.append(f"[{i + 1}] {_who(role)} · {local_text(at)}{mark}\n{body}")
    hi = cut_at
    names = await project_names(db, {c.project_id} if c.project_id else set())
    where = f" · 项目「{names[c.project_id]}」" if c.project_id in names else ""
    head = f"「{c.title}」{where} · 共 {total} 条消息，这里是第 {lo + 1}–{hi} 条"
    more = []
    if lo > 0:
        more.append(f"更早的：message=\"{rows[max(0, lo - READ_AFTER - 1)][0]}\"")
    if hi < total:
        more.append(f"更晚的：message=\"{rows[min(total - 1, hi + READ_BEFORE)][0]}\"")
    tail = ("\n还有 " + "；".join(more)) if more else ""
    return head + "\n\n" + "\n\n".join(parts) + tail

