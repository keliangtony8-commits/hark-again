"""单用户鉴权：这是你的私人助手，只有一个主人。多用户留到需要时再扩展。
token 还算不算数（设备被退出了没有）只问 app/login_sessions.py。"""
import hmac
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import login_sessions
from .config import settings

_bearer = HTTPBearer(auto_error=False)


@dataclass
class Who:
    user: str
    sid: str | None  # None = v2.61 之前签的老 token


def check_password(username: str, password: str) -> bool:
    return hmac.compare_digest(username, settings.owner_username) and hmac.compare_digest(
        password, settings.owner_password
    )


def issue_token(sid: str | None = None) -> str:
    """登录时带 sid（login_sessions.start 开的会话）；不带 = 服务器自己用的老式 token（受 cutoff 约束）。"""
    exp = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_ttl_hours)
    claims: dict = {"sub": settings.owner_username, "exp": exp, "iat": int(time.time())}
    if sid:
        claims["sid"] = sid
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


async def who(token: str) -> Who:
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from e
    sid = claims.get("sid")
    if not await login_sessions.alive(sid, claims.get("iat")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, login_sessions.SIGNED_OUT)
    return Who(claims["sub"], sid)


async def verify_token(token: str) -> str:
    return (await who(token)).user


async def current(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Who:
    if not cred:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing token")
    return await who(cred.credentials)


async def require_user(w: Who = Depends(current)) -> str:
    return w.user


async def require_query_token(token: str = Query("")) -> str:
    """给 <img>/<a> 用：它们带不了 Authorization 头，只能把 token 放在 ?token= 里。"""
    return await verify_token(token)
