# 冒烟：v2.52 BRAIN (bf) connect_api_key——app/api_keys.py 唯一规则 + 工具 + 保险箱接口共用 + api_request 带法。模拟模型，迁移 0056。
# 1) 规则：check_hosts（去协议 / 去重 / 要带点 / 上限 / 助手接 OAuth 域名 → oauth，用户自己存放过）、check_scheme（坏请求头 / 参数名）、
#    check_verify_url（https 且在域名里）；
# 2) connect：verify 2xx → 通过；401 → rejected 什么都不存；404 / 连不上 → 存但 verified=None；同服务再接 = 原地换（不多一条）；
#    query_param 带法 → api_request 把 Key 放进 ?appid=，回显里的 Key（含 URL 编码）抹掉；卡在 needs_connector:<服务> 的任务重跑；
# 3) 工具：参数错不弹卡；有人 → 表单卡 purpose=token（无值）；替换时标题“换一把新 Key”；无人值守 → 不弹卡并指去保险箱；
# 4) api_request 401 无 Key → 提示 connect_api_key；保险箱 Key 被拒 → 提示换 Key；
# 5) 一轮（deferred_tool call）：api_request 401 → connect_api_key → 卡 → 填 Key → 验证通过 → api_request 带上 → 回复；
#    Key 不进卡片 / 时间线 / 模型上下文 / 数据库消息；
# 6) 接口 POST /api/vault api_key 走同一规则（query_param 存下；同域名再存 = 替换；无域名 400）。
# 运行：python tests/smoke_api_keys.py
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
from app import api_keys as AK, llm, vault, web_guard
from app.agent.approvals import FormReply
from app.agent.runner import run_turn
from app.agent.tools import REGISTRY, ToolContext, load_builtin, nobody
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message, ScheduledTask, Secret

KEY = "wk-SECRET+5566/x"   # 带 + / 测 URL 编码后的打码
requests: list = []

def handler(req: httpx.Request):
    requests.append(req)
    host, path = req.url.host, req.url.path
    if host == "down.example.com":
        raise httpx.ConnectError("refused", request=req)
    if host == "api.weather.test":   # 网址参数带法
        if req.url.params.get("appid") != KEY:
            return httpx.Response(401, json={"cod": 401, "message": "Invalid API key"})
        return httpx.Response(200, json={"city": "杭州", "temp": 21, "echo": str(req.url)})
    if host == "api.notes.test":     # x-api-key 无前缀
        if path == "/missing":
            return httpx.Response(404, json={"error": "no route"})
        if req.headers.get("x-api-key") != KEY:
            return httpx.Response(403, json={"error": "forbidden"})
        return httpx.Response(200, json={"notes": 3})
    return httpx.Response(200, json={"ok": True})
real_client = httpx.AsyncClient
httpx.AsyncClient = lambda **kw: real_client(**{**kw, "transport": httpx.MockTransport(handler)})
async def fake_resolve(host):
    return ["93.184.216.34"]
web_guard.resolve = fake_resolve

# ---- 1) 规则 ----
assert AK.check_hosts(["https://API.Weather.test/data/2.5", "api.weather.test", " "]) == ["api.weather.test"]
assert AK.check_hosts("a.test, b.test") == ["a.test", "b.test"]
for bad, kind in [([], "hosts"), (["com"], "hosts"), (["*.x.com"], "hosts"), (["a.localhost"], "hosts"),
                  ([f"h{i}.test" for i in range(5)], "hosts"), (["api.github.com"], "oauth")]:
    try:
        AK.check_hosts(bad); raise AssertionError(bad)
    except AK.ConnectError as e:
        assert e.kind == kind, (bad, e.kind)
assert AK.check_hosts(["api.github.com"], by="user") == ["api.github.com"]
assert AK.check_scheme() == AK.Scheme("Authorization", "Bearer ", None)
assert AK.check_scheme("x-api-key", "") == AK.Scheme("x-api-key", "", None)
assert AK.check_scheme("x-api-key", "", "appid") == AK.Scheme("", "", "appid")
for h, p, q in [("Cookie", None, ""), ("bad header", None, ""), ("X", "a\nb", ""), ("X", None, "a&b")]:
    try:
        AK.check_scheme(h, p, q); raise AssertionError((h, p, q))
    except AK.ConnectError as e:
        assert e.kind == "scheme"
assert AK.check_verify_url("", ["a.test"]) is None
for bad in ("http://a.test/x", "https://evil.test/x"):
    try:
        AK.check_verify_url(bad, ["a.test"]); raise AssertionError(bad)
    except AK.ConnectError as e:
        assert e.kind == "verify_url"
assert AK.check_verify_url("https://v1.a.test/ping", ["a.test"]) == "https://v1.a.test/ping"

load_builtin()
t = REGISTRY["connect_api_key"]
api = REGISTRY["api_request"]
assert t.deferred and t.form and not t.risk

async def rules():
    async with SessionLocal() as db:
        db.add(ScheduledTask(name="每天天气", prompt="查天气", cron="0 7 * * *", wall="needs_connector:openweather"))
        await db.commit()
        # 被拒 → 不存
        try:
            await AK.connect(db, "OpenWeather", "wrongkey", ["api.weather.test"], query_param="appid",
                             verify_url="https://api.weather.test/ping"); raise AssertionError
        except AK.ConnectError as e:
            assert e.kind == "rejected" and "没有保存" in str(e) and "wrongkey" not in str(e)
        assert not (await db.scalars(select(Secret))).all()
        c = await AK.connect(db, "OpenWeather", KEY, ["api.weather.test"], query_param="appid",
                             verify_url="https://api.weather.test/ping")
        assert c.verified is True and not c.replaced and c.secret.query_param == "appid" and vault.reveal(c.secret) == KEY
        assert c.retried and "每天天气" in c.retried
        txt = AK.connected_text(c)
        assert KEY not in txt and "验证通过" in txt and "网址参数 ?appid=" in txt and "已重新运行" in txt, txt
        assert (await db.scalar(select(ScheduledTask))).run_requested
        # api_request：Key 进网址参数，回显打码
        ctx = ToolContext(db=db, ask=None, conversation_id="c1")
        res = await api.run(ctx, url="https://api.weather.test/data?q=hz")
        assert "HTTP 200" in res.content and "保险箱「OpenWeather」" in res.content and "杭州" in res.content
        assert KEY not in res.content and "SECRET%2B5566" not in res.content and "••••" in res.content, res.content
        assert requests[-1].url.params.get("q") == "hz" and requests[-1].url.params.get("appid") == KEY
        assert "authorization" not in requests[-1].headers
        # 没给验证地址 / 404 / 连不上 → 存但没确认
        n = await AK.connect(db, "Notes", KEY, ["api.notes.test"], header_name="x-api-key", header_prefix="",
                             verify_url="https://api.notes.test/missing")
        assert n.verified is None and "404" in n.verify_note and "还没确认能用" in AK.connected_text(n)
        d = await AK.connect(db, "Down", KEY, ["down.example.com"], verify_url="https://down.example.com/x")
        assert d.verified is None and "无法连接" in d.verify_note
        nv = await AK.connect(db, "Plain", "plainkey1", ["plain.test"])
        assert nv.verified is None and "没给验证地址" in nv.verify_note
        # 同服务再接：原地换
        before = len((await db.scalars(select(Secret))).all())
        again = await AK.connect(db, "Notes", "newkey-77", ["v2.api.notes.test"], header_name="x-api-key", header_prefix="")
        assert again.replaced and again.secret.id == n.secret.id and vault.reveal(again.secret) == "newkey-77"
        assert again.secret.hosts == ["v2.api.notes.test"] and len((await db.scalars(select(Secret))).all()) == before
        again = await AK.connect(db, "Notes", KEY, ["api.notes.test"], header_name="x-api-key", header_prefix="")
        res = await api.run(ctx, url="https://api.notes.test/list")
        assert "HTTP 200" in res.content and '"notes": 3' in res.content and requests[-1].headers["x-api-key"] == KEY
        # 4) 401/403 提示
        res = await api.run(ctx, url="https://api.weather.test/x".replace("weather", "weather2"))
        assert "connect_api_key" not in res.content  # 200 → 无提示
        async def bad_secret():
            s = await AK.existing(db, ["api.notes.test"]); s.ciphertext = vault.encrypt("stale-key"); await db.commit()
        await bad_secret()
        res = await api.run(ctx, url="https://api.notes.test/list")
        assert "HTTP 403" in res.content and "被对方拒绝" in res.content and "connect_api_key" in res.content
        await AK.connect(db, "Notes", KEY, ["api.notes.test"], header_name="x-api-key", header_prefix="")

        # ---- 3) 工具 ----
        async def asker(_id, _b):
            return FormReply(values={"key": KEY})
        tc = ToolContext(db=db, ask=asker, conversation_id="c1")
        card = await t.form(tc, {"service": "Maps", "hosts": ["restapi.maps.test"], "reason": "在控制台 → 应用管理里申请 Web 服务 Key", "query_param": "key"})
        assert card["purpose"] == "token" and card["site"] == "restapi.maps.test" and card["title"] == "连接 Maps 需要 API Key"
        assert card["fields"][0]["kind"] == "password" and "value" not in card["fields"][0] and "Web 服务 Key" in card["note"]
        card = await t.form(tc, {"service": "Notes", "hosts": ["api.notes.test"], "reason": "x"})
        assert card["title"] == "给Notes换一把新 Key", card["title"]
        assert await t.form(tc, {"service": "G", "hosts": ["api.github.com"], "reason": "x"}) is None
        assert await t.form(tc, {"service": "W", "hosts": ["a.test"], "reason": "x", "verify_url": "https://b.test"}) is None
        assert await t.form(ToolContext(db=db, ask=nobody), {"service": "W", "hosts": ["a.test"], "reason": "x"}) is None
        res = await t.run(tc, service="G", hosts=["api.github.com"], reason="x")
        assert res.failed == "参数不对" and "connector_accounts" in res.content
        res = await t.run(ToolContext(db=db, ask=nobody), service="Maps", hosts=["restapi.maps.test"], reason="x")
        assert res.failed == "没人能填 Key" and "保险箱" in res.content
        res = await t.run(tc, service="OpenWeather", hosts=["api.weather.test"], reason="x", query_param="appid",
                          verify_url="https://api.weather.test/ping", form=FormReply(values={"key": "nope-nope"}))
        assert res.failed == "Key 被拒" and "别反复弹卡" in res.content
        assert vault.reveal(await AK.existing(db, ["api.weather.test"])) == KEY, "被拒的 Key 不能顶掉旧的"
asyncio.run(rules())

# ---- 5) 一轮 ----
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
    return FormReply(values={"key": KEY})
async def seed():
    async with SessionLocal() as db:
        conv = Conversation(title="天气"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("用我的心知天气 Key 查一下杭州天气")))
        await db.commit()
        return conv.id
cid = asyncio.run(seed())
KEY2 = KEY
def handler2(req):
    requests.append(req)
    if req.url.host == "api.xinzhi.test":
        if req.url.params.get("key") != KEY:
            return httpx.Response(401, json={"status": "The API key is invalid."})
        return httpx.Response(200, json={"results": [{"now": {"text": "晴", "temperature": "22"}}]})
    return handler(req)
httpx.AsyncClient = lambda **kw: real_client(**{**kw, "transport": httpx.MockTransport(handler2)})
call = lambda **a: ("deferred_tool", {"action": "call", "tool": "connect_api_key", "arguments": a})
script.extend([("api_request", {"url": "https://api.xinzhi.test/v3/weather/now.json?location=hangzhou"}),
               call(service="心知天气", hosts=["api.xinzhi.test"], reason="在心知天气控制台 → 密钥 里复制私钥", query_param="key",
                    verify_url="https://api.xinzhi.test/v3/weather/now.json?location=beijing"),
               ("api_request", {"url": "https://api.xinzhi.test/v3/weather/now.json?location=hangzhou"}),
               "杭州现在晴，22°C。"])
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0), ask=turn_ask)
reply = asyncio.run(turn())
assert "connect_api_key" not in seen[0]["tools"] and "deferred_tool" in seen[0]["tools"]
tool_texts = [m["content"] for m in seen[-1]["messages"] if isinstance(m, dict) and m.get("role") == "tool"]
assert any("HTTP 401" in x and "connect_api_key" in x for x in tool_texts), tool_texts
assert any("用户已在卡上填好 心知天气 的 Key" in x and "验证通过" in x for x in tool_texts), tool_texts
assert any("HTTP 200" in x and "晴" in x for x in tool_texts), tool_texts
assert len(forms) == 1 and forms[0]["purpose"] == "token" and forms[0]["site"] == "api.xinzhi.test"
fb = [b for b in reply.blocks if b["type"] == "form"]
assert len(fb) == 1 and fb[0]["state"] == "submitted" and not fb[0].get("answers"), fb
dump = json.dumps(reply.blocks, ensure_ascii=False) + json.dumps(reply.steps, ensure_ascii=False) + json.dumps(seen, ensure_ascii=False, default=str)
assert KEY not in dump and "SECRET%2B5566" not in dump, "Key 绝不能进卡片、时间线或模型上下文"
async def check_db():
    async with SessionLocal() as db:
        msgs = (await db.scalars(select(Message).where(Message.conversation_id == cid))).all()
        assert all(KEY not in json.dumps(m.blocks, ensure_ascii=False) for m in msgs)
        s = await AK.existing(db, ["api.xinzhi.test"])
        assert s and s.name == "心知天气" and s.query_param == "key"
asyncio.run(check_db())

# ---- 6) 接口 ----
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth import require_user
from app.routes import vault as rv
app_ = FastAPI(); app_.include_router(rv.router)
app_.dependency_overrides[require_user] = lambda: None
cl = TestClient(app_)
r = cl.post("/api/vault", json={"kind": "api_key", "name": "高德", "value": "amapkey123", "hosts": ["restapi.amap.test"], "query_param": "key"})
assert r.status_code == 200 and r.json()["query_param"] == "key" and r.json()["replaced"] is False, r.text
r = cl.post("/api/vault", json={"kind": "api_key", "name": "高德", "value": "amapkey456", "hosts": ["restapi.amap.test"], "query_param": "key"})
assert r.status_code == 200 and r.json()["replaced"] is True
r = cl.post("/api/vault", json={"kind": "api_key", "name": "GH", "value": "ghp_abcdef", "hosts": ["api.github.com"]})
assert r.status_code == 200, "用户自己存 GitHub PAT 照收"
r = cl.post("/api/vault", json={"kind": "api_key", "name": "X", "value": "abcdefgh"})
assert r.status_code == 400 and "域名" in r.json()["detail"]
assert "amapkey" not in json.dumps(cl.get("/api/vault").json())
print("smoke_api_keys ok")
