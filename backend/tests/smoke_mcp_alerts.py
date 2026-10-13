# 冒烟：v0.97 MCP 服务器连不上 / 令牌被拒 → 主页“需要你亲自处理”提醒（app/connectors/mcp.py guarded + system_alerts 主体）。
# 模拟模型 + 假 MCP 服务器（httpx MockTransport），迁移 0023（home_cards.alert_subject）。
# - 模型调 mcp_tools，服务器连不上 → 工具结果“已经在主页放了提醒…别再重试”，Home 一张卡：target connectors、无 prompt、主体 mcp:<id>；
# - 再连不上 → 不重复；GET /api/connectors/mcp 这一行 problem=down；打开工具列表 → 502；
# - 同在连接器页的 GitHub 失效卡（主体 connector:github）不受 MCP 恢复影响；
# - 服务器恢复（mcp_call 成功）→ 卡收起、problem=null；之后再坏 → 再提醒一次（去重键已清）；
# - 401 → “令牌被拒绝”卡（顶掉同主体旧卡）；工具自己报错（JSON-RPC error）不算不通；删除服务器 → 收起；
# - 预算两档：新的一档顶掉旧的（主体 budget），迁移把老卡按去处补上主体。
# 运行：python tests/smoke_mcp_alerts.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
from cryptography.fernet import Fernet
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY=Fernet.generate_key().decode(), DATA_DIR=tmp,
  TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
# 先停在 0022 放一张老的系统卡，验证 0023 的回填
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "0022"], cwd=root, check=True, capture_output=True)
import sqlite3
con = sqlite3.connect(f"{tmp}/t.db")
con.execute("INSERT INTO home_cards (id, kind, title, blocks, dismissed, unread, target, created_at, updated_at) "
            "VALUES ('old1', 'action', '预算 50%', '[]', 0, 1, 'usage', '2026-10-01', '2026-10-01')")
con.commit(); con.close()
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import llm, system_alerts
from app.agent import runner
from app.agent.tools import load_builtin
from app.auth import require_user
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, HomeCard, McpServer, Message
from app.routes import connectors as rconn
from app.routes.resources import routers

script: list = []
tool_results: list = []

def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)

async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    tool_results.extend(m["content"] for m in messages if isinstance(m, dict) and m.get("role") == "tool"
                        and m["content"] not in tool_results)
    step = script.pop(0)
    async def gen():
        if isinstance(step, tuple):
            yield chunk(tool=[NS(index=0, id=f"c{len(script)}", function=NS(name=step[0], arguments=json.dumps(step[1])))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()

app = FastAPI()
for r in [*routers, rconn.router]:
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)

# ---- 假 MCP 服务器 ----
mode = {"m": "down"}
def handler(req: httpx.Request):
    m = mode["m"]
    if m == "down":
        raise httpx.ConnectError("refused", request=req)
    if m == "auth":
        return httpx.Response(401, json={"error": "bad token"})
    body = json.loads(req.content or b"{}")
    meth = body.get("method")
    if meth == "initialize":
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
    if meth == "notifications/initialized":
        return httpx.Response(202)
    if meth == "tools/list":
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"tools": [
            {"name": "search", "description": "搜笔记", "annotations": {"readOnlyHint": True}}]}})
    if m == "toolerr":
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "error": {"message": "参数不对"}})
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"content": [{"type": "text", "text": "找到 3 条"}]}})
real_client = httpx.AsyncClient
httpx.AsyncClient = lambda **kw: real_client(**{**kw, "transport": httpx.MockTransport(handler)})

async def seed():
    async with SessionLocal() as db:
        s = McpServer(name="notes", url="https://mcp.example.com/mcp"); db.add(s)
        # 同去处的另一件事：GitHub 失效卡
        await system_alerts.post(db, subject="connector:github", once="fp", title="GitHub 连接已失效", text="x", open="connectors")
        await db.commit()
        return s.id
sid = asyncio.run(seed())

async def turn(text, *steps):
    script.extend(steps)
    async with SessionLocal() as db:
        conv = Conversation(title="笔记"); db.add(conv); await db.commit()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks(text))); await db.commit()
        await runner.run_turn(db, conv)

def mcp_cards():
    return [x for x in c.get("/api/cards").json() if x["kind"] == "action" and not x["dismissed"] and x["title"].startswith("MCP")]
def titles():
    return sorted(x["title"] for x in c.get("/api/cards").json() if x["kind"] == "action" and not x["dismissed"])
def problem():
    return c.get("/api/connectors/mcp").json()[0]["problem"]

# 0) 迁移回填：老的用量卡主体 = budget
async def subj(cid):
    async with SessionLocal() as db:
        return (await db.get(HomeCard, cid)).alert_subject
assert asyncio.run(subj("old1")) == "budget"

# 1) 连不上 → 提醒
LIST = ("mcp_tools", {"server": "notes"})
asyncio.run(turn("查查笔记", LIST, "笔记服务器连不上。"))
assert "连不上服务器" in tool_results[-1] and "已经在主页放了提醒" in tool_results[-1], tool_results[-1]
k = mcp_cards()
assert len(k) == 1 and k[0]["title"] == "MCP「notes」连不上" and k[0]["target"] == "connectors" and k[0]["action_prompt"] is None, k
assert "mcp.example.com" in k[0]["blocks"][0]["text"]
assert problem() == "down"

# 2) 再连不上 → 不重复；打开工具列表 → 502
asyncio.run(turn("再查", LIST, "还是不行。"))
assert len(mcp_cards()) == 1
r = c.get(f"/api/connectors/mcp/{sid}/tools")
assert r.status_code == 502 and "连不上" in r.json()["detail"], r.text
assert len(mcp_cards()) == 1

# 3) 恢复（mcp_call 成功）→ 收起；GitHub 卡不动
mode["m"] = "ok"
asyncio.run(turn("搜一下", LIST, ("mcp_call", {"server": "notes", "tool": "search", "arguments": {"q": "a"}}), "找到 3 条。"))
assert "找到 3 条" in tool_results[-1], tool_results
assert mcp_cards() == [] and problem() is None
assert "GitHub 连接已失效" in titles()

# 4) 再坏 → 再提醒一次（去重键已清）
mode["m"] = "down"
asyncio.run(turn("查查", LIST, "又连不上了。"))
assert len(mcp_cards()) == 1

# 5) 401 → 令牌被拒绝，顶掉同主体的“连不上”
mode["m"] = "auth"
r = c.get(f"/api/connectors/mcp/{sid}/tools")
assert r.status_code == 502 and "令牌被拒绝" in r.json()["detail"]
k = mcp_cards()
assert [x["title"] for x in k] == ["MCP「notes」令牌被拒绝"] and "新的令牌" in k[0]["blocks"][0]["text"], k
assert problem() == "auth"

# 6) 工具自己报错 ≠ 不通：恢复后 JSON-RPC error 不发卡，且卡收起（服务器通了）
mode["m"] = "toolerr"
asyncio.run(turn("搜", ("mcp_call", {"server": "notes", "tool": "search", "arguments": {}}), "工具报错了。"))
assert "工具报错：参数不对" in tool_results[-1], tool_results[-1]
assert mcp_cards() == [] and problem() is None

# 7) 删除服务器 → 收起
mode["m"] = "down"
asyncio.run(turn("查", LIST, "连不上。"))
assert len(mcp_cards()) == 1
assert c.delete(f"/api/connectors/mcp/{sid}").json()["ok"]
assert mcp_cards() == [] and c.get("/api/connectors/mcp").json() == []
assert "GitHub 连接已失效" in titles()

# 8) 预算：新档顶掉旧档（同主体 budget），不碰别的主体
async def budget():
    async with SessionLocal() as db:
        await system_alerts.post(db, subject="budget", once="2026-10:80:30", title="预算 80%", text="x", open="usage", prompt="看看")
        await db.commit()
asyncio.run(budget())
t = titles()
assert "预算 80%" in t and "预算 50%" not in t and "GitHub 连接已失效" in t, t
print("smoke_mcp_alerts ok")
