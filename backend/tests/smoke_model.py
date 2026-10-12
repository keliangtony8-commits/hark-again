# 冒烟：每个对话选模型（快速 / 深度）。模拟模型（不打真接口），只看实际调用的别名：
# 新对话带 model → 记到对话、本轮就用它；之后不带 → 沿用；"" → 回默认；不认识的别名忽略；
# 重新生成带 model = 换模型重答；PATCH 改模型（非法 422、"" 清空、不改 updated_at）；列表/详情带 model；
# GET /api/catalog/models；配置里删掉某别名后老对话回落到默认。
# 运行：python tests/smoke_model.py
import os, sys, asyncio, subprocess, tempfile, json
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="",
  CHAT_MODELS=json.dumps({"fast": "快速", "smart": "深度"}), DEFAULT_MODEL="fast")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.agent import loop
from app.auth import issue_token, require_user
from app.config import settings
from app.db import SessionLocal
from app.llm import Turn
from app.models import Conversation
from app.routes import catalog as rcat, conversations as rc, ws as rws

used: list[str | None] = []

async def fake_stream_turn(messages, tools=None, model=None, effort=None):
    used.append(model)
    yield "好"
    yield Turn(text="好")
loop.stream_turn = fake_stream_turn

app = FastAPI()
for r in (rws.router, rc.router, rcat.router):
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
token = issue_token()

def turn(ws, event):
    ws.send_json(event)
    out = []
    while True:
        e = ws.receive_json(); out.append(e)
        if e["type"] in ("message.done", "error"):
            return out

async def conv_model(cid):
    async with SessionLocal() as db:
        return (await db.get(Conversation, cid)).model

assert c.get("/api/catalog/models").json() == {
    "default": "fast", "models": [{"id": "fast", "label": "快速"}, {"id": "smart", "label": "深度"}]}

with c.websocket_connect(f"/ws?token={token}") as ws:
    ev = turn(ws, {"type": "user.message", "text": "难题", "model": "smart"})
    cid = ev[0]["conversation_id"]
    assert used[-1] == "smart" and asyncio.run(conv_model(cid)) == "smart", used
    turn(ws, {"type": "user.message", "text": "接着", "conversation_id": cid})            # 不带 = 沿用
    assert used[-1] == "smart"
    turn(ws, {"type": "user.message", "text": "x", "conversation_id": cid, "model": "gpt-99"})  # 不认识：忽略
    assert used[-1] == "smart" and asyncio.run(conv_model(cid)) == "smart"
    turn(ws, {"type": "user.message", "text": "简单", "conversation_id": cid, "model": ""})     # 回默认
    assert used[-1] == "fast" and asyncio.run(conv_model(cid)) is None
    last = turn(ws, {"type": "user.message", "text": "再来", "conversation_id": cid})[-1]["message"]["id"]
    assert used[-1] == "fast"
    turn(ws, {"type": "message.regenerate", "conversation_id": cid, "message_id": last, "model": "smart"})
    assert used[-1] == "smart" and asyncio.run(conv_model(cid)) == "smart"           # 换模型重答，之后沿用
    ev = turn(ws, {"type": "user.message", "text": "新对话不选"})
    assert used[-1] == "fast" and asyncio.run(conv_model(ev[0]["conversation_id"])) is None

# REST：列表/详情带 model；PATCH 改模型
lst = {x["id"]: x for x in c.get("/api/conversations").json()}
assert lst[cid]["model"] == "smart", lst[cid]
before = lst[cid]["updated_at"]
assert c.patch(f"/api/conversations/{cid}", json={"model": "nope"}).status_code == 422
r = c.patch(f"/api/conversations/{cid}", json={"model": ""}).json()
assert r["model"] is None and r["updated_at"] == before, r
r = c.patch(f"/api/conversations/{cid}", json={"model": "smart"}).json()
assert r["model"] == "smart" and c.get(f"/api/conversations/{cid}").json()["model"] == "smart"
assert c.patch(f"/api/conversations/{cid}", json={"title": "改名"}).json()["model"] == "smart"  # 不带 model 不动它

# 配置里删掉 smart：老对话回落到默认，不报错
settings.chat_models = {"fast": "快速"}
with c.websocket_connect(f"/ws?token={token}") as ws:
    turn(ws, {"type": "user.message", "text": "还在吗", "conversation_id": cid})
    assert used[-1] == "fast", used
print("smoke_model OK")
