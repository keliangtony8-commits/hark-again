# 冒烟：v2.36 BRAIN (bb) connector_accounts——app/connector_accounts.py 唯一规则 + 工具。
# 1) 规则：find 认 id/名字；四种状态（已连接 / 授权失效 / 可以连接 / 服务器没配）；listing 带 MCP；系统提示那一行；
#    v2.90.2 setup()：只对没配的服务商给部署引导（注册地址、回调 = PUBLIC_URL/api/oauth/callback、.env 变量名）；
# 2) 工具：list；connect 出连接卡（换号 = reconnect）、没配 → 拒绝、无人值守 → 不出卡；disconnect 要审批、执行后连接与失效提醒都清掉；
# 3) 一轮（模拟模型，经 deferred_tool call）：回复里有连接卡，历史文本是“[连接卡：Google（google）]”。
# 运行：python tests/smoke_connector_accounts.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  GOOGLE_CLIENT_ID="gid", GOOGLE_CLIENT_SECRET="gs", GITHUB_CLIENT_ID="ghid", GITHUB_CLIENT_SECRET="",  # 只填一半 = 没配
  PUBLIC_URL="https://toyuis.example.com/",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import connector_accounts as CA, system_alerts
from app.agent.runner import run_turn
from app.agent.tools import REGISTRY, ToolContext, load_builtin, nobody
from app.blocks import blocks_to_text, text_to_blocks
from app.db import SessionLocal
from app.models import Connection, Conversation, HomeCard, McpServer, Message
from sqlalchemy import select

assert CA.find("google").id == "google" and CA.find("GitHub").id == "github" and CA.find(" Git-Hub ").id == "github"
assert CA.find("Google Calendar").id == "google" and CA.find("google_calendar").id == "google" and CA.find("Gmail").id == "google"
assert CA.find("日历").id == "google" and CA.find("dropbox") is None and CA.find("") is None
assert CA.prompt([]) .startswith("还没连接、但可以连：Google（") and "GitHub" not in CA.prompt([])  # github 没配
assert CA.prompt(["google"]) is None
# v2.90.2 setup：配好的 → None；没配（id 有、secret 空也算）→ 部署引导，回调只来自 oauth.redirect_uri
assert CA.setup(CA.find("google")) is None
assert CA.setup(CA.find("github")) == {"console": "https://github.com/settings/developers",
                                       "callback": "https://toyuis.example.com/api/oauth/callback",
                                       "env": ["GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET"]}, CA.setup(CA.find("github"))
from app.connectors.providers import PROVIDERS
from app.config import settings
for p in PROVIDERS.values():  # 变量名必须真是 config.py 的字段（.env 填了才读得到），注册地址必须有
    assert all(hasattr(settings, n.lower()) for n in p.env_names) and p.console_url.startswith("https://"), p.id

async def ask(_id, _form):
    return None
load_builtin()
t = REGISTRY["connector_accounts"]
assert t.deferred

async def main():
    async with SessionLocal() as db:
        st = {a.provider.id: a.status for a in await CA.accounts(db)}
        assert st == {"google": CA.AVAILABLE, "github": CA.UNCONFIGURED}, st
        db.add(McpServer(name="Notion", url="https://n/mcp")); await db.commit()
        text = await CA.listing(db)
        assert text.startswith("已连接（能直接用）：无\n还没连、可以连（发连接卡）：Google（id google：") and "服务器没配应用（现在连不了）：GitHub" in text, text
        assert "MCP 服务器：Notion（正常）" in text and "授权失效" not in text, text
        ctx = ToolContext(db=db, ask=ask, conversation_id="c1")
        res = await t.run(ctx, action="list")
        assert res.content == text and not res.failed
        res = await t.run(ctx, action="connect", provider="google", reason="读你的日历排明天的事" * 10)
        b = res.blocks[0]
        assert b["type"] == "connect" and b["provider"] == "google" and not b["reconnect"] and b["account"] is None
        assert len(b["reason"]) == CA.REASON_MAX and "连接 Google" in res.content and res.detail == "连接 Google"
        res = await t.run(ctx, action="connect", provider="github")
        assert res.failed == "服务器没配这个应用" and not res.blocks and "GITHUB_CLIENT_ID" in res.content and "api.github.com" in res.content
        res = await t.run(ToolContext(db=db, ask=nobody), action="connect", provider="google")
        assert res.failed == "没人能连接" and not res.blocks and "needs_connector:google" in res.content
        res = await t.run(ctx, action="connect", provider="dropbox")
        assert res.failed == "没有「dropbox」这个连接器" and "id google" in res.content
        assert (await t.run(ctx, action="nuke")).failed == "参数不对"
        assert (await t.run(ctx, action="connect")).failed == "没填 provider"
        h = await CA.missing_hint(db, "https://www.googleapis.com/calendar/v3/x")
        assert "provider=google" in h and "还没连接" in h, h
        assert "保险箱" in await CA.missing_hint(db, "https://api.github.com/user")
        assert await CA.missing_hint(db, "https://api.example.com/x") == ""
        res = await t.run(ctx, action="disconnect", provider="google")
        assert "本来就没连" in res.content

        # 连上了，然后失效
        db.add(Connection(provider="google", account="me@gmail.com", ciphertext="x")); await db.commit()
        assert (await CA.one(db, CA.find("google"))).status == CA.CONNECTED
        res = await t.run(ctx, action="connect", provider="google")
        assert res.blocks[0]["reconnect"] and res.blocks[0]["account"] == "me@gmail.com" and "已经连着" in res.content
        await system_alerts.post(db, subject="connector:google", once="fp", title="Google 连接已失效", text="x", open="connectors")
        await db.commit()
        a = await CA.one(db, CA.find("google"))
        assert a.status == CA.EXPIRED and "连过但授权失效（要用户重新连接，发连接卡）：Google（id google：Gmail、日历、云端硬盘，账户 me@gmail.com）" in await CA.listing(db)
        assert "授权失效了" in CA.connect_text(a)

        # 断开：审批理由只在 disconnect；执行后连接与提醒都没了
        assert t.risk({"action": "disconnect", "provider": "google"}, ctx) == "断开 Google 账户：之后我不能再代你读写它"
        assert t.risk({"action": "connect", "provider": "google"}, ctx) is None
        assert t.risk({"action": "disconnect", "provider": "zz"}, ctx) is None
        res = await t.run(ctx, action="disconnect", provider="google")
        assert "已断开 Google（me@gmail.com）" in res.content
        assert await db.scalar(select(Connection)) is None
        cards = (await db.scalars(select(HomeCard).where(HomeCard.dismissed.is_(False)))).all()
        assert not cards, [c.title for c in cards]
        assert (await CA.one(db, CA.find("google"))).status == CA.AVAILABLE
asyncio.run(main())

# ---- 3. 一轮（模拟模型）----
from app import llm
seen, script = [], []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append({"messages": [dict(m) for m in messages], "tools": [x["function"]["name"] for x in tools or []]})
    step = script.pop(0)
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"c{len(script)}-{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
async def seed():
    async with SessionLocal() as db:
        conv = Conversation(title="日历"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("帮我看看明天日历上有什么")))
        await db.commit()
        return conv.id
cid = asyncio.run(seed())
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0), ask=ask)
script.extend([[("deferred_tool", {"action": "call", "tool": "connector_accounts",
                                   "arguments": {"action": "connect", "provider": "google", "reason": "读你的日历"}})],
               "先点上面的卡连上 Google，连好告诉我。"])
reply = asyncio.run(turn())
sysmsg = seen[0]["messages"][0]["content"]
assert "还没连接、但可以连：Google" in sysmsg and "connector_accounts" not in seen[0]["tools"], seen[0]["tools"]
types = [b["type"] for b in reply.blocks]
assert "connect" in types, types
assert "[连接卡：Google（google）]" in blocks_to_text(reply.blocks)
assert [(x["tool"], x["state"]) for x in reply.steps] == [("connector_accounts", "done")], reply.steps
# ---- 4. 连接器列表接口带 status（客户端卡片和连接器页用同一份判定）----
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth import require_user
from app.routes import connectors as rc
api = FastAPI(); api.include_router(rc.router)
api.dependency_overrides[require_user] = lambda: None
rows = {x["id"]: x for x in TestClient(api).get("/api/connectors").json()}
assert rows["google"]["status"] == "available" and rows["google"]["account"] is None and rows["github"]["status"] == "unconfigured"
# v2.90.2：没配的带 setup（客户端据此隐藏这一行、给部署者一行引导），配好的 setup 为 null
assert rows["google"]["setup"] is None and rows["github"]["setup"]["env"] == ["GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET"], rows
assert rows["github"]["setup"]["callback"] == "https://toyuis.example.com/api/oauth/callback"
r = TestClient(api).get("/api/connectors/github/start")
assert r.status_code == 400 and "docs/oauth-setup.md" in r.json()["detail"], r.text
print("smoke_connector_accounts ok")
