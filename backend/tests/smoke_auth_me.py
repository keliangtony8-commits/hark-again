# 冒烟：GET /api/auth/me —— 带 token 返回主人用户名（“我的”页页头用）；不带 / 坏 token 401；登录错密码 401。
# 运行：python tests/smoke_auth_me.py
import os, sys, subprocess, tempfile
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="keliang", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi.testclient import TestClient
from app.main import app

with TestClient(app) as tc:
    assert tc.post("/api/auth/login", json={"username": "keliang", "password": "x"}).status_code == 401
    tok = tc.post("/api/auth/login", json={"username": "keliang", "password": "p"}).json()["token"]
    me = tc.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert me.status_code == 200 and me.json() == {"username": "keliang"}, me.text
    assert tc.get("/api/auth/me").status_code == 401
    assert tc.get("/api/auth/me", headers={"Authorization": "Bearer nope"}).status_code == 401
print("smoke_auth_me ok")
