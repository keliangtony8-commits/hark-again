"""服务器主机模式（我的电脑 → 服务器主机）：看状态、开关、删“以后都允许”的规则。规则与开关全在 app/host_mode.py。"""
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import host_client, host_mode
from ..auth import require_user
from ..db import get_session

router = APIRouter(prefix="/api/host", dependencies=[Depends(require_user)])


class Toggle(BaseModel):
    enabled: bool


async def _status(db: AsyncSession) -> dict:
    out = {"installed": host_mode.installed(), "enabled": await host_mode.enabled(db), "reachable": False,
           "host": None, "rules": [host_mode.rule_wire(r) for r in await host_mode.rules(db)]}
    if out["installed"]:
        try:
            out["host"] = await host_client.health()
            out["reachable"] = True
        except (httpx.HTTPError, OSError, ValueError):
            pass
    return out


@router.get("")
async def status(db: AsyncSession = Depends(get_session)):
    return await _status(db)


@router.put("")
async def toggle(body: Toggle, db: AsyncSession = Depends(get_session)):
    try:
        await host_mode.set_enabled(db, body.enabled)
    except host_mode.HostModeError as e:
        raise HTTPException(409, str(e))
    return await _status(db)


@router.delete("/rules/{rid}")
async def delete_rule(rid: str, db: AsyncSession = Depends(get_session)):
    if not await host_mode.remove_rule(db, rid):
        raise HTTPException(404, "没有这条规则")
    return await _status(db)
