# 冒烟：OAuth 回调按发起端（web / app）回跳，错误信息转义，伪造 state 被拒。运行：python tests/smoke_oauth_return.py
import os, sys, asyncio
os.environ.update(DATABASE_URL="sqlite+aiosqlite:///:memory:", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, GOOGLE_CLIENT_ID="gid", GOOGLE_CLIENT_SECRET="gs",
  VAULT_KEY="")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from urllib.parse import urlparse, parse_qs
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routes import connectors as rc
from app.connectors import oauth
from app.db import get_session

app = FastAPI(); app.include_router(rc.public)
async def fake_db(): yield None
app.dependency_overrides[get_session] = fake_db
class C: id="google"
async def fake_complete(db, p, code):
    if code == "bad": raise RuntimeError("bad <x>")
    return C()
oauth.complete = fake_complete
c = TestClient(app)
from app.connectors.providers import PROVIDERS
g = PROVIDERS["google"]
for client in ("web", "app"):
    st = parse_qs(urlparse(oauth.authorize_url(g, client)).query)["state"][0]
    r = c.get("/api/oauth/callback", params={"state": st, "code": "ok"}, follow_redirects=False)
    if client == "web":
        assert r.status_code == 307 and r.headers["location"] == "/#/me/connectors?connected=google", r.headers
    else:
        assert r.status_code == 200 and 'myassistant://app/me/connectors?connected=google' in r.text, r.text
    r = c.get("/api/oauth/callback", params={"state": st, "code": "bad"}, follow_redirects=False)
    body = r.headers.get("location", "") + r.text
    assert "error=bad+%3Cx%3E" in body and "<x>" not in body, body
r = c.get("/api/oauth/callback", params={"state": "forged", "code": "x"}, follow_redirects=False)
assert "error=" in r.headers["location"]
try: oauth.authorize_url(g, "evil"); raise SystemExit("no guard")
except ValueError: pass
print("oauth smoke OK")
