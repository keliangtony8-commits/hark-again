"""v2.61 登录设备（对标 Hark 设置 → 安全：看哪些设备登着、退出某一台、退出其他所有设备）：唯一的规则处。

“哪个 token 还算数”只在这里判断：
- 每次登录成功开一条 LoginSession（设备名 + 登录时间 + 最近活动），token 里带它的 id（sid）。
  token 算数 ⇔ 签名对、没过期，且 sid 那条会话还在、没被退出。
- 没有 sid 的 token（v2.61 之前登录的设备、服务器自己签的）只在“退出其他所有设备”之前签发的才不算数：
  owner_security.sessions_cutoff 之前的一律作废。这样升级后老设备不用重新登录，但一键退出也能踢掉它们。
- 退出某一台 / 退出其他所有 / 本机退出登录：标记 revoked_at，立刻生效（本进程缓存同步改），别的进程最多 RELOAD_S 秒。
- 打开两步验证时顺手退出其他所有设备（偷到 token 的人从此还得过验证码这关），结果告诉用户退了几台。
- 校验走内存快照（活着的 sid + cutoff），RELOAD_S 秒或本地改动后重读；不认识的 sid 先强制重读一次再判（别的进程刚登录）。
  “最近活动”最多 TOUCH_S 秒写一次库，不让每个请求都写。
- 列表只给没退出、没过期的会话，按最近活动倒序；退出/过期超过 KEEP_DAYS 天的行顺手删掉。
"""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import SessionLocal
from .models import LoginSession, OwnerSecurity
from .wire_time import iso

RELOAD_S = 30
TOUCH_S = 300
KEEP_DAYS = 30
LABEL_MAX = 60

SIGNED_OUT = "这台设备已经退出登录，请重新登录"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: datetime | None) -> datetime | None:
    return v if v is None or v.tzinfo else v.replace(tzinfo=timezone.utc)


# ---------- 设备名 ----------

_BROWSERS = [("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"),
             ("CriOS/", "Chrome"), ("Safari/", "Safari")]
_SYSTEMS = [("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"),
            ("Mac OS X", "Mac"), ("Macintosh", "Mac"), ("CrOS", "ChromeOS"), ("Linux", "Linux")]


def label(device: str | None, user_agent: str | None) -> tuple[str, str]:
    """(设备名, 种类 app|browser|other)。客户端报了 device（App 报“Android App”这类）就用它，否则从 UA 猜“Chrome · Windows”。"""
    d = re.sub(r"\s+", " ", (device or "")).strip()[:LABEL_MAX]
    if d:
        return d, "app" if "app" in d.lower() else "other"
    ua = user_agent or ""
    if ua.startswith("Dart/"):
        return "App", "app"
    browser = next((name for key, name in _BROWSERS if key in ua), "")
    system = next((name for key, name in _SYSTEMS if key in ua), "")
    if browser and system:
        return f"{browser} · {system}", "browser"
    if browser or system:
        return browser or system, "browser"
    return "未知设备", "other"


# ---------- 内存快照 ----------

@dataclass
class _Snap:
    alive: dict[str, float]  # sid → 上次写库的最近活动（epoch 秒）
    cutoff: float | None     # 无 sid 的 token：iat 早于它就作废
    at: float = 0.0


_snap: _Snap | None = None


async def _load() -> _Snap:
    global _snap
    async with SessionLocal() as db:
        rows = (await db.execute(select(LoginSession.id, LoginSession.last_seen_at)
                                 .where(LoginSession.revoked_at.is_(None)))).all()
        cut = await db.scalar(select(OwnerSecurity.sessions_cutoff).where(OwnerSecurity.id == 1))
    cut = _aware(cut)
    _snap = _Snap({sid: _aware(seen).timestamp() for sid, seen in rows}, cut.timestamp() if cut else None, time.time())
    return _snap


async def _current(force: bool = False) -> _Snap:
    if force or _snap is None or time.time() - _snap.at > RELOAD_S:
        return await _load()
    return _snap


def forget() -> None:
    """测试 / 本地改动后：下次校验重读库。"""
    global _snap
    _snap = None


# ---------- 校验 ----------

async def alive(sid: str | None, iat: float | None) -> bool:
    snap = await _current()
    if not sid:
        return snap.cutoff is None or (iat is not None and iat >= snap.cutoff)
    seen = snap.alive.get(sid)
    if seen is None:
        snap = await _current(force=True)
        seen = snap.alive.get(sid)
        if seen is None:
            return False
    now = time.time()
    if now - seen > TOUCH_S:
        snap.alive[sid] = now
        async with SessionLocal() as db:
            await db.execute(update(LoginSession).where(LoginSession.id == sid).values(last_seen_at=_now()))
            await db.commit()
    return True


# ---------- 增删 ----------

async def start(db: AsyncSession, device: str | None, user_agent: str | None) -> str:
    name, kind = label(device, user_agent)
    now = _now()
    row = LoginSession(id=uuid.uuid4().hex, label=name, kind=kind, created_at=now, last_seen_at=now)
    db.add(row)
    await db.commit()
    if _snap is not None:
        _snap.alive[row.id] = now.timestamp()
    return row.id


def _expired_before() -> datetime:
    return _now() - timedelta(hours=settings.jwt_ttl_hours)


async def listing(db: AsyncSession, current: str | None) -> list[dict]:
    old = _now() - timedelta(days=KEEP_DAYS)
    await db.execute(delete(LoginSession).where(or_(LoginSession.revoked_at < old,
                                                    LoginSession.created_at < old - timedelta(hours=settings.jwt_ttl_hours))))
    await db.commit()
    rows = (await db.scalars(select(LoginSession).where(LoginSession.revoked_at.is_(None),
                                                        LoginSession.created_at >= _expired_before()))).all()
    rows = sorted(rows, key=lambda r: (r.id != current, -_aware(r.last_seen_at).timestamp()))
    return [{"id": r.id, "label": r.label, "kind": r.kind, "created_at": iso(r.created_at),
             "last_seen_at": iso(r.last_seen_at), "current": r.id == current} for r in rows]


async def revoke(db: AsyncSession, sid: str) -> bool:
    """退出一台（也可能是本机）。不存在或已退出 → False。"""
    n = (await db.execute(update(LoginSession).where(LoginSession.id == sid, LoginSession.revoked_at.is_(None))
                          .values(revoked_at=_now()))).rowcount
    await db.commit()
    if _snap is not None:
        _snap.alive.pop(sid, None)
    return bool(n)


async def revoke_others(db: AsyncSession, keep: str | None) -> int:
    """退出除 keep 之外的所有设备，并把 cutoff 设成现在（没 sid 的老 token 一起作废）。返回退出了几台（不含老 token）。"""
    now = _now()
    q = update(LoginSession).where(LoginSession.revoked_at.is_(None), LoginSession.created_at >= _expired_before())
    if keep:
        q = q.where(LoginSession.id != keep)
    n = (await db.execute(q.values(revoked_at=now))).rowcount
    # 过期但没标记的也一并标掉，免得快照里留着
    await db.execute(update(LoginSession).where(LoginSession.revoked_at.is_(None), LoginSession.id != (keep or ""))
                     .values(revoked_at=now))
    row = await db.scalar(select(OwnerSecurity).where(OwnerSecurity.id == 1))
    if row is None:
        row = OwnerSecurity(id=1, recovery=[], last_step=0, updated_at=now)
        db.add(row)
    row.sessions_cutoff = now
    await db.commit()
    forget()
    return int(n or 0)
