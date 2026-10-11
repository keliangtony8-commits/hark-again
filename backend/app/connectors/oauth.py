"""OAuth 授权码流程 + Token 刷新。state 用 JWT 签名，回调无需登录态也能验真。

连接失效（refresh 被服务商拒绝 / 过期又没有 refresh token / 调接口被 401）→ expired()：Home 放一张系统提醒
（去处 connectors、没有“去做”——重新授权只能本人来），工具拿到 ReconnectNeeded 的中文说明转告模型。
同一份 token 只提醒一次（键含密文指纹）；重新连上（complete）或断开（forget）→ 收起提醒。
网络错误（连不上服务商）不算失效，原样抛出、不提醒。"""
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import system_alerts, vault
from ..config import settings
from ..models import Connection
from .providers import PROVIDERS, Provider

STATE_TTL = timedelta(minutes=10)
CLIENTS = ("web", "app")  # 授权完回到哪：网页版还是原生 App（只能是这两个，防开放重定向）


class ReconnectNeeded(RuntimeError):
    """这个连接用不了了，要用户重新授权。str(e) 是给模型看的中文说明。"""


def redirect_uri() -> str:
    return f"{settings.public_url.rstrip('/')}/api/oauth/callback"


def authorize_url(p: Provider, client: str = "web") -> str:
    if client not in CLIENTS:
        raise ValueError(f"unknown client {client}")
    state = jwt.encode({"p": p.id, "c": client, "n": secrets.token_urlsafe(8),
                        "exp": datetime.now(timezone.utc) + STATE_TTL},
                       settings.jwt_secret, algorithm="HS256")
    q = {"client_id": p.client_id, "redirect_uri": redirect_uri(), "response_type": "code",
         "scope": " ".join(p.scopes), "state": state, **p.extra_auth_params}
    return f"{p.authorize_url}?{urlencode(q)}"


def read_state(state: str) -> tuple[Provider, str]:
    """验签 state，返回 (服务商, 回到哪个客户端)。过期或伪造直接抛错。"""
    data = jwt.decode(state, settings.jwt_secret, algorithms=["HS256"])
    client = data.get("c", "web")
    return PROVIDERS[data["p"]], client if client in CLIENTS else "web"


async def _token_request(p: Provider, data: dict) -> dict:
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(p.token_url, headers={"Accept": "application/json"},
                         data={"client_id": p.client_id, "client_secret": p.client_secret, **data})
    r.raise_for_status()
    tok = r.json()
    if "access_token" not in tok:
        raise RuntimeError(tok.get("error_description") or tok.get("error") or "授权失败")
    return tok


def _store(conn: Connection, tok: dict, keep_refresh: str | None = None) -> None:
    refresh = tok.get("refresh_token") or keep_refresh
    conn.ciphertext = vault.encrypt(json.dumps({"access_token": tok["access_token"], "refresh_token": refresh}))
    conn.expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(tok["expires_in"]))
                       if tok.get("expires_in") else None)


async def complete(db: AsyncSession, p: Provider, code: str) -> Connection:
    tok = await _token_request(p, {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri()})
    async with httpx.AsyncClient(timeout=20) as c:
        info = (await c.get(p.userinfo_url, headers={"Authorization": f"Bearer {tok['access_token']}"})).json()
    conn = await db.scalar(select(Connection).where(Connection.provider == p.id)) or Connection(provider=p.id)
    conn.account = str(info.get(p.account_field, ""))
    _store(conn, tok)
    db.add(conn)
    await system_alerts.clear(db, f"connector:{conn.provider}")
    await db.commit()
    return conn


async def forget(db: AsyncSession, conn: Connection) -> None:
    """断开连接：删掉它，连同“已失效”的提醒（用户主动断开，不必再提醒重连）。"""
    await db.delete(conn)
    await system_alerts.clear(db, f"connector:{conn.provider}")
    await db.commit()


async def expired(db: AsyncSession, conn: Connection, reason: str) -> ReconnectNeeded:
    """记下“这个连接失效了”：发提醒（同一份 token 只一次）并提交，返回给工具抛的异常。"""
    p = PROVIDERS.get(conn.provider)
    name = p.name if p else conn.provider
    who = f"（{conn.account}）" if conn.account else ""
    fp = hashlib.sha256(conn.ciphertext.encode()).hexdigest()[:16]
    await system_alerts.post(
        db, subject=f"connector:{conn.provider}", once=fp, title=f"{name} 连接已失效",
        text=(f"{reason}。在重新连接之前，助手用不了你的 {name}{who}。\n\n"
              "去连接器页重新连接一次就好，连上后这张卡自动收起。"),
        open="connectors")
    await db.commit()
    return ReconnectNeeded(f"{name} 连接已失效（{reason}），需要用户在“连接器”页重新连接；"
                           "已经在主页放了提醒，请告诉用户，别再重试这个连接。")


def _refused(e: Exception) -> str | None:
    """refresh 失败的原因（服务商拒绝 = 失效）；网络问题 → None（不算失效）。"""
    if isinstance(e, httpx.HTTPStatusError):
        return f"授权被 {e.response.status_code} 拒绝" if e.response.status_code < 500 else None
    if isinstance(e, RuntimeError):
        return f"刷新授权没成功：{str(e)[:60]}"
    return None


async def access_token(db: AsyncSession, conn: Connection) -> str:
    """拿可用的 access token；快过期就用 refresh token 换新的。换不了 → ReconnectNeeded（并已提醒用户）。"""
    data = json.loads(vault.decrypt(conn.ciphertext))
    now = datetime.now(timezone.utc)
    expires = conn.expires_at.replace(tzinfo=conn.expires_at.tzinfo or timezone.utc) if conn.expires_at else None
    if expires and expires < now + timedelta(minutes=2):
        if not data.get("refresh_token"):
            if expires < now:
                raise await expired(db, conn, "授权已过期，服务商没给续期凭证")
            return data["access_token"]
        p = PROVIDERS[conn.provider]
        try:
            tok = await _token_request(p, {"grant_type": "refresh_token", "refresh_token": data["refresh_token"]})
        except (httpx.HTTPStatusError, RuntimeError) as e:
            if (reason := _refused(e)) is None:
                raise
            raise await expired(db, conn, reason) from e
        _store(conn, tok, keep_refresh=data["refresh_token"])
        await db.commit()
        return tok["access_token"]
    return data["access_token"]
