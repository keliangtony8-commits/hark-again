# 冒烟：v2.28 浏览器服务本身不能用（E2E B4）——Chromium 起不来 / 服务没连上。
# 1) 真 browser/service.py（playwright 换假的、launch 抛“缺系统库”）：goto → 503 + 一句中文原因（不是 500），
#    冷却期内不再硬试，修好后再起；
# 2) browser_client：503 → BrowserDown（short = 卡上一句），连不上 → BrowserDown，别的错误码照常返回；
# 3) 模拟模型：browser_open / browser_click 碰到 → 这一步记失败、模型拿到整句原因、画面卡标 down 且不残留 live；
#    之后浏览器好了再打开 → 卡上 down 消失；
# 4) 接口：/api/browser/screen、mouse 碰到 → 503（不是 500）。
# 运行：python tests/smoke_browser_down.py
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

# ---- 1. 真 browser 服务（假 playwright）----
LIBERR = ("BrowserType.launch: Target page, context or browser has been closed\n"
          "/ms-playwright/chromium-1134/chrome-linux/chrome: error while loading shared libraries: "
          "libatk-1.0.so.0: cannot open shared object file: No such file or directory")
fail = [LIBERR]
launches = [0]
class Page:
    url = "about:blank"
    def on(self, *a): pass
    def is_closed(self): return False
    async def goto(self, url, **kw): self.url = url
    async def wait_for_timeout(self, *a): pass
    async def evaluate(self, js): return {"url": self.url, "title": "T", "text": "hi", "elements": []}
class Ctx:
    async def route(self, *a): pass
    def on(self, *a): pass
    async def new_page(self):
        self.pages = [Page()]
        return self.pages[0]
    async def storage_state(self, path): open(path, "w").write('{"cookies": []}')
    async def close(self): pass
class Browser:
    def is_connected(self): return True
    async def new_context(self, **kw): return Ctx()
class PW:
    async def start(self):
        async def launch(**kw):
            launches[0] += 1
            if fail:
                raise RuntimeError(fail[0])
            return Browser()
        self.chromium = NS(launch=launch)
        return self
pa = types.ModuleType("playwright.async_api")
pa.Browser = pa.BrowserContext = pa.Page = object
pa.async_playwright = PW
sys.modules["playwright"] = types.ModuleType("playwright")
sys.modules["playwright.async_api"] = pa
os.environ.update(BROWSER_TOKEN="t")
sys.path.insert(0, os.path.join(root, "..", "browser"))
import service
from fastapi import HTTPException
service.STATE = os.path.join(tmp, "state"); os.makedirs(service.STATE)

async def svc():
    async def noop(): pass
    service._egress.start = noop
    service._egress.port = 1
    detail = ""
    for _ in range(2):
        try:
            await service.goto("a-com", service.GotoIn(url="https://a.com/"))
            raise AssertionError("应当 503")
        except HTTPException as e:
            assert e.status_code == 503, e.status_code
            detail = e.detail
    assert detail.startswith("云浏览器没能启动：缺少系统库 libatk-1.0.so.0。") and "重试也没用" in detail, detail
    assert launches[0] == 1  # 第二次在冷却期里，没再硬起
    fail.clear()
    service._launch_error = (0.0, "")  # 冷却过了（修好了）
    snap = await service.goto("a-com", service.GotoIn(url="https://a.com/"))
    assert snap["url"] == "https://a.com/" and launches[0] == 2 and service._launch_error is None
    return detail
DETAIL = asyncio.run(svc())
print("ok: browser service 503")

# ---- 2. browser_client ----
import httpx
from app import browser_client
real_client = httpx.AsyncClient
mode = {"v": "503"}
def handler(req):
    if mode["v"] == "503":
        return httpx.Response(503, json={"detail": DETAIL})
    if mode["v"] == "conn":
        raise httpx.ConnectError("refused", request=req)
    return httpx.Response(404, json={"detail": "x"})
browser_client.httpx.AsyncClient = lambda **kw: real_client(**{**kw, "transport": httpx.MockTransport(handler)})

async def client():
    try:
        await browser_client.snapshot_call("a-com", "GET", "/snapshot")
        raise AssertionError
    except browser_client.BrowserDown as e:
        assert str(e) == DETAIL and e.short == "缺少系统库 libatk-1.0.so.0", e.short
    mode["v"] = "conn"
    try:
        await browser_client.call("a-com", "GET", "/screen")
        raise AssertionError
    except browser_client.BrowserDown as e:
        assert e.short.startswith("云浏览器没连上") and "管理员" in str(e), str(e)
    mode["v"] = "404"
    assert (await browser_client.call("a-com", "GET", "/screen")).status_code == 404  # 别的错误码不是“服务坏了”
asyncio.run(client())
browser_client.httpx.AsyncClient = real_client
print("ok: client")

# ---- 3. 模拟模型 ----
from app import llm
from app.agent import loop
from app.agent.loop import BlockStart, BlockUpdate
from app.agent.tools import ToolContext, load_builtin
from app.db import SessionLocal
from app.models import Conversation

down = {"on": True}
async def fake_snapshot(session, method, path, body=None):
    if down["on"]:
        raise browser_client.BrowserDown(DETAIL)
    return {"title": "页", "url": "https://a.com/", "elements": [{"ref": "1", "tag": "a", "type": "", "name": "首页"}], "text": "正文"}
browser_client.snapshot_call = fake_snapshot

script: list = []
model_saw: list[str] = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
seq = [0]
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    model_saw.append(json.dumps(messages, ensure_ascii=False))
    step = script.pop(0)
    async def gen():
        if isinstance(step, tuple):
            seq[0] += 1
            yield chunk(tool=[NS(index=0, id=f"c{seq[0]}", function=NS(name=step[0], arguments=json.dumps(step[1])))])
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
        return [e async for e in loop.run("sys", [{"role": "user", "content": "去 a.com"}], ctx)]

async def model_turns():
    evs = await events_for("d1", ("browser_open", {"url": "https://a.com/"}), "浏览器坏了")
    blocks = evs[-1].blocks
    assert blocks[0] == {"type": "browser", "session": "a-com", "site": "a.com", "down": "缺少系统库 libatk-1.0.so.0"}, blocks
    tool_msg = json.loads(model_saw[-1])[-1]["content"]
    assert tool_msg.startswith("云浏览器没能启动：缺少系统库") and "Internal Server Error" not in tool_msg, tool_msg
    statuses = [e for e in evs if type(e).__name__ == "ToolStatus" and e.state == "error"]
    assert statuses, "这一步应记失败"
    # 点击也一样：同会话的卡原地标 down，不多出第二张
    evs = await events_for("d1", ("browser_click", {"ref": "1"}), "还是坏的")
    assert [b["type"] for b in evs[-1].blocks] == ["browser", "text"] and evs[-1].blocks[0]["down"]
    # 修好了：再打开 → 卡上 down 消失（单例卡换新不带旧的 down）
    down["on"] = False
    evs = await events_for("d1", ("browser_open", {"url": "https://a.com/"}), "好了")
    assert "down" not in evs[-1].blocks[0] and "live" not in evs[-1].blocks[0], evs[-1].blocks
    ups = [e.block for e in evs if isinstance(e, (BlockStart, BlockUpdate)) and e.block["type"] == "browser"]
    assert ups[0].get("live") and "down" not in ups[0]
asyncio.run(model_turns())
print("ok: model turns")

# ---- 4. 接口 ----
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth import require_user, require_query_token
from app.routes import browser as rb
async def dead_call(session, method, path, json=None):
    raise browser_client.BrowserDown(DETAIL)
browser_client.call = dead_call
app = FastAPI(); app.include_router(rb.router)
app.dependency_overrides[require_user] = lambda: None
app.dependency_overrides[require_query_token] = lambda: None
c = TestClient(app)
r = c.get("/api/browser/screen?session=a-com")
assert r.status_code == 503 and r.json()["detail"] == "缺少系统库 libatk-1.0.so.0", r.text
assert c.post("/api/browser/mouse", json={"x": 0.5, "y": 0.5, "session": "a-com"}).status_code == 503
print("ok: routes")
print("✓ smoke_browser_down 通过")
