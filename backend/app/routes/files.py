"""文件接口：聊天附件上传/下载、项目文件管理。实际读写都在 storage.py。
下载支持 ?token=，因为 <img>/<a> 标签无法带 Authorization 头。"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .. import reply_files, storage
from ..db import get_session
from ..auth import require_query_token, require_user
from ..config import settings

router = APIRouter()
auth = [Depends(require_user)]


async def _read_limited(f: UploadFile) -> bytes:
    data = await f.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"文件超过 {settings.max_upload_mb} MB")
    return data


@router.post("/api/uploads", dependencies=auth)
async def upload(file: UploadFile):
    return storage.save_upload(file.filename or "file", await _read_limited(file))


@router.get("/api/uploads/{uid}", dependencies=[Depends(require_query_token)])
async def download_upload(uid: str):
    p = storage.upload_path(uid)
    if not p:
        raise HTTPException(404)
    return FileResponse(p, media_type=storage.mime_of(p.name), filename=p.name)


# ---- 项目文件 ----
@router.get("/api/projects/{pid}/files", dependencies=auth)
async def list_project_files(pid: str):
    root = storage.project_dir(pid)
    return [{"path": str(p.relative_to(root)), "name": p.name, "size": p.stat().st_size,
             "mime": storage.mime_of(p.name), "modified": p.stat().st_mtime}
            for p in sorted(root.rglob("*")) if p.is_file() and not storage.hidden(p.relative_to(root).parts)][:500]


@router.post("/api/projects/{pid}/files", dependencies=auth)
async def upload_project_file(pid: str, file: UploadFile):
    p = storage.safe_join(storage.project_dir(pid), file.filename or "file")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(await _read_limited(file))
    return {"path": str(p.relative_to(storage.project_dir(pid))), "size": p.stat().st_size}


@router.get("/api/projects/{pid}/files/{path:path}", dependencies=[Depends(require_query_token)])
async def download_project_file(pid: str, path: str):
    p = storage.project_file(pid, path)
    if p is None:
        raise HTTPException(404)
    return FileResponse(p, media_type=storage.mime_of(p.name), filename=p.name)


@router.delete("/api/projects/{pid}/files/{path:path}", dependencies=auth)
async def delete_project_file(pid: str, path: str):
    p = storage.safe_join(storage.project_dir(pid), path)
    if p.is_file():
        p.unlink()
    return {"ok": True}


# ---- 把一条回复存成项目文件（reply_files.py）----
class SaveReply(BaseModel):
    project_id: str | None = Field(default=None, max_length=32)  # 不给 = 回复所在对话的项目


@router.post("/api/messages/{mid}/save-to-project", dependencies=auth)
async def save_reply(mid: str, body: SaveReply, db: AsyncSession = Depends(get_session)):
    try:
        return await reply_files.save(db, mid, body.project_id or None)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
