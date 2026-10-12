# 冒烟：v1.75 端口预览改写绝对路径（app/preview_rewrite.py + routes/preview.forward）。
# 1) 规则表：HTML 属性 / srcset / meta refresh / <base href="/"> / style url()；CSS url() 与 @import；JS 模块导入说明符；
#    已带前缀、//、/\ 不动；补丁脚本放在 <head>（或 meta charset 后）最前、只注入一次；
# 2) wants：HEAD/204/304/非文本/太大/认不了的编码/开关关 → 不改；
# 3) 经真路由（沙盒响应换成假的流）：Vite 打包的 index.html（gzip）改写 + 去掉 Content-Encoding + 带 charset + Content-Length 对；
#    CSS/JS 改写；图片、超过 REWRITE_MAX 的 JS 原样流式转发；GBK 页面按 meta charset 解开再编回；坏 gzip 原样；关开关原样；
# 4) 补丁脚本在 node 里跑（假 window）：fetch/XHR/WebSocket/EventSource/open/sendBeacon/src 赋值/setAttribute 都补前缀，
#    同域完整 URL 也补，外域、已带前缀、相对路径、// 不动。
# 运行：env -u HTTP_PROXY -u HTTPS_PROXY python tests/smoke_preview_rewrite.py
import os, sys, json, gzip, tempfile, subprocess, shutil

tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]',
  SANDBOX_URL="http://127.0.0.1:9", SANDBOX_TOKEN="t", PUBLIC_URL="https://me.example", NO_PROXY="*")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

import httpx
from app import preview, preview_rewrite as pr, sandbox_client
from app.config import settings

TOK = "me.8000.1999999999.sig"
B = f"/api/preview/{TOK}/"

# 1) 规则
html = ('<!doctype html><html><head><meta charset="utf-8"><title>x</title>'
        '<base href="/"><script type="module" crossorigin src="/assets/index-a1.js"></script>'
        '<link rel="stylesheet" href="/assets/index-b2.css"><link rel="icon" href=/favicon.ico></head>'
        '<body style="background:url(\'/bg.png\')"><img src="/logo.svg" srcset="/a.png 1x, /b.png 2x, c.png 3x">'
        '<a href="//cdn.example/x">cdn</a><a href="https://other.example/y">o</a><a href="rel/z">r</a>'
        f'<a href="{B}already">p</a><form action="/submit"><button formaction="/alt"></button></form>'
        '<meta http-equiv="refresh" content="5; url=/next"><video poster="/p.jpg"></video>'
        '<a href="/\\evil">bs</a><p>price /5 dollars</p></body></html>')
out = pr.rewrite("html", html, TOK)
for frag in (f'<base href="{B}">', f'src="{B}assets/index-a1.js"', f'href="{B}assets/index-b2.css"', f'href={B}favicon.ico',
             f"url('{B}bg.png')", f'src="{B}logo.svg"', f'srcset="{B}a.png 1x, {B}b.png 2x, c.png 3x"',
             f'action="{B}submit"', f'formaction="{B}alt"', f'url={B}next"', f'poster="{B}p.jpg"'):
    assert frag in out, (frag, out)
for keep in ('href="//cdn.example/x"', 'href="https://other.example/y"', 'href="rel/z"', f'href="{B}already"',
             'href="/\\evil"', "price /5 dollars"):
    assert keep in out, (keep, out)
assert out.count(pr.MARK) == 1 and pr.rewrite("html", out, TOK).count(pr.MARK) == 1, "只注入一次"
i_meta, i_shim, i_script = out.index('<meta charset="utf-8">'), out.index(pr.MARK), out.index("index-a1.js")
assert i_meta < i_shim < i_script, "补丁跟在 meta charset 后、在任何脚本前"
assert pr.inject("<p>x</p>", B).startswith("<script " + pr.MARK)
assert pr.inject("<!DOCTYPE html><p>x</p>", B).startswith("<!DOCTYPE html><script")
assert pr.inject("<html lang=zh><body>", B).startswith("<html lang=zh><script")
h2 = pr.inject('<head><script>var a=1</script><meta charset="utf-8"></head>', B)
assert h2.index(pr.MARK) < h2.index("var a"), "head 里先有脚本：补丁放 head 最前"

css = '@import "/base.css";@import url(/x.css);.a{background:url( "/i.png")}.b{src:url(data:a/b,x)}.c{background:url(//cdn/x.png)}'
c = pr.rewrite("css", css, TOK)
assert f'@import "{B}base.css"' in c and f"url({B}x.css)" in c and f'url( "{B}i.png")' in c, c
assert "url(data:a/b,x)" in c and "url(//cdn/x.png)" in c

js = ('import React from "/node_modules/.vite/deps/react.js";import "/src/index.css";'
      "import{a}from'/src/a.ts';export*from \"/src/b.ts\";const m=import( '/src/lazy.tsx');"
      'const r="/api/items";router.get("/");Array.from("/x");const s=`url(/img/a.png)`;import x from "./rel.js";')
j = pr.rewrite("js", js, TOK)
for frag in (f'from "{B}node_modules/.vite/deps/react.js"', f'import "{B}src/index.css"', f"from'{B}src/a.ts'",
             f'from "{B}src/b.ts"', f"import( '{B}src/lazy.tsx')", f"url({B}img/a.png)"):
    assert frag in j, (frag, j)
assert 'const r="/api/items"' in j and 'router.get("/")' in j and 'Array.from("/x")' in j and 'from "./rel.js"' in j, j

assert pr.kind("text/html; charset=UTF-8") == "html" and pr.kind("text/css") == "css"
assert pr.kind("application/javascript") == "js" and pr.kind("image/png") is None and pr.kind("") is None
assert pr.charset_of("text/html; charset=\"GBK\"") == "gbk" and pr.charset_of("text/html") is None

# 2) wants
H = lambda **kw: httpx.Headers({k.replace("_", "-"): v for k, v in kw.items()})
assert pr.wants("GET", 200, H(content_type="text/html")) == "html"
assert pr.wants("HEAD", 200, H(content_type="text/html")) is None
assert pr.wants("GET", 304, H(content_type="text/html")) is None
assert pr.wants("GET", 200, H(content_type="image/png")) is None
assert pr.wants("GET", 200, H(content_type="text/event-stream")) is None
assert pr.wants("GET", 200, H(content_type="text/css", content_length=str(pr.REWRITE_MAX + 1))) is None
assert pr.wants("GET", 200, H(content_type="text/css", content_encoding="gzip")) == "css"
assert pr.wants("GET", 200, H(content_type="text/css", content_encoding="zstd")) is None
assert pr.wants("GET", 200, H(content_type="text/css", content_encoding="gzip, gzip")) is None
assert pr.wants("GET", 404, H(content_type="text/html")) == "html", "服务自己的错误页也改"
settings.preview_rewrite = False
assert pr.wants("GET", 200, H(content_type="text/html")) is None
settings.preview_rewrite = True

# 3) 经真路由
class Stream(httpx.AsyncByteStream):
    def __init__(self, data: bytes, size: int = 7000):
        self.parts = [data[i:i + size] for i in range(0, len(data), size)] or [b""]
        self.closed = False

    async def __aiter__(self):
        for p in self.parts:
            yield p

    async def aclose(self):
        self.closed = True


served: dict = {}
streams: list = []


async def fake_send(ws, port, method, path, query, headers, body):
    status, hdrs, data = served[path]
    s = Stream(data)
    streams.append(s)
    return httpx.Response(status, headers=[*hdrs, ("x-sandbox-preview", "1")], stream=s,
                          request=httpx.Request(method, "http://sbx/" + path))

sandbox_client.preview_send = fake_send
tok, _ = preview.sign("me", 8000)
BB = f"/api/preview/{tok}/"
vite = ('<!doctype html><html lang="en"><head><meta charset="UTF-8" /><title>Vite + React</title>'
        '<script type="module" crossorigin src="/assets/index-DiwrgTda.js"></script>'
        '<link rel="stylesheet" crossorigin href="/assets/index-D8b4DHJx.css"></head><body><div id="root"></div></body></html>')
served["index.html"] = (200, [("Content-Type", "text/html"), ("Content-Encoding", "gzip"), ("ETag", '"abc"')],
                        gzip.compress(vite.encode()))
served["assets/index-D8b4DHJx.css"] = (200, [("Content-Type", "text/css; charset=utf-8")], b".l{background:url(/assets/react.svg)}")
served["assets/index-DiwrgTda.js"] = (200, [("Content-Type", "text/javascript")], b'import"/assets/vendor.js";const i="/vite.svg";')
png = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 50
served["logo.png"] = (200, [("Content-Type", "image/png")], png)
big = b"/*" + b"x" * (pr.REWRITE_MAX + 10) + b'*/import "/a.js";'
served["big.js"] = (200, [("Content-Type", "application/javascript")], big)
gbk = '<html><head><meta charset="gbk"><title>记账</title></head><body><img src="/记账.png">中文</body></html>'.encode("gbk")
served["gbk.html"] = (200, [("Content-Type", "text/html")], gbk)
served["bad.html"] = (200, [("Content-Type", "text/html"), ("Content-Encoding", "gzip")], b"not gzip at all <a href=/x>")
served["head.html"] = (200, [("Content-Type", "text/html")], vite.encode())

from fastapi.testclient import TestClient
from app.main import app as main_app

with TestClient(main_app) as cl:
    r = cl.get(BB + "index.html")
    assert r.status_code == 200, (r.status_code, r.text[:300])
    assert "content-encoding" not in r.headers and r.headers["content-type"] == "text/html; charset=utf-8", r.headers
    assert int(r.headers["content-length"]) == len(r.content), "Content-Length 与改写后的正文一致"
    assert f'src="{BB}assets/index-DiwrgTda.js"' in r.text and f'href="{BB}assets/index-D8b4DHJx.css"' in r.text, r.text
    assert pr.MARK in r.text and "sandbox allow-scripts" in r.headers["content-security-policy"], "CSP 仍在"
    assert r.headers.get("etag") == '"abc"'
    r = cl.get(BB + "assets/index-D8b4DHJx.css")
    assert r.text == f".l{{background:url({BB}assets/react.svg)}}", r.text
    r = cl.get(BB + "assets/index-DiwrgTda.js")
    assert r.text == f'import"{BB}assets/vendor.js";const i="/vite.svg";', r.text
    assert r.headers["content-type"] == "text/javascript; charset=utf-8"
    r = cl.get(BB + "logo.png")
    assert r.content == png and "content-length" not in r.headers or r.content == png, "图片原样"
    r = cl.get(BB + "big.js")
    assert r.content == big, "太大的原样流式转发（一个字节不少）"
    r = cl.get(BB + "gbk.html")
    assert r.headers["content-type"] == "text/html; charset=gbk", r.headers
    t = r.content.decode("gbk")
    assert f'src="{BB}记账.png"' in t and "中文" in t and pr.MARK in t, t
    with cl.stream("GET", BB + "bad.html") as r:
        raw = b"".join(r.iter_raw())
        assert raw == b"not gzip at all <a href=/x>" and r.headers.get("content-encoding") == "gzip", "坏 gzip 原样"
    r = cl.head(BB + "head.html")
    assert r.status_code == 200 and r.content == b""
    settings.preview_rewrite = False
    r = cl.get(BB + "head.html")
    assert r.content == vite.encode(), "开关关了原样"
    settings.preview_rewrite = True
assert streams and all(s.closed for s in streams), "每条上游流都关了"

# 4) 补丁脚本在 node 里跑
node = shutil.which("node")
if node:
    js_shim = pr.shim(B)[len("<script " + pr.MARK + ">"):-len("</script>")]
    harness = r"""
const log = [];
function El(){ this.attrs = {}; }
El.prototype.setAttribute = function(n, v){ this.attrs[n] = v; };
function mk(name, attr){ const C = function(){ El.call(this); }; C.prototype = Object.create(El.prototype);
  Object.defineProperty(C.prototype, attr, {configurable: true, enumerable: true,
    get(){ return this['_' + attr]; }, set(v){ this['_' + attr] = v; }}); return C; }
class WS { constructor(u, p){ this.u = u; this.p = p; } } WS.OPEN = 1;
class ES { constructor(u){ this.u = u; } }
function XHR(){} XHR.prototype.open = function(m, u, a){ this.m = m; this.u = u; this.a = a; };
class Req { constructor(u, init){ this.url = (u instanceof Req) ? u.url : (u.startsWith('/') ? 'https://me.example' + u : u); } }
const window = { location: { host: 'me.example' }, XMLHttpRequest: XHR, WebSocket: WS, EventSource: ES,
  fetch: (i) => { log.push(i instanceof Req ? 'R:' + i.url : i); return 'ok'; },
  open: (u, t) => { log.push('open:' + u + ':' + t); },
  navigator: { sendBeacon: function(u){ log.push('beacon:' + u + ':' + (this === window.navigator)); return true; } },
  Element: El, HTMLScriptElement: mk('S', 'src'), HTMLLinkElement: mk('L', 'href'), HTMLImageElement: mk('I', 'src'),
  HTMLAnchorElement: mk('A', 'href') };
global.window = window; global.location = window.location; global.Request = Req; global.URL = URL;
eval(SHIM);
const B = BASE, out = {};
window.fetch('/api/items'); window.fetch('api/rel'); window.fetch('https://me.example/x?y=1');
window.fetch('https://other.example/z'); window.fetch(B + 'already'); window.fetch(new Req('/via-request'));
window.fetch(new URL('https://me.example/u')); window.fetch('//cdn.example/a');
out.fetch = log.splice(0);
const x = new window.XMLHttpRequest(); x.open('GET', '/xhr', true); out.xhr = [x.u, x.a];
const w = new window.WebSocket('wss://me.example/ws', ['p1']); out.ws = [w.u, w.p, w instanceof WS, window.WebSocket.OPEN];
const w2 = new window.WebSocket('wss://me.example:/'); out.ws2 = w2.u;
out.es = new window.EventSource('/events').u;
window.open('/pop', '_blank'); window.navigator.sendBeacon('/b', 'd'); out.misc = log.splice(0);
const s = new window.HTMLScriptElement(); s.src = '/chunk.js'; const l = new window.HTMLLinkElement(); l.href = '/a.css';
const a = new window.HTMLAnchorElement(); a.href = '#top'; const im = new window.HTMLImageElement();
im.setAttribute('src', '/logo.svg'); im.setAttribute('alt', '/not-a-url'); im.setAttribute('SRC', 'https://me.example/i.png');
out.props = [s.src, l.href, a.href, im.attrs.src, im.attrs.alt, im.attrs.SRC];
console.log(JSON.stringify(out));
"""
    prog = f"const SHIM = {json.dumps(js_shim)}; const BASE = {json.dumps(B)};\n" + harness
    res = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    o = json.loads(res.stdout)
    H = "https://me.example"
    assert o["fetch"] == [B + "api/items", "api/rel", f"{H}{B}x?y=1", "https://other.example/z", B + "already",
                          f"R:{H}{B}via-request", f"{H}{B}u", "//cdn.example/a"], o["fetch"]
    assert o["xhr"] == [B + "xhr", True], o["xhr"]
    assert o["ws"] == [f"wss://me.example{B}ws", ["p1"], True, 1], o["ws"]
    assert o["ws2"] == f"wss://me.example{B}", o["ws2"]
    assert o["es"] == B + "events"
    assert o["misc"] == [f"open:{B}pop:_blank", f"beacon:{B}b:true"], o["misc"]
    assert o["props"] == [B + "chunk.js", B + "a.css", "#top", B + "logo.svg", "/not-a-url", f"{H}{B}i.png"], o["props"]
    print("node shim ok")
else:
    print("node 不在，跳过补丁脚本运行测试")

print("smoke_preview_rewrite ok")
