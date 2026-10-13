"""实时画面与接管：前端看截图、点画面、打字，都经后端转发给 browser 服务（browser 服务不对外）。
每个请求带会话名（实时画面卡上的 session；旧卡没有 → main）。会话列表 / 退出登录（我的电脑 → 浏览器登录）也在这。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .. import browser_client, browser_sessions, system_alerts
from ..db import get_session
from ..auth import require_query_token, require_user

router = APIRouter(prefix="/api/browser")
Session = Query(browser_sessions.LEGACY, pattern=r"^[A-Za-z0-9_-]{1,40}$")


class Point(BaseModel):
    x: float
    y: float
    session: str = Field(browser_sessions.LEGACY, pattern=r"^[A-Za-z0-9_-]{1,40}$")


class Keys(BaseModel):
    text: str | None = None
    key: str | None = None
    session: str = Field(browser_sessions.LEGACY, pattern=r"^[A-Za-z0-9_-]{1,40}$")


async def _call(session: str, method: str, path: str, json: dict | None = None):
    """转发给 browser 服务；服务本身不能用（BrowserDown）→ 503 + 一句原因，不是 500。"""
    try:
        return await browser_client.call(session, method, path, json)
    except browser_client.BrowserDown as e:
        raise HTTPException(503, e.short)


@router.get("/screen", dependencies=[Depends(require_query_token)])
async def screen(session: str = Session):
    r = await _call(session, "GET", "/screen")
    if r.status_code != 200:
        raise HTTPException(404, "浏览器没有打开")
    return Response(r.content, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/mouse", dependencies=[Depends(require_user)])
async def mouse(p: Point):
    await _call(p.session, "POST", "/mouse", {"x": min(max(p.x, 0), 1), "y": min(max(p.y, 0), 1)})
    return {"ok": True}


@router.post("/keyboard", dependencies=[Depends(require_user)])
async def keyboard(k: Keys):
    await _call(k.session, "POST", "/keyboard", k.model_dump(exclude={"session"}))
    return {"ok": True}


@router.get("/sessions", dependencies=[Depends(require_user)])
async def sessions():
    try:
        return await browser_sessions.listing()
    except RuntimeError as e:
        raise HTTPException(503, str(e))


@router.delete("/sessions/{name}", dependencies=[Depends(require_user)])
async def sign_out(name: str, db=Depends(get_session)):
    try:
        await browser_sessions.sign_out(name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    await system_alerts.clear(db, browser_sessions.alert_subject(name))  # 退出了，“登录过期”的提醒也没意义了
    await db.commit()
    return {"ok": True}
