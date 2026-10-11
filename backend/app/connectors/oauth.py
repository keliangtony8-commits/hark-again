"""OAuth 授权码流程 + Token 刷新。state 用 JWT 签名，回调无需登录态也能验真。"""
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import vault
from ..config import settings
from ..models import Connection
from .providers import PROVIDERS, Provider

STATE_TTL = timedelta(minutes=10)
CLIENTS = ("web", "app")  # 授权完回到哪：网页版还是原生 App（只能是这两个，防开放重定向）


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
    await db.commit()
    return conn


async def access_token(db: AsyncSession, conn: Connection) -> str:
    """拿可用的 access token；快过期就用 refresh token 换新的。"""
    data = json.loads(vault.decrypt(conn.ciphertext))
    soon = datetime.now(timezone.utc) + timedelta(minutes=2)
    expires = conn.expires_at.replace(tzinfo=conn.expires_at.tzinfo or timezone.utc) if conn.expires_at else None
    if expires and expires < soon and data.get("refresh_token"):
        p = PROVIDERS[conn.provider]
        tok = await _token_request(p, {"grant_type": "refresh_token", "refresh_token": data["refresh_token"]})
        _store(conn, tok, keep_refresh=data["refresh_token"])
        await db.commit()
        return tok["access_token"]
    return data["access_token"]
