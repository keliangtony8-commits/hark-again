"""Pages：公开浏览 /p/<slug>/，管理接口 /api/pages（需登录）。"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import pages_store
from ..auth import require_user

router = APIRouter(prefix="/api/pages", dependencies=[Depends(require_user)])
public = APIRouter()

# 不透明源 + 禁止表单提交到别处之外的一切额外能力：页面脚本碰不到 App 的 localStorage
SANDBOX_CSP = "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox"


@public.get("/p/{slug}/")
@public.get("/p/{slug}")
async def view(slug: str):
    p = pages_store.public_html(slug)  # 下线 = 不存在：同一个 404
    if not p:
        raise HTTPException(404)
    # no-cache：下线 / 改内容后浏览器与反代必须回源确认，否则旧页面还能被打开
    return FileResponse(p, media_type="text/html", headers={"Content-Security-Policy": SANDBOX_CSP,
                                                            "X-Robots-Tag": "noindex", "Cache-Control": "no-cache"})


def _wire(m: dict) -> dict:
    return {**m, "id": m["slug"], "url": pages_store.url_of(m["slug"])}  # id：与其他资源统一


class PageIn(BaseModel):
    title: str | None = None
    published: bool | None = None


@router.get("")
async def list_pages():
    return [_wire(m) for m in pages_store.list_pages()]


@router.patch("/{slug}")
async def update(slug: str, body: PageIn):
    try:
        m = pages_store.update(slug, title=body.title, published=body.published)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if m is None:
        raise HTTPException(404)
    return _wire(m)


@router.delete("/{slug}")
async def delete(slug: str):
    try:
        pages_store.delete(slug)
    except ValueError:
        raise HTTPException(400)
    return {"ok": True}
