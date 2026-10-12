"""保险箱接口：只能存、列（脱敏）、删。没有任何读取明文的接口。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import command_env, vault
from ..auth import require_user
from ..db import get_session
from ..models import Secret

router = APIRouter(prefix="/api/vault", dependencies=[Depends(require_user)])


class SecretIn(BaseModel):
    kind: str = "api_key"          # api_key | login | env（命令环境变量：name 即变量名，不要 hosts）
    name: str
    username: str | None = None
    value: str = Field(min_length=4)
    hosts: list[str] = Field(default_factory=list)
    header_name: str = "Authorization"
    header_prefix: str = "Bearer "


@router.get("")
async def list_secrets(db: AsyncSession = Depends(get_session)):
    return [vault.public(s) for s in (await db.scalars(select(Secret).order_by(Secret.created_at.desc()))).all()]


@router.post("")
async def create_secret(body: SecretIn, db: AsyncSession = Depends(get_session)):
    if body.kind == command_env.KIND:
        return await _create_env(body, db)
    if body.kind not in ("api_key", "login"):
        raise HTTPException(400, "不认识的类型")
    try:
        s = vault.create(body.name, body.value, body.hosts, body.kind, body.username, body.header_name, body.header_prefix)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    if s.kind == "login" and not (s.username or "").strip():
        raise HTTPException(400, "登录需要填用户名")
    if not s.hosts:
        raise HTTPException(400, "至少填一个有效域名")
    db.add(s)
    await db.commit()
    return vault.public(s)


async def _create_env(body: SecretIn, db: AsyncSession) -> dict:
    """命令环境变量：规则全在 command_env.save（聊天里的要变量卡也走它）。"""
    try:
        s, _ = await command_env.save(db, body.name, body.value)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    return vault.public(s)


@router.delete("/{sid}")
async def delete_secret(sid: str, db: AsyncSession = Depends(get_session)):
    if s := await db.get(Secret, sid):
        env = s.kind == command_env.KIND
        await db.delete(s)
        await db.commit()
        if env:
            await command_env.load(db)
    return {"ok": True}
