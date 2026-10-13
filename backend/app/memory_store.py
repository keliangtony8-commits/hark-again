"""记忆检索：决定每轮对话带哪些记忆进上下文（token 成本的大头之一）。

策略（按成本从低到高）：
1. 记忆不多（≤ ALWAYS_ALL 条）→ 全带，不调向量接口
2. 记忆多了 → 用户这句话做向量检索取 top-k，profile 类（身份、禁忌）始终带上
3. 向量接口不可用 → 按字面重合（中文两字词 + 英文单词）排，再按最近更新补满，功能不中断
没带进上下文的记忆模型用 search_memory 查（search()，v2.11）：字面 + 向量混合，同一套打分。

向量直接存在记忆行的 JSON 列里、内存里算余弦：单用户几千条以内毫秒级，
SQLite/Postgres 通用；真到几万条再换 pgvector 索引，接口不变。
编辑过的记忆向量会被清空，这里统一懒补齐。"""
import logging
import math
import re
from dataclasses import dataclass
from datetime import timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import chat_search, llm
from .config import settings
from .models import Memory

ALWAYS_ALL = 30
TOP_K = 12
DUPLICATE = 0.92
log = logging.getLogger("memory")


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


async def _backfill(db: AsyncSession, mems: list[Memory]) -> None:
    missing = [m for m in mems if not m.embedding]
    if not missing:
        return
    vecs = await llm.embed([m.content for m in missing])
    for m, v in zip(missing, vecs):
        m.embedding = v
    await db.commit()


_WORD = re.compile(r"[A-Za-z0-9]{2,}|[\u4e00-\u9fff]+")


def grams(text: str) -> set[str]:
    """字面重合用的“词”：英文/数字按单词（小写），中文连续段切成两字一组（单字段保留单字）。"""
    out: set[str] = set()
    for m in _WORD.finditer(text or ""):
        w = m.group().lower()
        if w.isascii():
            out.add(w)
        elif len(w) == 1:
            out.add(w)
        else:
            out.update(w[i:i + 2] for i in range(len(w) - 1))
    return out


def overlap(query: str, content: str) -> float:
    """query 的“词”有多少出现在 content 里（0~1）。"""
    q = grams(query)
    return len(q & grams(content)) / len(q) if q else 0.0


async def _vectors(db: AsyncSession, mems: list[Memory], query: str) -> list[float] | None:
    """补齐记忆向量并算 query 向量；向量接口不可用 → None（调用方退回字面）。"""
    try:
        await _backfill(db, mems)
        return (await llm.embed([query]))[0]
    except Exception:
        log.warning("embedding unavailable, falling back to keyword overlap")
        return None


async def count(db: AsyncSession) -> int:
    return len((await db.scalars(select(Memory.id))).all())


async def relevant(db: AsyncSession, query: str) -> list[Memory]:
    mems = list((await db.scalars(select(Memory).order_by(Memory.updated_at.desc()))).all())
    if len(mems) <= ALWAYS_ALL or not query.strip():
        return mems[:ALWAYS_ALL]
    pinned = [m for m in mems if m.category == "profile"]
    rest = [m for m in mems if m.category != "profile"]
    q = await _vectors(db, mems, query)
    if q is not None:
        ranked = sorted(rest, key=lambda m: -_cos(q, m.embedding))
    else:  # 字面重合优先，同分保持“最近更新”顺序（sorted 稳定）
        ranked = sorted(rest, key=lambda m: -overlap(query, m.content))
    return pinned + ranked[:TOP_K]


def overflow_note(total: int, shown: int) -> str:
    """上下文里只放了一部分记忆时告诉模型还有多少、怎么查；全放了就不说。"""
    if total <= shown:
        return ""
    return (f"（共 {total} 条记忆，这里只放了和这句话最相关的 {shown} 条；"
            "要用到没列出来的偏好或事实，先 search_memory 查，别凭印象说“我不知道”或编。）")


# ---- search_memory：在全部记忆里查（agent/builtin/memory.py 只调这里） ----
SEARCH_LIMIT = 10
LIMIT_MAX = 30
VEC_MIN = 0.35        # 向量相似度低于这个、字面又没碰上 → 不算命中
QUERY_MAX = 200


@dataclass
class Hit:
    memory: Memory
    score: float
    words: bool        # 字面碰上了
    near: bool         # 意思相近（向量）


async def search(db: AsyncSession, query: str, category: str | None = None,
                 limit: int = SEARCH_LIMIT) -> tuple[list[Hit], int, bool]:
    """返回 (命中按分数降序, 这个范围里记忆总数, 是否用上了向量)。
    query 空 → 这个分类最近更新的 limit 条（列一列）。
    分数 = 引号/空格分开的词全中优先（chat_search.terms，和翻对话同一套拆词）+ 两字词重合 + 向量相似度。"""
    query = (query or "").strip()[:QUERY_MAX]
    limit = max(1, min(int(limit or SEARCH_LIMIT), LIMIT_MAX))
    stmt = select(Memory).order_by(Memory.updated_at.desc())
    if category:
        stmt = stmt.where(Memory.category == category)
    mems = list((await db.scalars(stmt)).all())
    if not query:
        return [Hit(m, 0.0, False, False) for m in mems[:limit]], len(mems), False
    terms = chat_search.terms(query)
    q = await _vectors(db, mems, query) if mems else None
    hits: list[Hit] = []
    for m in mems:
        whole = chat_search.count_in(m.content, terms) / len(terms) if terms else 0.0
        part = overlap(query, m.content)
        cos = _cos(q, m.embedding) if q is not None and m.embedding else 0.0
        words = whole > 0 or part >= 0.5
        near = cos >= VEC_MIN
        if words or near:
            hits.append(Hit(m, whole * 2 + part + cos, words, near))
    hits.sort(key=lambda h: -h.score)  # 稳定：同分按最近更新
    return hits[:limit], len(mems), q is not None


def _day(m: Memory) -> str:
    t = m.updated_at
    if t is None:
        return ""
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    try:
        t = t.astimezone(ZoneInfo(settings.timezone))
    except Exception:  # noqa: BLE001
        pass
    return f"{t:%Y-%m-%d}"


def search_text(query: str, category: str | None, hits: list[Hit], total: int, vectors: bool) -> str:
    where = f"「{category}」类" if category else "全部"
    if not query.strip():
        if not hits:
            return f"{where}记忆是空的。"
        head = f"{where}记忆共 {total} 条，最近更新的 {len(hits)} 条："
    elif not hits:
        tail = "" if vectors else "（向量检索不可用，只按字面找了，换个说法或更短的词再试）"
        return f"在{where} {total} 条记忆里没找到和“{query}”相关的。{tail}"
    else:
        head = f"在{where} {total} 条记忆里找到 {len(hits)} 条和“{query}”相关的（越靠前越相关）："
    lines = [f"{context_line(h.memory)} 更新于 {_day(h.memory)}" + ("（意思相近）" if h.near and not h.words else "")
             for h in hits]
    return head + "\n" + "\n".join(lines) + "\n改/删时把 # 引用传给 update_memory / forget。"


async def find_similar(db: AsyncSession, content: str) -> tuple[Memory | None, list[float] | None]:
    """写记忆前查重：返回足够相似的旧记忆（用于更新而不是重复存）和新内容的向量。"""
    try:
        vec = (await llm.embed([content]))[0]
    except Exception:
        exact = await db.scalar(select(Memory).where(Memory.content == content))
        return exact, None
    mems = list((await db.scalars(select(Memory))).all())
    await _backfill(db, mems)
    best = max(mems, key=lambda m: _cos(vec, m.embedding), default=None)
    return (best if best and _cos(vec, best.embedding) >= DUPLICATE else None), vec


# ---- 按条引用与写入：工具（agent/builtin/memory.py）只调这里，聊天里的“记忆卡”也从这里出 ----
# 上下文里每条记忆带一个短引用（id 前 REF_LEN 位），模型改/删时传引用，不用再靠关键词猜。
REF_LEN = 8


def ref(m: Memory) -> str:
    return m.id[:REF_LEN]


def context_line(m: Memory) -> str:
    return f"- [{m.category}] {m.content} (#{ref(m)})"


async def resolve(db: AsyncSession, refs: list[str]) -> tuple[list[Memory], list[str]]:
    """短引用 → 记忆。返回 (找到的, 找不到或有歧义的引用)。引用可带 #，大小写不敏感。"""
    found: list[Memory] = []
    bad: list[str] = []
    for r in refs:
        key = r.strip().lstrip("#").lower()
        rows = (await db.scalars(select(Memory).where(Memory.id.startswith(key)))).all() if len(key) >= 4 else []
        if len(rows) == 1 and rows[0] not in found:
            found.append(rows[0])
        elif len(rows) != 1:
            bad.append(r)
    return found, bad


async def save(db: AsyncSession, content: str, category: str) -> tuple[Memory, str | None]:
    """记一条：意思相同的旧记忆就地覆盖（偏好会变，以最新为准）。返回 (记忆, 被覆盖前的内容或 None)。"""
    old, vec = await find_similar(db, content)
    if old:
        previous = old.content
        old.content, old.category, old.embedding = content, category, vec
        await db.commit()
        return old, previous
    m = Memory(content=content, category=category, embedding=vec)
    db.add(m)
    await db.commit()
    return m, None


async def update(db: AsyncSession, m: Memory, content: str | None, category: str | None) -> str:
    """改一条，返回改前内容。内容变了向量清空（检索时懒补，不在这里多调一次向量接口）。"""
    previous = m.content
    if content and content != m.content:
        m.content, m.embedding = content, None
    if category:
        m.category = category
    await db.commit()
    return previous


def card(action: str, items: list[tuple[Memory, str | None]]) -> dict:
    """聊天里的记忆卡块（blocks.MemoryBlock）。action = saved | updated | forgotten。"""
    return {"type": "memory", "action": action, "items": [
        {"id": m.id, "content": m.content, "category": m.category, **({"previous": p} if p else {})} for m, p in items]}
