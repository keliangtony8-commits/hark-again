"""实时画面与接管（v2.89：一条 WS /api/browser/live，取代 v2.82 的截图轮询 + 点按 HTTP）：browser 服务不对外，后端鉴权后只转发字节。
会话名 = 实时画面卡上的 session（旧卡没有 → main）。会话列表 / 退出登录（我的电脑 → 浏览器登录）也在这。"""
import re

from fastapi import APIRouter, Depends, HTTPException, WebSocket

from .. import browser_client, browser_sessions, preview, system_alerts
from ..db import get_session
from ..auth import require_user, verify_token

router = APIRouter(prefix="/api/browser")
_NAME = r"[A-Za-z0-9_-]{1,40}"


# 关闭码 = browser/live.py CLOSE_*（客户端 models/browser_view.dart / lib/browserView.ts 同值）
CLOSE_UNAUTHORIZED, CLOSE_DOWN = 4401, 4503


@router.websocket("/live")
async def live(ws: WebSocket, token: str = "", session: str = browser_sessions.LEGACY, open: bool = False):
    """实时画面 + 接管（v2.89 §M）：一条 WS，下行 JPEG 帧、上行接管输入（消息格式见 docs/protocol.md），后端只鉴权 + 转发字节。
    先 accept 再用自定义关闭码关（握手前关客户端只看到 403，分不清原因）。"""
    await ws.accept()
    try:
        await verify_token(token)
    except HTTPException:
        await ws.close(CLOSE_UNAUTHORIZED)
        return
    if not re.fullmatch(_NAME, session):
        await ws.close(4400)
        return
    try:
        upstream = await browser_client.live_connect(session, reopen=open)
    except Exception:
        await ws.close(CLOSE_DOWN, "云浏览器服务未运行")
        return
    try:
        await preview.ws_relay(ws, upstream)
    finally:
        await upstream.close()


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
