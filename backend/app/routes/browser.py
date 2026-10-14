"""实时画面与接管：前端看截图、点画面、拖动、滚动、打字、后退刷新，都经后端转发给 browser 服务（browser 服务不对外）。
v2.82 接管 = App / 网页的全屏接管页：mouse 带 kind（click|down|move|up，长按拖滑块），scroll 是滚轮 / 单指拖动，nav 是后退 / 刷新。
每个请求带会话名（实时画面卡上的 session；旧卡没有 → main）。会话列表 / 退出登录（我的电脑 → 浏览器登录）也在这。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .. import browser_client, browser_sessions, system_alerts
from ..db import get_session
from ..auth import require_query_token, require_user

router = APIRouter(prefix="/api/browser")
Session = Query(browser_sessions.LEGACY, pattern=r"^[A-Za-z0-9_-]{1,40}$")


_NAME = r"^[A-Za-z0-9_-]{1,40}$"


def _unit(v: float) -> float:
    return min(max(v, 0), 1)


class Point(BaseModel):
    x: float
    y: float
    kind: str = Field("click", pattern=r"^(click|down|move|up)$")
    session: str = Field(browser_sessions.LEGACY, pattern=_NAME)


class Wheel(BaseModel):
    x: float = 0.5
    y: float = 0.5
    dx: float = 0
    dy: float = 0
    session: str = Field(browser_sessions.LEGACY, pattern=_NAME)


class Nav(BaseModel):
    action: str = Field(pattern=r"^(back|reload)$")
    session: str = Field(browser_sessions.LEGACY, pattern=_NAME)


class Keys(BaseModel):
    text: str | None = None
    key: str | None = None
    session: str = Field(browser_sessions.LEGACY, pattern=_NAME)


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
    await _call(p.session, "POST", "/mouse", {"x": _unit(p.x), "y": _unit(p.y), "kind": p.kind})
    return {"ok": True}


@router.post("/scroll", dependencies=[Depends(require_user)])
async def scroll(w: Wheel):
    await _call(w.session, "POST", "/scroll", {"x": _unit(w.x), "y": _unit(w.y), "dx": w.dx, "dy": w.dy})
    return {"ok": True}


@router.post("/nav", dependencies=[Depends(require_user)])
async def nav(n: Nav):
    await _call(n.session, "POST", "/nav", {"action": n.action})
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
