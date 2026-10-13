# 冒烟：v2.49 BRAIN (be) mcp_servers——app/mcp_servers.py 唯一登记规则 + 工具 + 连接器页接口共用。模拟模型，无迁移。
# 1) 规则：check_url / suggest_name / clean_name / same_url / find（精确 → 不分大小写 → 地址）；
# 2) add：连得上才存；重名 / 重复地址（末尾 / 不算）→ dupe 不存；要令牌 → auth；连不上 / 回的不是 MCP → down；
#    助手加内网地址（169.254.169.254、localhost）→ blocked，用户自己从接口加 → 放过；令牌加密存、不进返回文字；
#    卡在 needs_connector:<名字> 的定时任务立即重跑；
# 3) 工具：list（无网络，带令牌 / 问题状态）；add 无令牌被拒 → 提示 needs_token；needs_token → 表单卡 purpose=token，
#    令牌不进卡、不进历史；无人值守 + needs_token → 不弹卡；remove 要审批（拒绝 → 还在；批准 → 删掉且提醒收起）；
# 4) 一轮（经 deferred_tool call）：add 401 → 再带 needs_token → 卡 → 填令牌 → 加好，回复里表单卡 submitted、历史没有令牌；
# 5) 接口 POST /api/connectors/mcp 重名 → 409（以前是数据库唯一约束 500）。
# 运行：python tests/smoke_mcp_servers.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
from cryptography.fernet import Fernet
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY=Fernet.generate_key().decode(), DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', OUTBOUND_ALLOW_HOSTS="")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

import httpx
from sqlalchemy import select
from app import llm, mcp_servers as MS, system_alerts, vault, web_guard
from app.agent.approvals import FormReply
from app.agent.runner import run_turn
from app.agent.tools import REGISTRY, ToolContext, load_builtin, nobody
from app.blocks import blocks_to_text, text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, McpServer, Message, ScheduledTask

TOKEN = "tok-SECRET-9876"

# ---- 假 MCP 服务器：host 决定行为 ----
def handler(req: httpx.Request):
    host = req.url.host
    if host == "down.example.com":
        raise httpx.ConnectError("refused", request=req)
    if host == "html.example.com":
        return httpx.Response(200, text="<html>hi</html>", headers={"content-type": "text/html"})
    if host == "auth.example.com" and req.headers.get("authorization") != f"Bearer {TOKEN}":
        return httpx.Response(401, json={"error": "bad token"})
    body = json.loads(req.content or b"{}")
    meth = body.get("method")
    if meth == "initialize":
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
    if meth == "notifications/initialized":
        return httpx.Response(202)
    if meth == "tools/list":
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"tools": [
            {"name": f"t{i}", "description": "x"} for i in range(25 if host == "many.example.com" else 2)]}})
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"content": [{"type": "text", "text": "ok"}]}})
real_client = httpx.AsyncClient
httpx.AsyncClient = lambda **kw: real_client(**{**kw, "transport": httpx.MockTransport(handler)})

async def fake_resolve(host):
    return {"evil.example.com": ["10.0.0.5"]}.get(host, ["93.184.216.34"])
web_guard.resolve = fake_resolve

# ---- 1) 规则 ----
assert MS.suggest_name("https://mcp.notion.com/mcp") == "notion"
assert MS.suggest_name("https://api.example.co.uk/mcp") == "example"
assert MS.suggest_name("https://github.com/x") == "github"
assert MS.suggest_name("http://127.0.0.1:9000/mcp") == "127.0.0.1"
assert MS.clean_name("  my   notes ", "https://a.com") == "my notes" and MS.clean_name("", "https://mcp.linear.app/sse") == "linear"
for bad in ("ftp://x", "mcp.example.com", "", "https://" + "a" * 600, "https:///mcp"):
    try:
        MS.check_url(bad); raise AssertionError(bad)
    except MS.AddError as e:
        assert e.kind == "url", bad
try:
    MS.clean_name("x" * 61, "https://a.com"); raise AssertionError
except MS.AddError as e:
    assert e.kind == "name"
assert MS.same_url("https://a.com/mcp/", "HTTPS://A.com/mcp")

load_builtin()
t = REGISTRY["mcp_servers"]
assert t.deferred and t.form and t.risk
assert t.risk({"action": "remove", "name": "notes"}).startswith("删除 MCP 服务器「notes」") and t.risk({"action": "add"}) is None

async def asker(_id, _block):
    return FormReply(values={"token": TOKEN})

async def rules():
    async with SessionLocal() as db:
        # 卡在 needs_connector:notes 的任务
        db.add(ScheduledTask(name="每天整理笔记", prompt="整理", cron="0 9 * * *", wall="needs_connector:notes"))
        await db.commit()
        a = await MS.add(db, "notes", "https://ok.example.com/mcp", by="agent")
        assert a.tools == ["t0", "t1"] and a.server.token_ciphertext is None
        assert a.retried and "每天整理笔记" in a.retried, a.retried
        txt = MS.added_text(a)
        assert "已添加 MCP 服务器「notes」" in txt and "t0、t1" in txt and "已重新运行" in txt
        task = await db.scalar(select(ScheduledTask))
        assert task.run_requested, "卡住的任务该排一次立即运行"
        for name, url, kind in [("Notes", "https://other.example.com/mcp", "dupe"),     # 重名不分大小写
                                ("n2", "https://ok.example.com/mcp/", "dupe"),          # 同地址
                                ("d", "https://down.example.com/mcp", "down"),
                                ("h", "https://html.example.com/mcp", "down"),
                                ("a", "https://auth.example.com/mcp", "auth"),
                                ("m", "http://169.254.169.254/latest", "blocked"),
                                ("l", "http://localhost:8000/mcp", "blocked"),
                                ("e", "https://evil.example.com/mcp", "blocked")]:
            try:
                await MS.add(db, name, url, by="agent"); raise AssertionError(name)
            except MS.AddError as e:
                assert e.kind == kind, (name, e.kind, str(e))
                if kind == "dupe":
                    assert e.existing == "notes"
        assert len(await MS.all_servers(db)) == 1, "失败的一个都不能存"
        # 用户自己从设置里加内网的：放过（这里假服务器回 tools 就算通）
        lan = await MS.add(db, "nas", "http://192.168.1.10:9000/mcp", by="user")
        assert lan.server.name == "nas"
        # 带令牌：加密存，文字里没有令牌
        au = await MS.add(db, "", "https://auth.example.com/mcp", TOKEN, by="agent")
        assert au.server.name == "example" and vault.decrypt(au.server.token_ciphertext) == TOKEN
        assert TOKEN not in MS.added_text(au) and "已在卡上填好令牌并验证通过" in MS.added_text(au)
        many = await MS.add(db, "many", "https://many.example.com/mcp", by="agent")
        assert "等 25 个" in MS.added_text(many) and "t24" not in MS.added_text(many)
        assert (await MS.find(db, "NOTES")).name == "notes" and (await MS.find(db, "https://ok.example.com/mcp/")).name == "notes"
        assert await MS.find(db, "") is None and await MS.find(db, "zzz") is None
        # listing：不联网；有提醒的显示问题
        s = await MS.find(db, "nas")
        await system_alerts.post(db, subject=f"mcp:{s.id}", once="down", title="x", text="y", open="connectors"); await db.commit()
        lst = await MS.listing(db)
        assert "- notes：ok.example.com，无令牌，正常" in lst and "- nas：192.168.1.10，无令牌，上次连不上" in lst and "- example：auth.example.com，有令牌" in lst, lst
        assert TOKEN not in lst

        # ---- 3) 工具 ----
        ctx = ToolContext(db=db, ask=asker, conversation_id="c1")
        assert (await t.run(ctx, action="list")).content == lst
        assert (await t.run(ctx, action="nuke")).failed == "参数不对"
        res = await t.run(ctx, action="add")
        assert res.failed == "没填地址" and "别自己编" in res.content
        res = await t.run(ctx, action="add", name="a2", url="https://auth.example.com/v2/mcp")
        assert res.failed == "要令牌" and "needs_token=true" in res.content
        res = await t.run(ctx, action="add", name="notes", url="https://x.example.com/mcp")
        assert not res.failed and "已经有一台叫「notes」" in res.content
        res = await t.run(ctx, action="add", url="http://169.254.169.254/")
        assert res.failed == "内网地址" and "亲手添加" in res.content
        # 表单：只有 add + needs_token + 有人才弹
        card = await t.form(ctx, {"action": "add", "url": "https://auth.example.com/v3/mcp", "needs_token": True, "reason": "在设置 → API 里生成"})
        assert card["purpose"] == "token" and card["site"] == "auth.example.com" and card["note"] == "在设置 → API 里生成"
        assert card["fields"][0]["kind"] == "password" and "value" not in card["fields"][0]
        assert await t.form(ctx, {"action": "add", "url": "https://a.com", "needs_token": False}) is None
        assert await t.form(ToolContext(db=db, ask=nobody), {"action": "add", "url": "https://a.com", "needs_token": True}) is None
        assert await t.form(ctx, {"action": "add", "url": "bad", "needs_token": True}) is None
        res = await t.run(ToolContext(db=db, ask=nobody), action="add", url="https://auth.example.com/v4/mcp", needs_token=True)
        assert res.failed == "没人能填令牌" and "连接器" in res.content
        res = await t.run(ctx, action="add", name="a3", url="https://auth.example.com/v3/mcp", needs_token=True, form=FormReply(values={"token": "wrong"}))
        assert res.failed == "要令牌" and "令牌被拒绝" in res.content and "别反复弹卡" in res.content
        res = await t.run(ctx, action="remove", name="zzz")
        assert res.failed == "没有这台服务器"
        nas_id = s.id
        res = await t.run(ctx, action="remove", name="NAS")
        assert res.content == "已删除 MCP 服务器「nas」。"
        assert await MS.find(db, "nas") is None and not await system_alerts.active(db, f"mcp:{nas_id}")
asyncio.run(rules())

# ---- 4) 一轮：401 → needs_token → 卡 → 加好 ----
script: list = []
seen: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append({"messages": [dict(m) if isinstance(m, dict) else m for m in messages], "tools": [x["function"]["name"] for x in tools or []]})
    step = script.pop(0)
    async def gen():
        if isinstance(step, tuple):
            yield chunk(tool=[NS(index=0, id=f"c{len(script)}", function=NS(name=step[0], arguments=json.dumps(step[1], ensure_ascii=False)))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
forms: list = []
async def turn_ask(fid, block):
    forms.append(block)
    return FormReply(values={"token": TOKEN})
async def seed():
    async with SessionLocal() as db:
        conv = Conversation(title="MCP"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("帮我把 https://auth.example.com/team/mcp 这个 MCP 接上，叫 team")))
        await db.commit()
        return conv.id
cid = asyncio.run(seed())
call = lambda **a: ("deferred_tool", {"action": "call", "tool": "mcp_servers", "arguments": a})
script.extend([call(action="add", name="team", url="https://auth.example.com/team/mcp"),
               call(action="add", name="team", url="https://auth.example.com/team/mcp", needs_token=True, reason="在团队设置里生成"),
               "接好了，team 有 2 个工具。"])
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0), ask=turn_ask)
reply = asyncio.run(turn())
assert "mcp_servers" not in seen[0]["tools"] and "deferred_tool" in seen[0]["tools"]
tool_texts = [m["content"] for m in seen[-1]["messages"] if isinstance(m, dict) and m.get("role") == "tool"]
assert any("needs_token=true" in x for x in tool_texts) and any("已添加 MCP 服务器「team」" in x for x in tool_texts), tool_texts
assert len(forms) == 1 and forms[0]["purpose"] == "token"
fb = [b for b in reply.blocks if b["type"] == "form"]
assert len(fb) == 1 and fb[0]["state"] == "submitted" and not fb[0].get("answers"), fb
dump = json.dumps(reply.blocks, ensure_ascii=False) + json.dumps(reply.steps, ensure_ascii=False) + json.dumps(seen, ensure_ascii=False, default=str)
assert TOKEN not in dump, "令牌绝不能进卡片、时间线或模型上下文"
assert "[表单：添加 MCP「team」需要令牌（auth.example.com）——用户已填写]" in blocks_to_text(reply.blocks)
async def check_saved():
    async with SessionLocal() as db:
        s = await MS.find(db, "team")
        assert s and vault.decrypt(s.token_ciphertext) == TOKEN
        msgs = (await db.scalars(select(Message).where(Message.conversation_id == cid))).all()
        assert all(TOKEN not in json.dumps(m.blocks, ensure_ascii=False) for m in msgs)
asyncio.run(check_saved())

# remove 一轮：拒绝审批 → 还在
script.extend([call(action="remove", name="team"), "你没批准，team 还在。"])
async def turn_deny():
    async with SessionLocal() as db:
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks("删掉 team"))); await db.commit()
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0), ask=turn_ask)
reply = asyncio.run(turn_deny())
assert any(b["type"] == "approval" and b["state"] != "pending" for b in reply.blocks), [b["type"] for b in reply.blocks]
async def still():
    async with SessionLocal() as db:
        return await MS.find(db, "team")
assert asyncio.run(still()) is not None

# ---- 5) 接口共用规则 ----
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth import require_user
from app.routes import connectors as rc
api = FastAPI(); api.include_router(rc.router)
api.dependency_overrides[require_user] = lambda: None
cl = TestClient(api)
r = cl.post("/api/connectors/mcp", json={"name": "TEAM", "url": "https://ok.example.com/other"})
assert r.status_code == 409 and "已经有一台叫「team」" in r.json()["detail"], r.text
r = cl.post("/api/connectors/mcp", json={"name": "x", "url": "mcp.example.com"})
assert r.status_code == 400 and "http" in r.json()["detail"]
r = cl.post("/api/connectors/mcp", json={"name": "lan", "url": "http://10.0.0.9/mcp"})
assert r.status_code == 200 and r.json()["tools"] == ["t0", "t1"] and r.json()["retried_note"] is None, r.text
sid = r.json()["id"]
assert cl.delete(f"/api/connectors/mcp/{sid}").json() == {"ok": True}
assert "lan" not in [x["name"] for x in cl.get("/api/connectors/mcp").json()]
print("smoke_mcp_servers ok")
