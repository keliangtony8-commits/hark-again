"""实时画面与接管：前端看截图、点画面、打字，都经后端转发给 browser 服务（browser 服务不对外）。"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from .. import browser_client
from ..auth import require_query_token, require_user

router = APIRouter(prefix="/api/browser")


class Point(BaseModel):
    x: float
    y: float


class Keys(BaseModel):
    text: str | None = None
    key: str | None = None


@router.get("/screen", dependencies=[Depends(require_query_token)])
async def screen():
    r = await browser_client.call("GET", "/screen")
    if r.status_code != 200:
        raise HTTPException(404, "浏览器没有打开")
    return Response(r.content, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/mouse", dependencies=[Depends(require_user)])
async def mouse(p: Point):
    await browser_client.call("POST", "/mouse", {"x": min(max(p.x, 0), 1), "y": min(max(p.y, 0), 1)})
    return {"ok": True}


@router.post("/keyboard", dependencies=[Depends(require_user)])
async def keyboard(k: Keys):
    await browser_client.call("POST", "/keyboard", k.model_dump())
    return {"ok": True}
