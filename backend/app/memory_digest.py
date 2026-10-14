"""“我对你的了解”：全部记忆 → 一段第二人称的概括。

成本控制：从不自动生成，只有用户点“生成/更新”才调一次便宜模型（settings.summary_model，记账 kind=digest）；
读取（GET）零模型调用，只比对指纹告诉客户端是否过期。输入按字符预算截断（profile 类优先），
记忆再多也是一次小调用。指纹 = 每条记忆 id+updated_at 排序后的哈希：增删改任何一条都会变。"""
import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import llm, reply_language
from .config import settings
from .models import Memory, MemoryDigest
from .wire_time import iso

INPUT_CHARS = 12000   # 送给模型的记忆原文上限
DIGEST_ID = "me"

PROMPT = (
    "下面是一个私人助手记住的关于用户的事实，每行一条，方括号里是分类。"
    "请用中文、第二人称“你”，写一段 150~300 字的概括，让用户一眼看到助手对他的了解："
    "先身份与近况，再偏好与禁忌，最后习惯。只用给出的事实，不推测、不加建议、不用标题和列表。"
)


def fingerprint(mems: list[Memory]) -> str:
    h = hashlib.sha256()
    for m in sorted(mems, key=lambda m: m.id):
        h.update(f"{m.id}:{m.updated_at.isoformat() if m.updated_at else ''}\n".encode())
    return h.hexdigest()


def _lines(mems: list[Memory]) -> str:
    """profile 先、其余按最近更新；超预算的旧记忆不送。"""
    ordered = sorted(mems, key=lambda m: (m.category != "profile", -(m.updated_at.timestamp() if m.updated_at else 0)))
    out, used = [], 0
    for m in ordered:
        line = f"[{m.category}] {m.content}"
        if used + len(line) > INPUT_CHARS:
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)


async def _memories(db: AsyncSession) -> list[Memory]:
    return list((await db.scalars(select(Memory))).all())


def _wire(d: MemoryDigest | None, mems: list[Memory]) -> dict:
    if d is None:
        return {"text": None, "generated_at": None, "count": 0, "memories": len(mems), "stale": False}
    return {"text": d.text, "generated_at": iso(d.created_at), "count": d.memory_count,
            "memories": len(mems), "stale": d.fingerprint != fingerprint(mems)}


async def get(db: AsyncSession) -> dict:
    return _wire(await db.get(MemoryDigest, DIGEST_ID), await _memories(db))


async def regenerate(db: AsyncSession) -> dict:
    """调模型重写。没有记忆 → 删掉旧概括返回空；模型失败抛出（路由转 502），旧概括保留。"""
    mems = await _memories(db)
    old = await db.get(MemoryDigest, DIGEST_ID)
    if not mems:
        if old:
            await db.delete(old)
            await db.commit()
        return _wire(None, mems)
    prompt = PROMPT.replace("请用中文", "请用" + reply_language.name_or(await reply_language.get(db), "中文"))
    text = await llm.complete([{"role": "system", "content": prompt}, {"role": "user", "content": _lines(mems)}],
                              model=settings.summary_model, kind="digest")
    if not text:
        raise RuntimeError("empty digest")
    if old is None:
        old = MemoryDigest(id=DIGEST_ID, text=text, fingerprint="", memory_count=0)
        db.add(old)
    old.text, old.fingerprint, old.memory_count = text, fingerprint(mems), len(mems)
    old.created_at = datetime.now(timezone.utc)
    await db.commit()
    return _wire(old, mems)

