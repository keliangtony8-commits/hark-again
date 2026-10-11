from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ..auth import check_password, issue_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(body: LoginIn):
    if not check_password(body.username, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    return {"token": issue_token()}
