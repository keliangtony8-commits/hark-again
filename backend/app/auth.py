"""单用户鉴权：这是你的私人助手，只有一个主人。多用户留到需要时再扩展。"""
import hmac
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

_bearer = HTTPBearer(auto_error=False)


def check_password(username: str, password: str) -> bool:
    return hmac.compare_digest(username, settings.owner_username) and hmac.compare_digest(
        password, settings.owner_password
    )


def issue_token() -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_ttl_hours)
    return jwt.encode({"sub": settings.owner_username, "exp": exp}, settings.jwt_secret, algorithm="HS256")


def verify_token(token: str) -> str:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from e


def require_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    if not cred:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing token")
    return verify_token(cred.credentials)


def require_query_token(token: str = Query("")) -> str:
    """给 <img>/<a> 用：它们带不了 Authorization 头，只能把 token 放在 ?token= 里。"""
    return verify_token(token)
