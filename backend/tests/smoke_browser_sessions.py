# 冒烟：v1.26 云浏览器会话按网站保存（app/browser_sessions.py、browser/service.py /sessions、/api/browser/sessions）。
# 1) 规则：网址 → 站点 → 会话名（www./子域名归一、bbc.co.uk 三段、IP）、clean、给人看的名字；
# 2) 真 browser/service.py（playwright 换假的）：按名字存档、restored 回报、GET /sessions 只给域名和个数（不给 cookie 值）、
#    DELETE 默认存档再关、forget=1 连存档删；非法名字 400；
# 3) 模拟模型：browser_open 按网站起会话名、打开期间先推 live 画面卡再原地换成最终卡（不残留 live）、同会话一条回复只一张卡、
#    不同网站两张；沿用登录时模型被告知；没打开过的对话点击 → 提示先打开；点击风险按本对话的快照判断；
#    显式 session 参数；对话之间“当前会话”互不串；
# 4) 接口：列表（label、带时区的时间）、退出登录（forget + 正在用它的对话要重新打开）、坏名字 400、服务连不上 503、
#    实时画面/接管带 session 转发，旧卡默认 main。
# 运行：python tests/smoke_browser_sessions.py
import os, sys, asyncio, subprocess, tempfile, json, types
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

# ---- 1. 规则 ----
from app import browser_sessions as bs
assert bs.site_of("https://www.taobao.com/a?b") == "taobao.com"
assert bs.site_of("login.taobao.com") == "taobao.com"
assert bs.site_of("https://news.bbc.co.uk/x") == "bbc.co.uk"
assert bs.site_of("https://github.com") == "github.com"
assert bs.site_of("http://1.2.3.4:8080/") == "1.2.3.4"
assert bs.site_of("") == ""
assert bs.name_for("https://www.taobao.com/") == "taobao-com" == bs.name_for("https://buyer.taobao.com/x")
assert bs.name_for("https://news.bbc.co.uk") == "bbc-co-uk"
assert bs.name_for("not a url ://") == "web" or bs.name_for("not a url ://")
assert bs.clean("  My Shop 2! ") == "my-shop-2" and bs.clean("!!!") == "" and len(bs.clean("a" * 80)) == 40
assert bs.label("main") == "早先的浏览器会话"
assert bs.label("taobao-com", ["taobao.com", "alicdn.com"]) == "taobao.com"
assert bs.label("bbc-co-uk") == "bbc.co.uk" and bs.label("work_acct") == "work_acct"
t1, t2 = bs.tab("c1"), bs.tab("c2")
assert t1 is bs.tab("c1") and t1 is not t2 and bs.tab(None, "task9") is not bs.tab(None, "task8")
print("ok: rules")

# ---- 2. 真 browser 服务（假 playwright）----
saved_files: dict = {}
class Page:
    def __init__(self): self.url = "about:blank"
    def on(self, *a): pass
    async def goto(self, url, **kw): self.url = url
    async def wait_for_load_state(self, *a, **kw): pass
    async def evaluate(self, js): return {"url": self.url, "title": "T", "text": "hi", "elements": []}
class Ctx:
    def __init__(self, state): self.state, self.closed = state, False
    async def route(self, *a): pass
    def on(self, *a): pass
    async def new_page(self): return Page()
    async def storage_state(self, path):
        with open(path, "w") as f:
            json.dump({"cookies": [{"domain": ".taobao.com", "name": "sid", "value": "SECRET"},
                                   {"domain": "login.taobao.com", "name": "x", "value": "y"},
                                   {"domain": ".taobao.com", "name": "z", "value": "w"}], "origins": []}, f)
    async def close(self): self.closed = True
class Browser:
    def is_connected(self): return True
    async def new_context(self, **kw): return Ctx(kw.get("storage_state"))
class PW:
    async def start(self):
        async def launch(**kw): return Browser()
        self.chromium = NS(launch=launch)
        return self
pa = types.ModuleType("playwright.async_api")
pa.Browser = pa.BrowserContext = pa.Page = object
pa.async_playwright = PW
sys.modules["playwright"] = types.ModuleType("playwright")
sys.modules["playwright.async_api"] = pa
os.environ.update(BROWSER_TOKEN="t", BROWSER_MAX_SESSIONS="1")
sys.path.insert(0, os.path.join(root, "..", "browser"))
import service
from fastapi import HTTPException
service.STATE = os.path.join(tmp, "state")

async def svc():
    async def allow(route): pass
    service._guard = allow
    snap = await service.goto("taobao-com", service.GotoIn(url="https://www.taobao.com/"))
    assert snap["restored"] is False and os.path.exists(f"{service.STATE}/taobao-com.json")
    lst = await service.sessions()
    s = lst["sessions"][0]
    assert lst["max_open"] == 1 and s["name"] == "taobao-com" and s["open"] and s["saved"]
    assert s["cookies"] == 3 and s["domains"] == ["taobao.com", "login.taobao.com"], s
    assert "SECRET" not in json.dumps(lst)
    # 上限 1：开第二个 → 第一个存档关掉；再打开第一个 → restored
    await service.goto("jd-com", service.GotoIn(url="https://www.jd.com/"))
    names = {x["name"]: x for x in (await service.sessions())["sessions"]}
    assert not names["taobao-com"]["open"] and names["taobao-com"]["saved"] and names["jd-com"]["open"]
    snap = await service.goto("taobao-com", service.GotoIn(url="https://www.taobao.com/"))
    assert snap["restored"] is True
    # 默认关闭 = 存档再关；forget = 删存档
    await service.close("taobao-com")
    names = {x["name"]: x for x in (await service.sessions())["sessions"]}
    assert not names["taobao-com"]["open"] and names["taobao-com"]["saved"]
    await service.close("taobao-com", forget=True)
    assert "taobao-com" not in {x["name"] for x in (await service.sessions())["sessions"]}
    await service.close("never-opened", forget=True)  # 没有也不报错
    try:
        await service.close("../etc", forget=True)
        raise AssertionError("bad name accepted")
    except HTTPException as e:
        assert e.status_code == 400
    open(f"{service.STATE}/junk name.json", "w").write("{}")  # 不合法的文件名不列
    assert "junk name" not in {x["name"] for x in (await service.sessions())["sessions"]}
asyncio.run(svc())
print("ok: browser service")

# ---- 3. 模拟模型 ----
from app import llm, browser_client
from app.agent import runner
from app.agent.loop import MessageBuilder, BlockStart, BlockUpdate
from app.agent import loop
from app.agent.tools import ToolContext, load_builtin
from app.db import SessionLocal
from app.models import Conversation, Message
from app.blocks import text_to_blocks

calls: list = []
restored = {"taobao-com": True}
ELEMENTS = [{"ref": "1", "tag": "button", "type": "", "name": "提交订单"}, {"ref": "2", "tag": "a", "type": "", "name": "首页"}]
async def fake_snapshot(session, method, path, body=None):
    calls.append((session, method, path, body))
    url = body["url"] if body and "url" in body else f"https://{session.replace('-', '.')}/"
    snap = {"title": "页", "url": url, "elements": ELEMENTS, "text": "正文"}
    if path == "/goto":
        snap["restored"] = restored.get(session, False)
    return snap
browser_client.snapshot_call = fake_snapshot

script: list = []
model_saw: list[str] = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    model_saw.append(json.dumps(messages, ensure_ascii=False))
    step = script.pop(0)
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"c{len(script)}-{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(step)])
        elif isinstance(step, tuple):
            name, args = step
            yield chunk(tool=[NS(index=0, id=f"c{len(script)}", function=NS(name=name, arguments=json.dumps(args, ensure_ascii=False)))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()

async def events_for(cid, *steps):
    script.extend(steps)
    async with SessionLocal() as db:
        if not await db.get(Conversation, cid):
            db.add(Conversation(id=cid, title="t")); await db.commit()
        ctx = ToolContext(db=db, conversation_id=cid)
        return [e async for e in loop.run("sys", [{"role": "user", "content": "去淘宝"}], ctx)]

async def model_turns():
    # 打开淘宝：先推 live 卡，再原地换成最终卡
    evs = await events_for("k1", ("browser_open", {"url": "https://www.taobao.com/"}), "好")
    starts = [e for e in evs if isinstance(e, BlockStart) and e.block["type"] == "browser"]
    ups = [e for e in evs if isinstance(e, BlockUpdate) and e.block["type"] == "browser"]
    assert len(starts) == 1 and starts[0].block == {"type": "browser", "session": "taobao-com", "site": "taobao.com", "live": True}, starts
    assert ups and ups[-1].block == {"type": "browser", "session": "taobao-com", "site": "taobao.com"}, ups
    blocks = evs[-1].blocks
    assert [b["type"] for b in blocks] == ["browser", "text"] and "live" not in blocks[0]
    assert calls[-1][:3] == ("taobao-com", "POST", "/goto")
    tool_msg = json.loads(model_saw[-1])[-1]["content"]
    assert "会话：taobao-com" in tool_msg and "沿用了这个会话之前保存的登录" in tool_msg, tool_msg

    # 同一回复里同会话再开一次 → 仍一张卡；换网站 → 第二张；显式 session
    evs = await events_for("k2", ("browser_open", {"url": "https://taobao.com/a"}), ("browser_open", {"url": "https://buyer.taobao.com/b"}),
                           ("browser_open", {"url": "https://www.jd.com/", "session": "JD Work"}), "好")
    blocks = evs[-1].blocks
    assert [(b["type"], b.get("session")) for b in blocks] == [("browser", "taobao-com"), ("browser", "jd-work"), ("text", None)], blocks
    tool_msg = json.loads(model_saw[-1])[-1]["content"]
    assert "新会话" in tool_msg and "从会话 taobao-com 换到了这个" in tool_msg, tool_msg

    # 新对话没打开过 → 点击提示先打开（不调浏览器）
    n = len(calls)
    await events_for("k3", ("browser_click", {"ref": "2"}), "好")
    assert "还没打开浏览器" in json.loads(model_saw[-1])[-1]["content"] and len(calls) == n

    # k2 的当前会话是 jd-work：点击作用于它；风险按 k2 的快照（“提交订单”）→ 无人值守不批
    await events_for("k2", ("browser_click", {"ref": "2"}), "好")
    assert calls[-1][:3] == ("jd-work", "POST", "/act")
    n = len(calls)
    await events_for("k2", ("browser_click", {"ref": "1"}), "好")
    assert "用户没有批准" in json.loads(model_saw[-1])[-1]["content"] and len(calls) == n
    # k1 仍在 taobao-com（对话之间不串）
    await events_for("k1", ("browser_read", {}), "好")
    assert calls[-1][:3] == ("taobao-com", "GET", "/snapshot")

    # 停止时 live 卡不残留
    b = MessageBuilder(); b.add({"type": "browser", "session": "x", "live": True})
    assert b.partial() == [{"type": "browser", "session": "x"}]
asyncio.run(model_turns())
print("ok: model turns")

# ---- 4. 接口 ----
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth import require_user, require_query_token
from app.routes import browser as rb

state = {"down": False}
closed: list = []
async def fake_sessions():
    if state["down"]:
        raise RuntimeError("云浏览器没连上")
    return {"sessions": [{"name": "taobao-com", "open": True, "saved": True, "last_used": 1791781863.0, "cookies": 3,
                          "domains": ["taobao.com"]},
                         {"name": "main", "open": False, "saved": True, "last_used": None, "cookies": 1, "domains": ["x.com"]}],
            "max_open": 1}
async def fake_close(name, forget=False):
    if state["down"]:
        raise RuntimeError("云浏览器没连上")
    closed.append((name, forget))
seen_calls: list = []
async def fake_call(session, method, path, json=None):
    seen_calls.append((session, method, path, json))
    return httpx.Response(200, content=b"jpg")
browser_client.sessions, browser_client.close, browser_client.call = fake_sessions, fake_close, fake_call
app = FastAPI(); app.include_router(rb.router)
app.dependency_overrides[require_user] = lambda: None
app.dependency_overrides[require_query_token] = lambda: None
c = TestClient(app)
j = c.get("/api/browser/sessions").json()
assert j["max_open"] == 1 and [s["label"] for s in j["sessions"]] == ["taobao.com", "早先的浏览器会话"]
assert j["sessions"][0]["last_used"].endswith("+00:00") and j["sessions"][1]["last_used"] is None
bs.tab("k9").session = "taobao-com"
assert c.delete("/api/browser/sessions/taobao-com").json() == {"ok": True}
assert closed == [("taobao-com", True)] and bs.tab("k9").session == ""
assert c.delete("/api/browser/sessions/Bad.Name").status_code == 400
state["down"] = True
assert c.get("/api/browser/sessions").status_code == 503 and c.delete("/api/browser/sessions/a-b").status_code == 503
assert c.get("/api/browser/screen?session=taobao-com").content == b"jpg"
assert c.get("/api/browser/screen").status_code == 200 and seen_calls[-1][0] == "main"  # 旧卡
assert c.get("/api/browser/screen?session=../x").status_code == 422
c.post("/api/browser/mouse", json={"x": 2, "y": 0.5, "session": "jd-com"})
assert seen_calls[-1] == ("jd-com", "POST", "/mouse", {"x": 1, "y": 0.5})
c.post("/api/browser/keyboard", json={"text": "hi", "session": "jd-com"})
assert seen_calls[-1] == ("jd-com", "POST", "/keyboard", {"text": "hi", "key": None})
print("ok: api")
print("✓ smoke_browser_sessions")
