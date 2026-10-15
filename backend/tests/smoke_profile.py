# 冒烟：v2.92 §P 个人资料（app/identity.py + routes/profile.py，取代 GET /api/auth/me）
# 称呼 / 助手名的读改清、头像上传下载删除、首次问候只建一次、问候引导句只在问候对话里且答过就停、系统提示第一句跟着助手名变、set_names 工具。
# 运行：python tests/smoke_profile.py
import asyncio, os, sys, subprocess, tempfile
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{os.path.join(tmp, 't.db')}", DATA_DIR=os.path.join(tmp, "data"), LLM_BASE_URL="http://x",
                  LITELLM_MASTER_KEY="k", OWNER_USERNAME="keliang", OWNER_PASSWORD="p", JWT_SECRET="s" * 32, VAULT_KEY="")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi.testclient import TestClient
from app import identity
from app.agent.context import build_system_prompt
from app.db import SessionLocal
from app.main import app

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64

with TestClient(app) as tc:
    tok = tc.post("/api/auth/login", json={"username": "keliang", "password": "p"}).json()["token"]
    H = {"Authorization": f"Bearer {tok}"}
    assert tc.get("/api/profile").status_code == 401
    assert tc.get("/api/auth/me", headers=H).status_code in (404, 405), "旧接口应已删除"

    p = tc.get("/api/profile", headers=H).json()
    assert p == {"username": "keliang", "display_name": None, "assistant_name": None, "assistant_default": "Toyuis",
                 "avatar": None, "greet": True}, p

    # 首次问候：建一段对话、第一条是固定的助手消息；再调不重复建
    cid = tc.post("/api/profile/greet", headers=H).json()["conversation_id"]
    assert cid
    conv = tc.get(f"/api/conversations/{cid}", headers=H).json()
    msgs = conv["messages"] if isinstance(conv, dict) and "messages" in conv else conv
    first = msgs[0]
    assert first["role"] == "assistant" and "请问我该如何称呼你" in str(first["blocks"]) and "Toyuis" in str(first["blocks"]), first
    assert tc.post("/api/profile/greet", headers=H).json() == {"conversation_id": None}
    assert tc.get("/api/profile", headers=H).json()["greet"] is False

    async def checks_before():
        async with SessionLocal() as db:
            assert identity.ONBOARD_LINE == await identity.onboarding_line(db, cid)
            assert await identity.onboarding_line(db, "other") == ""
            sp = (await build_system_prompt(db, None, "")).text()
            assert sp.startswith("你是 Toyuis，用户的私人助手。"), sp[:60]
    asyncio.run(checks_before())

    # 改名字：只改传了的；太长 422；助手名写回产品名 = 没取名
    p = tc.patch("/api/profile", headers=H, json={"display_name": " Tony "}).json()
    assert p["display_name"] == "Tony" and p["assistant_name"] is None
    assert tc.patch("/api/profile", headers=H, json={"assistant_name": "x" * 21}).status_code == 422
    p = tc.patch("/api/profile", headers=H, json={"assistant_name": "小克"}).json()
    assert p["display_name"] == "Tony" and p["assistant_name"] == "小克"

    async def checks_after():
        async with SessionLocal() as db:
            assert await identity.onboarding_line(db, cid) == "", "答过就不再提醒"
            sp = (await build_system_prompt(db, None, "")).text()
            assert sp.startswith("你是 小克，用户的私人助手。") and "“Tony”" in sp, sp[:120]
            assert "Toyuis" in identity.greeting(await identity.get(db)) or "小克" in identity.greeting(await identity.get(db))
    asyncio.run(checks_after())
    assert tc.patch("/api/profile", headers=H, json={"assistant_name": "Toyuis"}).json()["assistant_name"] is None
    assert tc.patch("/api/profile", headers=H, json={"display_name": None}).json()["display_name"] is None

    # 头像：类型 / 大小校验，上传后地址带版本，?token= 能取，删掉 404
    assert tc.post("/api/profile/avatar", headers=H, files={"file": ("a.gif", b"GIF89a", "image/gif")}).status_code == 422
    big = PNG + b"0" * identity.AVATAR_MAX
    assert tc.post("/api/profile/avatar", headers=H, files={"file": ("a.png", big, "image/png")}).status_code == 422
    url = tc.post("/api/profile/avatar", headers=H, files={"file": ("a.bin", PNG, "application/octet-stream")}).json()["avatar"]
    assert url and url.startswith("/api/profile/avatar/"), url
    assert tc.get(url).status_code == 401
    r = tc.get(url, params={"token": tok})
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
    assert tc.delete("/api/profile/avatar", headers=H).json()["avatar"] is None
    assert tc.get(url, params={"token": tok}).status_code == 404

# set_names 工具（模型在问候对话里调）
from app.agent.tools import REGISTRY, ToolContext


async def tool_check():
    t = REGISTRY["set_names"]
    assert t.deferred
    async with SessionLocal() as db:
        ctx = ToolContext(db=db)
        r = await t.run(ctx, display_name="阿亮")
        assert not r.failed and "阿亮" in r.content, r.content
        r = await t.run(ctx)
        assert r.failed
        r = await t.run(ctx, assistant_name="一句很长很长很长很长很长很长很长很长的话不像名字")
        assert r.failed
        assert (await identity.get(db)).display_name == "阿亮"
asyncio.run(tool_check())
print("smoke_profile ok")
