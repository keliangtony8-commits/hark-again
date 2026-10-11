from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..auth import check_password, issue_token, require_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(body: LoginIn):
    if not check_password(body.username, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    return {"token": issue_token()}


@router.get("/me")
async def me(user: str = Depends(require_user)):
    """当前登录的主人：客户端“我的”页页头显示用户名。只读、零查询。"""
    return {"username": user}
