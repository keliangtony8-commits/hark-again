"""v2.92 §P 个人资料：称呼、助手名、头像、首次问候。规则只在 app/identity.py。
取代了原来的 GET /api/auth/me（只回用户名）：“我的”页页头、顶栏头像都读这里一处。"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import identity
from ..auth import require_query_token, require_user
from ..db import get_session

router = APIRouter(prefix="/api/profile")


class Patch(BaseModel):
    display_name: str | None = None
    assistant_name: str | None = None


@router.get("")
async def get_profile(user: str = Depends(require_user), db: AsyncSession = Depends(get_session)):
    return identity.wire(await identity.get(db), user)


@router.patch("")
async def patch_profile(body: Patch, user: str = Depends(require_user), db: AsyncSession = Depends(get_session)):
    """只改请求里出现的字段（显式传 null / 空串 = 清除）。"""
    fields = body.model_fields_set
    kw = {k: getattr(body, k) for k in ("display_name", "assistant_name") if k in fields}
    try:
        ident = await identity.set_names(db, **kw)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return identity.wire(ident, user)


@router.post("/avatar")
async def post_avatar(file: UploadFile, user: str = Depends(require_user), db: AsyncSession = Depends(get_session)):
    data = await file.read(identity.AVATAR_MAX + 1)
    try:
        ident = await identity.set_avatar(db, data)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return identity.wire(ident, user)


@router.delete("/avatar")
async def delete_avatar(user: str = Depends(require_user), db: AsyncSession = Depends(get_session)):
    return identity.wire(await identity.clear_avatar(db), user)


@router.get("/avatar/{version}", dependencies=[Depends(require_query_token)])
async def get_avatar(version: str, db: AsyncSession = Depends(get_session)):
    """version 只用来换缓存（换头像地址就变）；永远给当前这一张。<img> 带不了请求头，所以用 ?token=。"""
    ident = await identity.get(db)
    p = identity.avatar_path()
    if not ident.avatar or not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type=ident.avatar_type or "image/png", headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.post("/greet")
async def greet(user: str = Depends(require_user), db: AsyncSession = Depends(get_session)):
    """主聊天空白时客户端调一次：没问候过 → 建问候对话、返回它的 id；问候过 → conversation_id = null。"""
    return {"conversation_id": await identity.greet(db)}
