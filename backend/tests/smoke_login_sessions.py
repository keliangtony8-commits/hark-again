# 冒烟：v2.61 登录设备（app/login_sessions.py + auth.py + routes/auth.py，不打真接口）。
# 设备名（device / UA 猜 / Dart）；登录开会话、token 带 sid；列表本机排第一 + current；退出一台立刻 401（REST、?token=、/ws）；
# 退出别的设备不影响本机；revoke-others：别的 sid 全退 + 老 token（无 sid）作废，本机是老 token 时换发新 token；
# 不认识的 sid（别的进程刚登录）强制重读后认；最近活动 TOUCH_S 节流；logout；过期/很久前退出的行被清；迁移 0059 往返。
# 运行：python tests/smoke_login_sessions.py
import os, sys, asyncio, subprocess, tempfile, time
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
alembic = lambda *a: subprocess.run([sys.executable, "-m", "alembic", *a], cwd=root, check=True, capture_output=True)
alembic("upgrade", "head")

from datetime import datetime, timedelta, timezone
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from app import login_sessions as ls
from app.auth import issue_token, require_query_token, require_user
from app.db import SessionLocal
from app.models import LoginSession
from app.routes import auth

# —— 设备名 ——
assert ls.label("Android App", None) == ("Android App", "app")
assert ls.label("  我的  平板 ", "x") == ("我的 平板", "other")
assert ls.label(None, "Dart/3.5 (dart:io)") == ("App", "app")
chrome_win = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
assert ls.label(None, chrome_win) == ("Chrome · Windows", "browser")
assert ls.label(None, chrome_win + " Edg/129.0")[0] == "Edge · Windows"
assert ls.label(None, "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit Version/17.0 Mobile Safari/604.1")[0] == "Safari · iPhone"
assert ls.label(None, "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0; rv:130.0) Gecko Firefox/130.0")[0] == "Firefox · Mac"
assert ls.label(None, "") == ("未知设备", "other") and ls.label(None, None)[0] == "未知设备"
assert len(ls.label("x" * 200, None)[0]) == ls.LABEL_MAX

# —— 接口 ——
app = FastAPI(); app.include_router(auth.router)

@app.get("/probe")
async def probe(user: str = Depends(require_user)):
    return {"u": user}

@app.get("/img", dependencies=[Depends(require_query_token)])
async def img():
    return {"ok": True}

c = TestClient(app)
def login(device=None, ua=chrome_win):
    r = c.post("/api/auth/login", json={"username": "u", "password": "p", **({"device": device} if device else {})},
               headers={"User-Agent": ua})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["token"]

phone, phone_t = login("Android App")
web, web_t = login()
pc, pc_t = login(ua="Mozilla/5.0 (X11; Linux x86_64) Firefox/130.0")
for h in (phone, web, pc):
    assert c.get("/probe", headers=h).status_code == 200

r = c.get("/api/auth/sessions", headers=web).json()["sessions"]
assert len(r) == 3 and r[0]["current"] and r[0]["label"] == "Chrome · Windows" and sum(s["current"] for s in r) == 1
assert {s["label"] for s in r} == {"Android App", "Chrome · Windows", "Firefox · Linux"}
assert all(s["created_at"] and s["last_seen_at"] for s in r)
phone_sid = next(s["id"] for s in r if s["label"] == "Android App")

# 退出手机：立刻 401（REST / ?token= / 列表），网页不受影响
d = c.delete(f"/api/auth/sessions/{phone_sid}", headers=web)
assert d.status_code == 200 and d.json()["current"] is False
assert c.get("/probe", headers=phone).status_code == 401
assert c.get("/probe", headers=phone).json()["detail"] == ls.SIGNED_OUT
assert c.get(f"/img?token={phone_t}").status_code == 401 and c.get(f"/img?token={web_t}").status_code == 200
assert c.get("/probe", headers=web).status_code == 200
assert c.delete(f"/api/auth/sessions/{phone_sid}", headers=web).status_code == 404  # 再退一次
assert len(c.get("/api/auth/sessions", headers=web).json()["sessions"]) == 2

# /ws 也认
from app.routes import ws as ws_route
wsapp = FastAPI(); wsapp.include_router(ws_route.router)
wc = TestClient(wsapp)
try:
    with wc.websocket_connect(f"/ws?token={phone_t}") as s:
        s.receive_json()
    raise AssertionError("revoked token opened ws")
except AssertionError:
    raise
except Exception:
    pass

# 不认识的 sid（另一个进程刚登录）：强制重读后认
async def insert_other():
    async with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        db.add(LoginSession(id="z" * 32, label="别的进程", kind="other", created_at=now, last_seen_at=now)); await db.commit()
asyncio.run(insert_other())
assert c.get("/probe", headers={"Authorization": f"Bearer {issue_token('z' * 32)}"}).status_code == 200
assert c.get("/probe", headers={"Authorization": f"Bearer {issue_token('nope')}"}).status_code == 401

# 最近活动节流：TOUCH_S 内不写库；超过才写
async def seen(sid):
    async with SessionLocal() as db:
        return (await db.get(LoginSession, sid)).last_seen_at
pc_sid = next(s["id"] for s in c.get("/api/auth/sessions", headers=pc).json()["sessions"] if s["current"])
before = asyncio.run(seen(pc_sid))
c.get("/probe", headers=pc); assert asyncio.run(seen(pc_sid)) == before
ls._snap.alive[pc_sid] -= ls.TOUCH_S + 1
c.get("/probe", headers=pc); assert asyncio.run(seen(pc_sid)) != before

# 老 token（无 sid）：没退出过所有设备前照常
legacy = {"Authorization": f"Bearer {issue_token()}"}
assert c.get("/probe", headers=legacy).status_code == 200

# 退出其他所有设备（从网页）：PC、别的进程那台、老 token 全作废，网页还在
r = c.post("/api/auth/sessions/revoke-others", headers=web).json()
assert r["signed_out"] == 2 and "token" not in r, r
assert c.get("/probe", headers=pc).status_code == 401 and c.get("/probe", headers=legacy).status_code == 401
assert c.get("/probe", headers=web).status_code == 200
assert [s["current"] for s in c.get("/api/auth/sessions", headers=web).json()["sessions"]] == [True]
time.sleep(1.1)
assert c.get("/probe", headers={"Authorization": f"Bearer {issue_token()}"}).status_code == 200  # cutoff 之后签的老式 token 照常

# 本机是老 token 时退出其他：换发新 token，旧的作废
legacy2 = {"Authorization": f"Bearer {issue_token()}"}
r = c.post("/api/auth/sessions/revoke-others", headers=legacy2).json()
assert r["signed_out"] == 1 and r["token"]
assert c.get("/probe", headers=legacy2).status_code == 401 and c.get("/probe", headers=web).status_code == 401
fresh = {"Authorization": f"Bearer {r['token']}"}
assert c.get("/probe", headers=fresh).status_code == 200

# 本机退出登录
assert c.post("/api/auth/logout", headers=fresh).json()["ok"]
assert c.get("/probe", headers=fresh).status_code == 401

# 别的进程退了一台：本进程最多 RELOAD_S 秒后知道（这里直接让快照过期）
a, _ = login("A App")
async def revoke_direct():
    async with SessionLocal() as db:
        await db.execute(update(LoginSession).values(revoked_at=datetime.now(timezone.utc))); await db.commit()
asyncio.run(revoke_direct())
assert c.get("/probe", headers=a).status_code == 200  # 快照还没过期
ls._snap.at -= ls.RELOAD_S + 1
assert c.get("/probe", headers=a).status_code == 401

# 清理：很久前退出的行被删，过期的不列
b, _ = login("B App")
async def age():
    async with SessionLocal() as db:
        old = datetime.now(timezone.utc) - timedelta(days=ls.KEEP_DAYS + 1)
        await db.execute(update(LoginSession).where(LoginSession.revoked_at.is_not(None)).values(revoked_at=old)); await db.commit()
        return len((await db.scalars(select(LoginSession))).all())
n_before = asyncio.run(age())
assert len(c.get("/api/auth/sessions", headers=b).json()["sessions"]) == 1
async def count():
    async with SessionLocal() as db:
        return len((await db.scalars(select(LoginSession))).all())
assert asyncio.run(count()) == 1 < n_before

# 迁移往返
alembic("downgrade", "0058"); alembic("upgrade", "head")
print("smoke_login_sessions OK")
