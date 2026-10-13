"""连接器接口：OAuth 连接 + 用户的 MCP 服务器。流程都在 connectors/，这里只收发。"""
from html import escape
from json import dumps as json_dumps
from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import task_wall, vault
from ..config import settings
from ..auth import require_user
from ..connectors import mcp, oauth
from ..connectors.providers import PROVIDERS
from ..db import get_session
from ..models import Connection, McpServer

router = APIRouter(prefix="/api/connectors", dependencies=[Depends(require_user)])
public = APIRouter()  # OAuth 回调由第三方跳回，没有登录头，靠签名 state 验真


@router.get("")
async def list_connectors(db: AsyncSession = Depends(get_session)):
    conns = {c.provider: c for c in (await db.scalars(select(Connection))).all()}
    return [{"id": p.id, "name": p.name, "desc": p.desc, "logo": p.logo, "configured": p.configured,
             "account": conns[p.id].account if p.id in conns else None} for p in PROVIDERS.values()]


@router.get("/{provider}/start")
async def start(provider: str, client: Literal["web", "app"] = "web"):
    p = PROVIDERS.get(provider)
    if not p:
        raise HTTPException(404)
    if not p.configured:
        raise HTTPException(400, f"服务器还没配置 {p.name} 的 OAuth 应用（见 .env.example）")
    return {"url": oauth.authorize_url(p, client)}


@router.delete("/{provider}")
async def disconnect(provider: str, db: AsyncSession = Depends(get_session)):
    if c := await db.scalar(select(Connection).where(Connection.provider == provider)):
        await oauth.forget(db, c)
    return {"ok": True}


def _back(client: str, result: dict) -> str:
    """授权结果回到发起的客户端：网页版走 hash 路由，App 走深链。两边路径一致：/me/connectors。"""
    q = urlencode(result)
    if client == "app":
        return f"{settings.app_scheme}://app/me/connectors?{q}"
    return f"/#/me/connectors?{q}"


def _app_handoff(url: str, ok: bool) -> HTMLResponse:
    """App 场景：浏览器不一定允许无手势跳自定义 scheme，所以先自动跳一次，再给一个按钮兜底。"""
    title = "授权完成" if ok else "授权没有完成"
    u = escape(url, quote=True)
    return HTMLResponse(f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>body{{font:16px system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;
background:#f6f6f4;color:#1b1b1a}}main{{text-align:center;padding:24px}}a{{display:inline-block;margin-top:16px;
padding:12px 22px;border-radius:999px;background:#1b1b1a;color:#fff;text-decoration:none}}
@media (prefers-color-scheme:dark){{body{{background:#141413;color:#eee}}a{{background:#eee;color:#141413}}}}</style>
</head><body><main><h2>{title}</h2><p>正在回到 App…</p><a href="{u}">回到 App</a></main>
<script>location.replace({json_dumps(url).replace("<", "\\u003c")});</script></body></html>""")


@public.get("/api/oauth/callback")
async def callback(state: str, code: str = "", error: str = "", db: AsyncSession = Depends(get_session)):
    try:
        p, client = oauth.read_state(state)
    except Exception:
        return RedirectResponse(_back("web", {"error": "授权链接已过期，请重新连接"}))
    try:
        if error or not code:
            raise RuntimeError(error or "已取消")
        await oauth.complete(db, p, code)
        result, ok = {"connected": p.id}, True
    except Exception as e:
        result, ok = {"error": str(e)[:80]}, False
    if ok:
        try:  # 顺手重跑碰壁任务是锦上添花：它出错不能把“已连接”变成失败
            if note := await _retry(db, p.id, p.name):
                result["retried"] = note
        except Exception:
            pass
    url = _back(client, result)
    return _app_handoff(url, ok) if client == "app" else RedirectResponse(url)


# ---- MCP 服务器 ----
class McpIn(BaseModel):
    name: str
    url: str
    token: str = ""


def _mcp_public(s: McpServer, problem: str | None = None) -> dict:
    """problem：还没恢复的问题 "auth"（令牌被拒）| "down"（连不上）| null，客户端在这一行标出来。"""
    return {"id": s.id, "name": s.name, "url": s.url, "has_token": bool(s.token_ciphertext), "problem": problem}


@router.get("/mcp")
async def list_mcp(db: AsyncSession = Depends(get_session)):
    servers = (await db.scalars(select(McpServer).order_by(McpServer.created_at))).all()
    return [_mcp_public(s, await mcp.problem(db, s)) for s in servers]


@router.post("/mcp")
async def add_mcp(body: McpIn, db: AsyncSession = Depends(get_session)):
    if not body.url.startswith(("https://", "http://")):
        raise HTTPException(400, "地址要以 http(s):// 开头")
    s = McpServer(name=body.name.strip(), url=body.url.strip(),
                  token_ciphertext=vault.encrypt(body.token) if body.token else None)
    try:  # 先连一次，确认能用再保存
        tools = await mcp.list_tools(s)
    except Exception as e:
        raise HTTPException(400, f"连不上这个 MCP 服务器：{e}")
    db.add(s)
    note = await _retry(db, s.name)
    await db.commit()
    return {**_mcp_public(s), "tools": [t["name"] for t in tools], "retried_note": note}


async def _retry(db: AsyncSession, *names: str) -> str | None:
    """连好了：卡在“需要重新连接它”的任务重跑一次（规则在 task_wall.retry_fixed）并提交。"""
    note = task_wall.retry_note(await task_wall.retry_fixed(db, "needs_connector", names=list(names)))
    await db.commit()
    return note


@router.get("/mcp/{sid}/tools")
async def mcp_tools(sid: str, db: AsyncSession = Depends(get_session)):
    s = await db.get(McpServer, sid)
    if not s:
        raise HTTPException(404)
    try:  # 用户打开工具列表也算一次体检：不通 → 主页提醒 + 502；通了 → 收起旧提醒
        tools = await mcp.guarded(db, s, mcp.list_tools(s))
    except mcp.Unreachable as e:
        raise HTTPException(502, f"连不上这个 MCP 服务器：{e}")
    return [{"name": t["name"], "description": t.get("description", "")} for t in tools]


@router.delete("/mcp/{sid}")
async def remove_mcp(sid: str, db: AsyncSession = Depends(get_session)):
    if s := await db.get(McpServer, sid):
        await mcp.forget(db, s)
    return {"ok": True}
