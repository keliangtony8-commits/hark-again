from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import login_sessions, two_factor
from ..auth import Who, check_password, current, issue_token, require_user
from ..db import get_session

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str
    code: str | None = None  # 两步验证码或恢复码；开着两步验证时必填
    device: str | None = None  # 客户端自报的设备名（App 报“Android App”）；不报就按 User-Agent 猜


def _guard() -> None:
    if two_factor.throttle.blocked():
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, two_factor.THROTTLED)


async def _code_ok(db: AsyncSession, code: str | None) -> two_factor.Checked:
    """密码已对：开着两步验证 → 没码 428、错码 401（记一次失败）。"""
    if not await two_factor.enabled(db):
        return two_factor.Checked(True)
    if not two_factor.clean_code(code):
        raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED, two_factor.REQUIRED)
    checked = await two_factor.check(db, code or "")
    if not checked.ok:
        two_factor.throttle.fail()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, two_factor.WRONG)
    return checked


@router.post("/login")
async def login(body: LoginIn, request: Request, db: AsyncSession = Depends(get_session)):
    _guard()
    if not check_password(body.username, body.password):
        two_factor.throttle.fail()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    checked = await _code_ok(db, body.code)
    two_factor.throttle.reset()
    sid = await login_sessions.start(db, body.device, request.headers.get("user-agent"))
    out: dict = {"token": issue_token(sid)}
    if checked.recovery:  # 用了恢复码：提醒还剩几个
        out["recovery_left"] = checked.left
    return out


# ---------- 登录设备（规则在 app/login_sessions.py） ----------

@router.post("/logout")
async def logout(w: Who = Depends(current), db: AsyncSession = Depends(get_session)):
    """本机退出登录：这个 token 立刻作废（客户端再清本地）。"""
    if w.sid:
        await login_sessions.revoke(db, w.sid)
    return {"ok": True}


@router.get("/sessions")
async def sessions(w: Who = Depends(current), db: AsyncSession = Depends(get_session)):
    return {"sessions": await login_sessions.listing(db, w.sid)}


@router.delete("/sessions/{sid}")
async def revoke_session(sid: str, w: Who = Depends(current), db: AsyncSession = Depends(get_session)):
    if not await login_sessions.revoke(db, sid):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "这台设备已经退出了")
    return {"ok": True, "current": sid == w.sid}


async def _others_out(db: AsyncSession, w: Who) -> dict:
    """退出其他所有设备。本机是老 token（没 sid）→ 也会被 cutoff 作废，所以给本机换一个新 token。"""
    n = await login_sessions.revoke_others(db, w.sid)
    out: dict = {"signed_out": n}
    if not w.sid:
        out["token"] = issue_token(await login_sessions.start(db, None, None))
    return out


@router.post("/sessions/revoke-others")
async def revoke_others(w: Who = Depends(current), db: AsyncSession = Depends(get_session)):
    return await _others_out(db, w)


# ---------- 两步验证（规则在 app/two_factor.py） ----------

class CodeIn(BaseModel):
    code: str


class ConfirmIn(BaseModel):
    password: str
    code: str


async def _confirm(db: AsyncSession, user: str, body: ConfirmIn) -> None:
    """关闭 / 重新生成恢复码：当前密码 + 一个码，拿着已登录设备的人做不了。
    错了回 403 而不是 401：两端把 401 当“登录过期”直接退出登录。"""
    _guard()
    if not check_password(user, body.password):
        two_factor.throttle.fail()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "密码不对")
    if not (await two_factor.check(db, body.code)).ok:
        two_factor.throttle.fail()
        raise HTTPException(status.HTTP_403_FORBIDDEN, two_factor.WRONG)
    two_factor.throttle.reset()


@router.get("/2fa")
async def tf_status(_: str = Depends(require_user), db: AsyncSession = Depends(get_session)):
    return await two_factor.status(db)


@router.post("/2fa/setup")
async def tf_setup(user: str = Depends(require_user), db: AsyncSession = Depends(get_session)):
    try:
        return await two_factor.setup(db, user)
    except two_factor.TwoFactorError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e


@router.post("/2fa/enable")
async def tf_enable(body: CodeIn, w: Who = Depends(current), db: AsyncSession = Depends(get_session)):
    _guard()
    try:
        codes = await two_factor.enable(db, body.code)
    except two_factor.TwoFactorError as e:
        if str(e) == two_factor.WRONG:
            two_factor.throttle.fail()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    # 打开两步验证 = 顺手退出其他所有设备（偷到 token 的人从此也得过验证码）
    return {**await two_factor.status(db), "recovery_codes": codes, **await _others_out(db, w)}


@router.post("/2fa/disable")
async def tf_disable(body: ConfirmIn, user: str = Depends(require_user), db: AsyncSession = Depends(get_session)):
    if not await two_factor.enabled(db):
        return await two_factor.status(db)
    await _confirm(db, user, body)
    await two_factor.disable(db)
    return await two_factor.status(db)


@router.post("/2fa/recovery")
async def tf_recovery(body: ConfirmIn, user: str = Depends(require_user), db: AsyncSession = Depends(get_session)):
    if not await two_factor.enabled(db):
        raise HTTPException(status.HTTP_409_CONFLICT, "两步验证没开")
    await _confirm(db, user, body)
    codes = await two_factor.regenerate(db)
    return {**await two_factor.status(db), "recovery_codes": codes}
