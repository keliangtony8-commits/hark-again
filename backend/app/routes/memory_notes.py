"""记忆笔记接口（v2.21）：列表 / 新建 / 改 / 删。路径规范化与校验全在 app/memory_notes.py，这里只转 HTTP 状态。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import memory_notes
from ..auth import require_user
from ..db import get_session
from ..models import MemoryNote

router = APIRouter(prefix="/api/memory-notes", tags=["memory"], dependencies=[Depends(require_user)])


class NoteIn(BaseModel):
    path: str
    title: str | None = None
    kind: str | None = None
    body: str = ""


class NotePatch(BaseModel):
    path: str | None = None
    title: str | None = None
    kind: str | None = None
    body: str | None = None


def _status(e: memory_notes.NoteError) -> HTTPException:
    return HTTPException(409 if "已经有笔记" in str(e) else 422, str(e))


@router.get("")
async def list_notes(db: AsyncSession = Depends(get_session)):
    return [memory_notes.wire(n) for n in await memory_notes.all_notes(db)]


@router.post("")
async def create_note(body: NoteIn, db: AsyncSession = Depends(get_session)):
    try:
        n = await memory_notes.create(db, body.path, body.body, body.title, body.kind)
    except memory_notes.NoteError as e:
        raise _status(e)
    return memory_notes.wire(n)


@router.get("/{note_id}")
async def get_note(note_id: str, db: AsyncSession = Depends(get_session)):
    n = await db.get(MemoryNote, note_id)
    if not n:
        raise HTTPException(404)
    return memory_notes.wire(n)


@router.patch("/{note_id}")
async def patch_note(note_id: str, body: NotePatch, db: AsyncSession = Depends(get_session)):
    n = await db.get(MemoryNote, note_id)
    if not n:
        raise HTTPException(404)
    try:
        n = await memory_notes.patch(db, n, body.model_dump(exclude_unset=True))
    except memory_notes.NoteError as e:
        await db.rollback()
        raise _status(e)
    return memory_notes.wire(n)


@router.delete("/{note_id}")
async def delete_note(note_id: str, db: AsyncSession = Depends(get_session)):
    n = await db.get(MemoryNote, note_id)
    if not n:
        raise HTTPException(404)
    await db.delete(n)
    await db.commit()
    return {"ok": True}
