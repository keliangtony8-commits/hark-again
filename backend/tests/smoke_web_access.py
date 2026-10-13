# 冒烟：v2.01 大脑 (ap) 出网安全 + 读网页升级 + 搜图片——app/web_guard.py、app/web_page.py、web 工具。模拟模型，无迁移。
# - web_guard：私网 / 回环 / 链路本地 / 共享 / 测试网段 / IPv4 映射 IPv6 / 内部后缀拒；域名解析出任一私网地址拒；
#   允许名单放行；重定向跳到内网也拦（传输层每跳检查）；配了代理（mounts）也拦；github blob → raw；按主机限速；
# - web_page：HTML 提正文带标题、JSON 原样缩进、纯文本、PDF 带页码、二进制不进上下文、超 5MB 只读前面、截断、
#   缓存（max_age=0 现读）、错误页注明 HTTP 状态且不缓存、超时 / 连不上中文原因；
# - 工具：配图探测与 api_request、browser_open 拒内网；一轮对话里模型并行调 web_search(recent) + image_search +
#   web_fetch（内网被拒 → 时间线 error）→ 结果交回模型；计划模式、子助手都能用 image_search。
# 运行：python tests/smoke_web_access.py
import os, sys, asyncio, subprocess, tempfile, json, io
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai",
  OUTBOUND_ALLOW_HOSTS="nas.home")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

import httpx
from app import llm, plan_mode, web_guard, web_page
from app.agent import runner, subagent
from app.agent.builtin import web as web_tools, display, api as api_tool, browser as browser_tool
from app.agent.tools import REGISTRY, load_builtin
from app.blocks import text_to_blocks
from app.config import settings
from app.db import SessionLocal
from app.models import Conversation, Message

DNS = {"example.com": ["93.184.216.34"], "evil.example": ["8.8.8.8", "10.0.0.5"], "sandbox": ["172.18.0.3"],
       "rebind.example": ["127.0.0.1"], "news.example": ["1.1.1.1"], "img.example": ["1.0.0.1"],
       "raw.githubusercontent.com": ["185.199.108.133"], "nas.home": ["192.168.1.9"]}
async def fake_resolve(host):
    if host not in DNS:
        raise OSError(-2, "Name or service not known")
    return DNS[host]
web_guard.resolve = fake_resolve

def run(c):
    return asyncio.run(c)

def blocked(url, **kw):
    try:
        run(web_guard.check(url, **kw))
    except web_guard.Blocked as e:
        return str(e)
    return None

# --- 地址规则 ---
P = web_guard.is_private_address
for a in ("127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.0.1", "169.254.169.254", "100.64.0.1", "198.18.0.1",
          "0.0.0.0", "224.0.0.1", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "localhost",
          "db.internal", "printer.local", "x.localhost", "240.0.0.1"):
    assert P(a), a
for a in ("8.8.8.8", "93.184.216.34", "2606:4700::1111", "::ffff:8.8.8.8", "example.com"):
    assert not P(a), a
assert web_guard.sanitize_host("[::1]") == "::1" and web_guard.sanitize_host("Example.COM.") == "example.com"

assert "内部主机名" in blocked("http://localhost:8000/api")
assert "内网" in blocked("http://169.254.169.254/latest/meta-data")
assert "内网" in blocked("http://[::1]:5432/")
assert "10.0.0.5" in blocked("https://evil.example/")           # 解析出的任何一个是私网就拒
assert "172.18.0.3" in blocked("http://sandbox:9000/exec")      # Docker 服务名
assert "file:" in blocked("file:///etc/passwd")
assert "解析不了" in blocked("https://nowhere.example/")
assert blocked("https://nowhere.example/", unresolved_ok=True) is None
assert blocked("example.com/x") is None
assert blocked("http://nas.home/share") is None                 # 允许名单
assert run(web_guard.check("example.com/a")) == "https://example.com/a"

assert web_guard.github_raw("https://github.com/o/r/blob/main/src/a.py") == "https://raw.githubusercontent.com/o/r/main/src/a.py"
assert web_guard.github_raw("https://github.com/o/r/tree/main/src") == "https://github.com/o/r/tree/main/src"

# 限速：同一主机 60 秒 10 次，第 11 次等；过窗口恢复；别的主机不受影响
web_guard._hits.clear()
for i in range(10):
    assert web_guard.rate_wait("https://rl.example/a", now=100 + i) == 0
w = web_guard.rate_wait("https://rl.example/b", now=110)
assert 49 < w <= 50, w
assert web_guard.rate_wait("https://other.example/", now=110) == 0
assert web_guard.rate_wait("https://rl.example/c", now=161) == 0
web_guard._hits.clear()

# --- 传输层：每跳重定向都查；配代理（mounts）也查 ---
seen_hosts = []
def handler(req):
    seen_hosts.append(req.url.host)
    if req.url.path == "/go-internal":
        return httpx.Response(302, headers={"Location": "http://sandbox:9000/exec"})
    if req.url.path == "/go-ok":
        return httpx.Response(302, headers={"Location": "https://news.example/final"})
    return httpx.Response(200, text="ok")
async def via(url, **kw):
    async with web_guard.client(transport=httpx.MockTransport(handler), follow_redirects=True, **kw) as c:
        return await c.get(url)
assert run(via("https://example.com/go-ok")).text == "ok" and seen_hosts == ["example.com", "news.example"]
try:
    run(via("https://example.com/go-internal")); raise AssertionError("重定向进内网应被拦")
except web_guard.Blocked as e:
    assert "172.18.0.3" in str(e)
assert "sandbox" not in seen_hosts
c = web_guard.client(mounts={"all://": httpx.MockTransport(handler)})
assert all(isinstance(v, web_guard.SafeTransport) for v in c._mounts.values() if v is not None)
async def via_mount():
    async with c:
        return await c.get("http://localhost/")
try:
    run(via_mount()); raise AssertionError("代理 mounts 也要查")
except web_guard.Blocked:
    pass

# --- 读网页 ---
HTML = ("<html><head><title>九月天气回顾</title></head><body><nav>菜单</nav><article><h1>九月天气回顾</h1>"
        + "<p>" + "上海九月平均气温 26 度，降雨偏多。" * 20 + "</p></article></body></html>")
def pdf_bytes():
    from pypdf import PdfWriter
    w = PdfWriter(); w.add_blank_page(200, 200); w.add_blank_page(200, 200)
    b = io.BytesIO(); w.write(b); return b.getvalue()
PDF = pdf_bytes()
calls = []
def site(req):
    calls.append(str(req.url))
    p = req.url.path
    if p == "/page":
        return httpx.Response(200, html=HTML)
    if p == "/api.json":
        return httpx.Response(200, json={"price": 12.5, "名称": "牛奶"})
    if p == "/notes.txt":
        return httpx.Response(200, text="第一行\n第二行", headers={"content-type": "text/plain; charset=utf-8"})
    if p == "/doc.pdf":
        return httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"})
    if p == "/pic.zip":
        return httpx.Response(200, content=b"PK\x03\x04" + b"\x00\xff" * 100, headers={"content-type": "application/zip"})
    if p == "/huge.txt":
        return httpx.Response(200, content=b"a" * (web_page.MAX_BYTES + 1000), headers={"content-type": "text/plain"})
    if p == "/long.txt":
        return httpx.Response(200, text="字" * (web_page.MAX_CHARS + 50))
    if p == "/missing":
        return httpx.Response(404, html="<html><body><p>" + "页面不存在。" * 30 + "</p></body></html>")
    if p == "/slow":
        raise httpx.ReadTimeout("slow", request=req)
    if p == "/down":
        raise httpx.ConnectError("refused", request=req)
    if p == "/hop":
        return httpx.Response(301, headers={"Location": "http://10.0.0.8/admin"})
    if p.startswith("/o/r/main"):
        return httpx.Response(200, text="print('hi')", headers={"content-type": "text/plain"})
    return httpx.Response(200, text="x")
T = httpx.MockTransport(site)
F = lambda u, **kw: run(web_page.fetch(u, transport=T, **kw))
def ferr(u, **kw):
    try:
        F(u, **kw)
    except web_page.FetchError as e:
        return str(e)
    raise AssertionError(u)

pg = F("https://example.com/page")
assert pg.kind == "html" and pg.title == "九月天气回顾" and "26 度" in pg.text and "菜单" not in pg.text, pg
assert pg.for_model().startswith("地址：https://example.com/page\n标题：九月天气回顾"), pg.for_model()[:80]
assert pg.detail() == "example.com · 网页"
n = len(calls)
again = F("https://EXAMPLE.com/page/#top")           # 规范化后同一个键 → 缓存
assert again.cached and len(calls) == n and "秒前读过" in again.for_model() and again.detail().endswith("缓存")
fresh = F("https://example.com/page", max_age=0)      # 0 = 必须现读
assert not fresh.cached and len(calls) == n + 1
j = F("https://example.com/api.json")
assert j.kind == "json" and '"名称": "牛奶"' in j.text and '"price": 12.5' in j.text
t = F("https://example.com/notes.txt")
assert t.kind == "text" and t.text == "第一行\n第二行"
pd = F("https://example.com/doc.pdf")
assert pd.kind == "pdf" and "扫描件" in pd.text, pd.text
b = F("https://example.com/pic.zip")
assert b.kind == "binary" and "application/zip" in b.text and "\x00" not in b.text
h = F("https://example.com/huge.txt")
assert h.partial and h.truncated and "只读了前面" in h.for_model() and "已截断" in h.for_model()
ln = F("https://example.com/long.txt")
assert ln.truncated and len(ln.text) == web_page.MAX_CHARS and not ln.partial
m = F("https://example.com/missing")
assert m.status == 404 and "HTTP 404" in m.for_model()
n = len(calls); F("https://example.com/missing"); assert len(calls) == n + 1  # 错误页不缓存
web_guard._hits.clear()
assert "超时" in ferr("https://example.com/slow")
assert "连不上" in ferr("https://example.com/down")
assert "跳转到了不允许的地址" in ferr("https://example.com/hop")
assert "内网" in ferr("http://169.254.169.254/")
g = F("https://github.com/o/r/blob/main/a.py")
assert g.url == "https://raw.githubusercontent.com/o/r/main/a.py" and g.text == "print('hi')"
web_guard._hits.clear()
for i in range(web_guard.RATE_MAX):
    F(f"https://news.example/a{i}")
assert "太多次" in ferr("https://news.example/again")
web_guard._hits.clear()
assert web_page.normalize("HTTPS://A.com:443/x/?q=1#f") == "https://a.com/x?q=1"
assert web_page.normalize("http://a.com:8080/") == "http://a.com:8080/"

# --- 别的出网工具也过检查 ---
async def probe(u):
    async with web_guard.client(transport=httpx.MockTransport(lambda r: httpx.Response(200, headers={"content-type": "image/png"}))) as cl:
        return await display.probe_image(cl, u)
assert run(probe("https://img.example/a.png")) is True
assert run(probe("http://192.168.1.1/a.png")) is False         # 内网图片算打不开，不抛

ctx = NS(db=None, conversation_id="c0", task_id=None, live=lambda *a, **k: None)
async def call_api():
    from app import credentials
    real = credentials.resolve
    async def no_cred(db, url):
        return NS(headers={}, params={}, connection=None, scrub=[], source="")
    credentials.resolve = no_cred
    try:
        return await api_tool.api_request(ctx, url="https://rebind.example/admin")
    finally:
        credentials.resolve = real
load_builtin()
r = run(call_api())
assert r.failed and "127.0.0.1" in r.content, r
called = []
real_snap = browser_tool.browser_client.snapshot_call
async def no_browser(*a, **k):
    called.append(a); raise AssertionError("不该打开浏览器")
browser_tool.browser_client.snapshot_call = no_browser
r = run(browser_tool.browser_open(ctx, url="http://sandbox:9000/"))
assert r.failed and "172.18.0.3" in r.content and not called, r
browser_tool.browser_client.snapshot_call = real_snap

# --- 一轮对话 ---
assert "image_search" in REGISTRY and REGISTRY["image_search"].parallel
assert "image_search" in plan_mode.READ_TOOLS and "image_search" in subagent.CHILD_TOOLS
assert "image_search" in settings.system_prompt
assert REGISTRY["web_search"].parameters["properties"]["recent"]["enum"] == ["day", "week", "month", "year"]
searx_calls = []
async def fake_searx(params):
    searx_calls.append(params)
    if params.get("categories") == "images":
        return [{"title": "三花猫", "img_src": "https://img.example/cat.jpg", "thumbnail_src": "https://img.example/t.jpg",
                 "url": "https://img.example/post", "source": "img.example", "resolution": "800x600"},
                {"title": "重复", "img_src": "https://img.example/cat.jpg"},
                {"title": "坏的", "img_src": "javascript:alert(1)"},
                {"title": "协议相对", "img_src": "//cdn.example/c.png", "url": "https://cdn.example/p"}]
    return [{"title": "国庆出行", "url": "https://news.example/n1", "content": "高速免费", "publishedDate": "2026-10-08T09:00:00"}]
web_tools._searx = fake_searx
real_fetch = web_page.fetch
web_page.fetch = lambda url, max_age=None: real_fetch(url, max_age=max_age, transport=T)

script: list = []
tool_msgs: list[dict] = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    messages = [dict(m) for m in messages]
    tool_msgs.extend(m for m in messages if m["role"] == "tool" and m not in tool_msgs)
    step = script.pop(0)
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"c{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create

async def turn():
    script.extend([[("web_search", {"query": "国庆高速", "recent": "week"}),
                    ("image_search", {"query": "三花猫"}),
                    ("web_fetch", {"url": "https://example.com/api.json", "max_age_seconds": 0}),
                    ("web_fetch", {"url": "http://sandbox:9000/exec"})],
                   "好的。"])
    async with SessionLocal() as db:
        conv = Conversation(id="c1", title="t"); db.add(conv); await db.commit()
        db.add(Message(conversation_id="c1", role="user", blocks=text_to_blocks("查一下")))
        await db.commit()
        return await runner.run_turn(db, conv)
reply = run(turn())
steps = {}
for s in reply.steps:
    steps.setdefault(s["tool"], []).append(s)
ws = steps["web_search"][0]
assert ws["state"] == "done" and ws["detail"] == "国庆高速 · 一周内", ws
assert searx_calls[0] == {"q": "国庆高速", "time_range": "week"} or {"q": "国庆高速", "time_range": "week"} in searx_calls
im = steps["image_search"][0]
assert im["state"] == "done" and im["detail"] == "三花猫 · 2 张", im
f_ok, f_bad = steps["web_fetch"]
assert f_ok["state"] == "done" and f_ok["detail"] == "example.com · JSON", f_ok
assert f_bad["state"] == "error" and "172.18.0.3" in f_bad["note"], f_bad
contents = " | ".join(m["content"] for m in tool_msgs)
assert "（2026-10-08）" in contents and "图片：https://img.example/cat.jpg" in contents and "缩略图：https://img.example/t.jpg" in contents
assert "所在网页：https://img.example/post" in contents and "img.example · 800x600" in contents
assert "图片：https://cdn.example/c.png" in contents and "javascript" not in contents
assert '"名称": "牛奶"' in contents

print("smoke_web_access OK")
