"""记忆检索：决定每轮对话带哪些记忆进上下文（token 成本的大头之一）。

策略（按成本从低到高）：
1. 记忆不多（≤ ALWAYS_ALL 条）→ 全带，不调向量接口
2. 记忆多了 → 用户这句话做向量检索取 top-k，profile 类（身份、禁忌）始终带上
3. 向量接口不可用 → 退回最近更新的 k 条，功能不中断

向量直接存在记忆行的 JSON 列里、内存里算余弦：单用户几千条以内毫秒级，
SQLite/Postgres 通用；真到几万条再换 pgvector 索引，接口不变。
编辑过的记忆向量会被清空，这里统一懒补齐。"""
import logging
import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import llm
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


async def relevant(db: AsyncSession, query: str) -> list[Memory]:
    mems = list((await db.scalars(select(Memory).order_by(Memory.updated_at.desc()))).all())
    if len(mems) <= ALWAYS_ALL or not query.strip():
        return mems[:ALWAYS_ALL]
    try:
        await _backfill(db, mems)
        q = (await llm.embed([query]))[0]
    except Exception:
        log.warning("embedding unavailable, falling back to recent memories")
        return mems[:TOP_K]
    pinned = [m for m in mems if m.category == "profile"]
    ranked = sorted((m for m in mems if m.category != "profile"), key=lambda m: -_cos(q, m.embedding))
    return pinned + ranked[:TOP_K]


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
