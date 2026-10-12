"""端口预览：公开转发 /api/preview/<token>/…（不用登录，靠签名链接；规则全在 app/preview.py），
和电脑页端口旁“预览”按钮的签链接口（要登录；在听的端口随 GET …/computer 一起给，见 computer.status）。"""
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

import httpx

from .. import preview, preview_rewrite, sandbox_client
from ..auth import require_user
from .files import _workspace

router = APIRouter(dependencies=[Depends(require_user)])
public = APIRouter()
METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


class PreviewIn(BaseModel):
    port: int = Field(ge=1, le=65535)
    path: str = ""


@router.post("/api/projects/{pid}/computer/preview")
async def open_preview(body: PreviewIn, pid: str = Depends(_workspace)):
    try:
        out = await preview.open_port(pid, body.port, body.path)
    except preview.PreviewError as e:
        raise HTTPException(409, str(e))
    out.pop("internal_url", None)  # 只给助手自己的浏览器
    return out


def _page(kind: str) -> HTMLResponse:
    code, html = preview.error_page(kind)
    return HTMLResponse(html, status_code=code, headers={"Content-Security-Policy": preview.CSP, "Cache-Control": "no-store"})


@public.api_route("/api/preview/{token}", methods=METHODS)
async def bare(token: str):
    """没有结尾斜杠：先跳到 …/token/，页面里的相对路径才落在预览前缀下。"""
    if preview.verify(token) is None:
        return _page("expired")
    return RedirectResponse(preview.base_path(token), status_code=307)


@public.api_route("/api/preview/{token}/{path:path}", methods=METHODS)
async def forward(token: str, path: str, request: Request):
    hit = preview.verify(token)
    if hit is None:
        return _page("expired")
    ws, port = hit
    if request.method == "OPTIONS" and "access-control-request-method" in request.headers:
        return Response(status_code=204, headers=dict(preview.preflight_headers(
            request.headers.get("access-control-request-method", ""), request.headers.get("access-control-request-headers", ""))))
    body = await request.body()
    if len(body) > preview.BODY_MAX:
        return _page("too_large")
    try:
        r = await sandbox_client.preview_send(ws, port, request.method, path, request.url.query.encode(),
                                              preview.request_headers(list(request.headers.items()), token), body)
    except httpx.HTTPError:
        return _page("unreachable")
    if "x-sandbox-preview" not in r.headers:  # 沙盒自己拒的：休眠 / 端口上没人 / 太大
        await r.aread()
        await r.aclose()
        try:
            kind = r.json().get("detail")
        except ValueError:
            kind = None
        return _page(kind if kind in ("asleep", "no_service", "too_large") else "unreachable")
    items, body = list(r.headers.multi_items()), r.aiter_raw()
    k = preview_rewrite.wants(request.method, r.status_code, r.headers)
    if k:  # 页面里以 / 开头的绝对路径补上预览前缀（规则全在 preview_rewrite.py）
        try:
            items, body = await preview_rewrite.collect(r, k, token)
        except httpx.HTTPError:
            await r.aclose()
            return _page("unreachable")
    out = [(h.encode("latin-1"), v.encode("latin-1")) for h, v in preview.response_headers(items, token)]
    if isinstance(body, bytes):
        await r.aclose()
        resp = Response(body, status_code=r.status_code)
        resp.raw_headers = out + [(b"content-length", str(len(body)).encode())]
        return resp
    resp = StreamingResponse(body, status_code=r.status_code, background=BackgroundTask(r.aclose))
    resp.raw_headers = out
    return resp


@public.websocket("/api/preview/{token}/{path:path}")
async def forward_ws(ws: WebSocket, token: str, path: str):
    """预览页里的 WebSocket（热更新、Streamlit…）：验签 → 经沙盒和容器里的服务握手 → 用上游选的子协议接受 → 双向搬运。
    任何一步不成就不接受（浏览器拿到握手失败，页面自己会重试）。"""
    hit = preview.verify(token)
    if hit is None:
        await ws.close(1008)
        return
    ws_id, port = hit
    try:
        upstream = await sandbox_client.preview_ws(
            ws_id, port, path, ws.url.query, preview.ws_headers(list(ws.headers.items()), token),
            preview.ws_protocols(ws.headers.get("sec-websocket-protocol", "")))
    except Exception:
        await ws.close(1011)
        return
    await ws.accept(subprotocol=upstream.subprotocol)
    try:
        await preview.ws_relay(ws, upstream)
    finally:
        await upstream.close()
