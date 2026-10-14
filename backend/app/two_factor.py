"""v2.58 两步验证（对标 Hark 设置 → 安全 → 打开两步验证）：这是唯一的规则处。

这台服务器能替你跑命令、开浏览器、动保险箱，只靠一个密码太薄。打开后登录要多填验证器 App（Google
Authenticator / Microsoft Authenticator / 1Password…）里的 6 位码，丢了手机用一次性恢复码。

- TOTP 按 RFC 6238：SHA1、6 位、30 秒一步，前后各容 1 步（手机时钟偏一点也能过）；同一步的码只认一次（防重放）。
- 秘钥只存加密后的（Fernet，钥匙由 JWT_SECRET 派生，不依赖保险箱的 VAULT_KEY）；恢复码只存 SHA-256。
- 打开分两步：setup 先生成“待确认”的秘钥，用户用验证器扫/填好、回填一个码 enable 才算开；没确认前登录不受影响。
- 关闭、重新生成恢复码都要当前密码 + 一个验证码（或恢复码）：拿到一台已登录设备的人关不掉它。
- 试错上限（Throttle）：密码/验证码连续错 FAIL_MAX 次 → FAIL_WINDOW 秒内一律 429；单用户服务器，计数是全局的。
- 手机和恢复码都丢了：在服务器上 `python -m app.two_factor --reset` 关掉（能登服务器的人本来就是主人）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .version import APP_NAME
from .models import OwnerSecurity
from .wire_time import iso

ISSUER = APP_NAME  # 认证器里显示的名字；改名不影响已绑定的验证码（密钥不变）
DIGITS = 6
STEP_S = 30
DRIFT_STEPS = 1
SECRET_BYTES = 20  # 160 位，RFC 4226 推荐
RECOVERY_COUNT = 8
RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # 去掉 0/o、1/l/i 这些看错的
FAIL_MAX = 5
FAIL_WINDOW = 300

REQUIRED = "请输入验证器里的 6 位码"  # 登录时开着两步验证但没给码（HTTP 428）
WRONG = "验证码不对，看一下验证器里最新的 6 位码"
THROTTLED = "试错太多了，5 分钟后再试"


class TwoFactorError(ValueError):
    """用户能看懂的中文原因；路由翻成 400/401/409。"""


# ---------- TOTP（RFC 6238 / 4226） ----------

def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    s = secret.upper().replace(" ", "")
    return base64.b32decode(s + "=" * (-len(s) % 8))


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    off = digest[-1] & 0x0F
    n = struct.unpack(">I", digest[off:off + 4])[0] & 0x7FFFFFFF
    return str(n % 10 ** DIGITS).zfill(DIGITS)


def step_of(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP_S)


def clean_code(code: str | None) -> str:
    """去空格/横杠，全角数字转半角（中文输入法常见）。"""
    s = (code or "").strip().translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    return "".join(ch for ch in s if ch not in " -_").lower()


def match_step(secret: str, code: str, last_step: int, now: float | None = None) -> int | None:
    """码对上的那一步（> last_step 才算，防同一个码用两次）；对不上 → None。"""
    code = clean_code(code)
    if len(code) != DIGITS or not code.isdigit():
        return None
    cur = step_of(now)
    for step in range(cur - DRIFT_STEPS, cur + DRIFT_STEPS + 1):
        if step > last_step and hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def uri(secret: str, account: str) -> str:
    label = quote(f"{ISSUER}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}&algorithm=SHA1&digits={DIGITS}&period={STEP_S}"


def qr_rows(text: str) -> list[str]:
    """二维码模块矩阵（"1" 黑 / "0" 白，不含留白边）：两端自己画（App CustomPaint / 网页 SVG），不引图片库。"""
    import qrcode  # 纯 Python；只有打开两步验证时才用
    q = qrcode.QRCode(border=0, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(text)
    q.make(fit=True)
    return ["".join("1" if c else "0" for c in row) for row in q.get_matrix()]


def group(secret: str) -> str:
    """手动输入用：每 4 个字符一组。"""
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))


# ---------- 恢复码 ----------

def new_recovery_codes() -> list[str]:
    def one() -> str:
        s = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(8))
        return f"{s[:4]}-{s[4:]}"
    codes: list[str] = []
    while len(codes) < RECOVERY_COUNT:
        c = one()
        if c not in codes:
            codes.append(c)
    return codes


def hash_recovery(code: str) -> str:
    return hashlib.sha256(clean_code(code).encode()).hexdigest()


# ---------- 存储 ----------

def _fernet() -> Fernet:
    raw = hashlib.sha256(b"two-factor:" + settings.jwt_secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def _seal(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def _open(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:  # JWT_SECRET 换了：旧秘钥解不开 → 当没开（主人能用新密钥重设）
        return None


async def _row(db: AsyncSession) -> OwnerSecurity:
    row = await db.scalar(select(OwnerSecurity).where(OwnerSecurity.id == 1))
    if row is None:
        row = OwnerSecurity(id=1, recovery=[], last_step=0)
        db.add(row)
        await db.flush()
    return row


async def enabled(db: AsyncSession) -> bool:
    row = await db.scalar(select(OwnerSecurity).where(OwnerSecurity.id == 1))
    return bool(row and row.enabled_at and _open(row.secret))


def _wire(row: OwnerSecurity) -> dict:
    on = bool(row.enabled_at and _open(row.secret))
    return {"enabled": on, "enabled_at": iso(row.enabled_at) if on else None,
            "recovery_left": len(row.recovery or []) if on else 0, "pending": bool(row.pending) and not on}


async def status(db: AsyncSession) -> dict:
    return _wire(await _row(db))


async def setup(db: AsyncSession, account: str) -> dict:
    """生成（或换一个）待确认的秘钥。已经开着 → 先关再开（换手机走“关掉再开”，免得半路两套码都不认）。"""
    row = await _row(db)
    if _wire(row)["enabled"]:
        raise TwoFactorError("两步验证已经开着；要换手机，先关掉再重新打开")
    secret = new_secret()
    row.pending = _seal(secret)
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    link = uri(secret, account)
    return {"secret": group(secret), "uri": link, "qr": qr_rows(link), "issuer": ISSUER, "account": account,
            "digits": DIGITS, "period": STEP_S}


async def enable(db: AsyncSession, code: str, now: float | None = None) -> list[str]:
    row = await _row(db)
    if _wire(row)["enabled"]:
        raise TwoFactorError("两步验证已经开着")
    secret = _open(row.pending)
    if not secret:
        raise TwoFactorError("先点“打开两步验证”拿到秘钥，再填验证码")
    step = match_step(secret, code, 0, now)
    if step is None:
        raise TwoFactorError(WRONG)
    codes = new_recovery_codes()
    row.secret, row.pending, row.last_step = row.pending, None, step
    row.recovery = [hash_recovery(c) for c in codes]
    row.enabled_at = row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return codes


@dataclass
class Checked:
    ok: bool
    recovery: bool = False  # 用掉的是恢复码
    left: int = 0           # 还剩几个恢复码


async def check(db: AsyncSession, code: str, now: float | None = None) -> Checked:
    """登录 / 关闭 / 重新生成时核一个码：6 位数字按 TOTP，否则按恢复码（用掉即作废）。成功会提交。"""
    row = await _row(db)
    secret = _open(row.secret)
    if not (row.enabled_at and secret):
        return Checked(True)
    c = clean_code(code)
    if c.isdigit() and len(c) == DIGITS:
        step = match_step(secret, c, row.last_step or 0, now)
        if step is None:
            return Checked(False)
        row.last_step = step
        await db.commit()
        return Checked(True, left=len(row.recovery or []))
    h = hash_recovery(c)
    left = list(row.recovery or [])
    hit = next((x for x in left if hmac.compare_digest(x, h)), None)
    if not hit:
        return Checked(False)
    left.remove(hit)
    row.recovery = left
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return Checked(True, recovery=True, left=len(left))


async def disable(db: AsyncSession) -> None:
    row = await _row(db)
    row.secret = row.pending = None
    row.enabled_at = None
    row.recovery = []
    row.last_step = 0
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()


async def regenerate(db: AsyncSession) -> list[str]:
    row = await _row(db)
    if not _wire(row)["enabled"]:
        raise TwoFactorError("两步验证没开")
    codes = new_recovery_codes()
    row.recovery = [hash_recovery(c) for c in codes]
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return codes


# ---------- 试错上限 ----------

class Throttle:
    def __init__(self, limit: int = FAIL_MAX, window: float = FAIL_WINDOW):
        self.limit, self.window, self.fails = limit, window, []

    def _trim(self, now: float) -> None:
        self.fails = [t for t in self.fails if now - t < self.window]

    def blocked(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        self._trim(now)
        return len(self.fails) >= self.limit

    def fail(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self._trim(now)
        self.fails.append(now)

    def reset(self) -> None:
        self.fails.clear()


throttle = Throttle()


# ---------- 命令行救急 ----------

async def _reset_cli() -> None:
    from .db import SessionLocal
    async with SessionLocal() as db:
        await disable(db)


if __name__ == "__main__":  # pragma: no cover
    if "--reset" in sys.argv:
        import asyncio
        asyncio.run(_reset_cli())
        print("两步验证已关闭；用密码登录后可以在 我的 → 安全 重新打开。")
    else:
        print("用法：python -m app.two_factor --reset   （手机和恢复码都丢了时关掉两步验证）")
