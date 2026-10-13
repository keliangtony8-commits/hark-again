# 冒烟：v2.58 两步验证（app/two_factor.py + routes/auth.py，不打真接口）。
# RFC 6238 测试向量（SHA1，秘钥 "12345678901234567890"）；前后 1 步容差、同一步不认两次；全角数字/空格；
# setup → 待确认不影响登录 → enable 错码 400 / 对码返回 8 个恢复码 → 登录没码 428、错码 401、对码 200；
# 恢复码登录一次作废 + recovery_left；试错 5 次 → 429；关闭要密码 + 码；重新生成恢复码旧的作废；
# 已开再 setup 409；数据库里没有明文秘钥/恢复码；JWT_SECRET 换了 → 当没开；--reset 命令；迁移 0058 往返。
# 运行：python tests/smoke_two_factor.py
import os, sys, asyncio, base64, subprocess, tempfile, time
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
alembic = lambda *a: subprocess.run([sys.executable, "-m", "alembic", *a], cwd=root, check=True, capture_output=True)
alembic("upgrade", "head")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import two_factor as tf
from app.auth import issue_token
from app.db import SessionLocal
from app.models import OwnerSecurity
from app.routes import auth

# —— 规则：RFC 6238 附录 B（8 位向量取后 6 位） ——
rfc = base64.b32encode(b"12345678901234567890").decode()
for t, want in [(59, "94287082"), (1111111109, "07081804"), (1234567890, "89005924"), (2000000000, "69279037")]:
    assert tf.code_at(rfc, t // 30) == want[-6:], (t, tf.code_at(rfc, t // 30))
now = 1234567890.0
c0 = tf.code_at(rfc, tf.step_of(now))
assert tf.match_step(rfc, c0, 0, now) == tf.step_of(now)
assert tf.match_step(rfc, tf.code_at(rfc, tf.step_of(now) - 1), 0, now) == tf.step_of(now) - 1  # 慢一步
assert tf.match_step(rfc, tf.code_at(rfc, tf.step_of(now) + 1), 0, now) is not None             # 快一步
assert tf.match_step(rfc, tf.code_at(rfc, tf.step_of(now) - 2), 0, now) is None                 # 太旧
assert tf.match_step(rfc, c0, tf.step_of(now), now) is None                                     # 重放
full = c0.translate(str.maketrans("0123456789", "０１２３４５６７８９"))
assert tf.match_step(rfc, f" {full[:3]} {full[3:]} ", 0, now) is not None                       # 全角 + 空格
assert tf.match_step(rfc, "12345", 0, now) is None and tf.match_step(rfc, "abcdef", 0, now) is None
s = tf.new_secret(); assert len(s) == 32 and tf.code_at(s, 1).isdigit()
assert tf.group("ABCDEFGHIJ") == "ABCD EFGH IJ"
u = tf.uri("ABC", "u"); assert u.startswith("otpauth://totp/") and "secret=ABC" in u and "period=30" in u
rows = tf.qr_rows(u); assert len(rows) >= 21 and all(len(r) == len(rows) for r in rows) and set("".join(rows)) <= {"0", "1"}
codes = tf.new_recovery_codes(); assert len(codes) == 8 == len(set(codes)) and all(len(c) == 9 and c[4] == "-" for c in codes)
assert tf.hash_recovery("ABCD-EFGH") == tf.hash_recovery("abcd efgh")
th = tf.Throttle(3, 10)
for i in range(3): th.fail(i)
assert th.blocked(3) and not th.blocked(20)

# —— 接口 ——
app = FastAPI(); app.include_router(auth.router)
c = TestClient(app)
H = {"Authorization": f"Bearer {issue_token()}"}
login = lambda **kw: c.post("/api/auth/login", json={"username": "u", "password": "p", **kw})

def secret_now():
    async def go():
        async with SessionLocal() as db:
            row = await db.get(OwnerSecurity, 1)
            return tf._open(row.secret or row.pending), row
    return asyncio.run(go())

def fresh_code(after_step=None):
    sec, row = secret_now()
    st = tf.step_of()
    last = row.last_step or 0
    for step in (st, st + 1):
        if step > last and (after_step is None or step > after_step):
            return tf.code_at(sec, step)
    raise AssertionError("no fresh step")

assert c.get("/api/auth/2fa").status_code in (401, 403)
assert c.get("/api/auth/2fa", headers=H).json() == {"enabled": False, "enabled_at": None, "recovery_left": 0, "pending": False}
assert login().status_code == 200
r = c.post("/api/auth/2fa/setup", headers=H).json()
assert r["account"] == "u" and r["uri"].startswith("otpauth://") and r["qr"] and " " in r["secret"]
assert c.get("/api/auth/2fa", headers=H).json()["pending"] is True
assert login().status_code == 200                                  # 待确认：登录照旧
assert c.post("/api/auth/2fa/enable", headers=H, json={"code": "000000" if fresh_code() != "000000" else "111111"}).status_code == 400
tf.throttle.reset()
r = c.post("/api/auth/2fa/enable", headers=H, json={"code": fresh_code()})
assert r.status_code == 200, r.text
rec = r.json()["recovery_codes"]; assert len(rec) == 8 and r.json()["enabled"] and r.json()["recovery_left"] == 8
assert c.post("/api/auth/2fa/setup", headers=H).status_code == 409

# 存的不是明文
async def raw():
    async with SessionLocal() as db:
        row = await db.get(OwnerSecurity, 1)
        return row.secret, row.recovery
sec_db, rec_db = asyncio.run(raw())
assert secret_now()[0].replace(" ", "") not in sec_db and not any(x in str(rec_db) for x in rec)

# 登录
r = login(); assert r.status_code == 428 and r.json()["detail"] == tf.REQUIRED
r = login(code="12"); assert r.status_code == 401
r = login(password="bad", code=fresh_code()); assert r.status_code == 401 and "密码" in r.json()["detail"]
tf.throttle.reset()
time.sleep(0)  # 同一步的码 enable 已用过 → 等下一步不现实，取下一步（容差 +1）
code = fresh_code()
r = login(code=code)
if r.status_code == 401:  # enable 用的是当前步 → 用 +1 步
    sec, _ = secret_now(); code = tf.code_at(sec, tf.step_of() + 1); r = login(code=code)
assert r.status_code == 200 and "token" in r.json() and "recovery_left" not in r.json(), r.text
assert login(code=code).status_code == 401                         # 同一个码不认第二次
tf.throttle.reset()
r = login(code=rec[0].upper()); assert r.status_code == 200 and r.json()["recovery_left"] == 7
assert login(code=rec[0]).status_code == 401                        # 恢复码作废
assert c.get("/api/auth/2fa", headers=H).json()["recovery_left"] == 7
tf.throttle.reset()
for _ in range(5): login(code="999999" if code != "999999" else "888888")
r = login(code=rec[1]); assert r.status_code == 429 and r.json()["detail"] == tf.THROTTLED
tf.throttle.reset()

# 重新生成恢复码：要密码 + 码
assert c.post("/api/auth/2fa/recovery", headers=H, json={"password": "x", "code": rec[1]}).status_code == 403
tf.throttle.reset()
r = c.post("/api/auth/2fa/recovery", headers=H, json={"password": "p", "code": rec[1]})
assert r.status_code == 200 and r.json()["recovery_left"] == 8
rec2 = r.json()["recovery_codes"]; assert not set(rec2) & set(rec)
assert login(code=rec[2]).status_code == 401
tf.throttle.reset()

# 关闭：错码不关
assert c.post("/api/auth/2fa/disable", headers=H, json={"password": "p", "code": "abcd-efgh"}).status_code == 403
assert c.get("/api/auth/2fa", headers=H).json()["enabled"]
tf.throttle.reset()
r = c.post("/api/auth/2fa/disable", headers=H, json={"password": "p", "code": rec2[0]})
assert r.status_code == 200 and r.json()["enabled"] is False
assert login().status_code == 200
assert c.post("/api/auth/2fa/disable", headers=H, json={"password": "p", "code": ""}).status_code == 200  # 没开 → 幂等

# JWT_SECRET 换了 → 解不开 → 当没开
c.post("/api/auth/2fa/setup", headers=H)
assert c.post("/api/auth/2fa/enable", headers=H, json={"code": fresh_code()}).status_code == 200
assert login().status_code == 428
old = tf.settings.jwt_secret
tf.settings.jwt_secret = "t" * 32
assert login().status_code == 200
tf.settings.jwt_secret = old
assert login().status_code == 428

# 命令行救急
env = dict(os.environ)
out = subprocess.run([sys.executable, "-m", "app.two_factor", "--reset"], cwd=root, env=env, capture_output=True, text=True)
assert out.returncode == 0 and "已关闭" in out.stdout, out.stderr
assert login().status_code == 200

# 迁移往返
alembic("downgrade", "0057")
alembic("upgrade", "head")
print("smoke_two_factor OK")
