"""端口预览的“绝对路径改写”——唯一规则处（v1.75）。

问题：预览挂在 /api/preview/<token>/ 下，但模型写的网页常引用以 / 开头的绝对路径（Vite/CRA 打包产物的
<script src="/assets/index-xx.js">、Angular 的 <base href="/">、页面里 fetch("/api/items")、React 渲染的 <img src="/logo.svg">、
Vite 开发服务器模块里的 import "/src/main.tsx"）。浏览器把它们发到 App 自己的根路径，资源 404、页面白屏。

对照：E2B / Codespaces / Gitpod 给每个端口一个子域名（要通配域名，用户还没有）；code-server 的 /absproxy 与
jupyter-server-proxy 的 absolute_url 要求应用自己配前缀（Vite --base 之类，token 每次签都变，模型配不准）。
结论：没有通配域名时由转发层改写——jupyter-server-proxy 的 rewrite_response 钩子思路，规则自己写：
  1. HTML：src/href/action/formaction/poster/data/background/manifest/xlink:href 与 srcset、meta refresh 里以 / 开头的
     路径补上前缀；<style>/style= 里的 url(/…) 一样；<head> 最前面注入一段小脚本（SHIM），运行时把
     fetch / XMLHttpRequest / WebSocket / EventSource / window.open / sendBeacon 和
     script.src、link.href、img.src… 的赋值与 setAttribute 里的根路径或“本域名 + 根路径”补上前缀。
     不碰 history.pushState（前端路由读 location.pathname 匹配路由，补了反而全不匹配）。
  2. CSS：url(/…) 与 @import "/…"。
  3. JS（ES 模块）：import "/x"、from "/x"、import("/x") 的说明符（模块导入没法在运行时拦）+ url(/…)。
  已带前缀（服务认 X-Forwarded-Prefix 自己生成的 /api/preview/…）、协议相对 //x、反斜杠开头的一律不动。
只改小于 REWRITE_MAX 的 html/css/js 正文；gzip/deflate（装了 brotli 时也认 br）先解开再改，改不了（编码不认、
字符集解不开、太大）就原样转发。settings.preview_rewrite = False 时整个关掉。

数据流：routes/preview.forward 拿到沙盒的流式响应 → wants(method, status, headers) → 要改就 collect(response, token)
→ (新响应头, 正文 bytes) 或 (原响应头, 原样的字节流)；之后统一过 preview.response_headers（CSP sandbox 等）。
"""
import json
import re
import zlib
from typing import AsyncIterator

from .config import settings

REWRITE_MAX = 4 * 1024 * 1024  # 原始（压缩后）字节上限；更大的不改，原样转发
DECODED_MAX = 16 * 1024 * 1024  # 解压后上限（防压缩炸弹）
MARK = "data-preview-shim"
PREFIX = "/api/preview/"

_HTML = ("text/html", "application/xhtml+xml")
_CSS = ("text/css",)
_JS = ("application/javascript", "text/javascript", "application/x-javascript", "application/ecmascript",
       "text/ecmascript", "module")

# 以 / 开头、但不是 //、/\、也不是已经带了预览前缀的路径
_ROOT = r"/(?![/\\])(?!api/preview/)"
_ATTR = re.compile(r"(?i)(\s(?:src|href|action|formaction|poster|data|background|manifest|xlink:href)\s*=\s*)([\"']?)"
                   + _ROOT)
_SRCSET = re.compile(r"(?i)(\ssrcset\s*=\s*)([\"'])(.*?)\2", re.S)
_SRCSET_ITEM = re.compile(r"(^|,)(\s*)" + _ROOT)
_REFRESH = re.compile(r"(?i)(<meta\b[^>]*?http-equiv\s*=\s*[\"']?refresh[^>]*?url\s*=\s*)([\"']?)" + _ROOT)
_CSS_URL = re.compile(r"(?i)(url\(\s*)([\"']?)" + _ROOT)
_CSS_IMPORT = re.compile(r"(?i)(@import\s+)([\"'])" + _ROOT)
_JS_IMPORT = re.compile(r"(\bimport\s*\(\s*|\bfrom\s*|\bimport\s*)([\"'])" + _ROOT)
_META_CHARSET = re.compile(rb"(?i)<meta\b[^>]*?charset\s*=\s*[\"']?\s*([\w.:-]+)")
_HEAD = re.compile(r"(?i)<head\b[^>]*>")
_HTML_TAG = re.compile(r"(?i)<html\b[^>]*>")
_DOCTYPE = re.compile(r"(?i)^\s*<!doctype[^>]*>")
_CHARSET_TAG = re.compile(r"(?i)<meta\b[^>]*?charset\s*=[^>]*>")


def kind(content_type: str) -> str | None:
    """Content-Type → html | css | js | None（别的不改）。"""
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime in _HTML:
        return "html"
    if mime in _CSS:
        return "css"
    if mime in _JS:
        return "js"
    return None


def charset_of(content_type: str) -> str | None:
    m = re.search(r"(?i)charset\s*=\s*[\"']?([\w.:-]+)", content_type or "")
    return m.group(1).lower() if m else None


def _base(token: str) -> str:
    return f"{PREFIX}{token}/"


def _sub(rx: re.Pattern, text: str, base: str) -> str:
    return rx.sub(lambda m: m.group(1) + m.group(2) + base, text)


def rewrite_css(text: str, base: str) -> str:
    return _sub(_CSS_IMPORT, _sub(_CSS_URL, text, base), base)


def rewrite_js(text: str, base: str) -> str:
    return _sub(_CSS_URL, _sub(_JS_IMPORT, text, base), base)


def _srcset(m: re.Match, base: str) -> str:
    return m.group(1) + m.group(2) + _SRCSET_ITEM.sub(lambda i: i.group(1) + i.group(2) + base, m.group(3)) + m.group(2)


def shim(base: str) -> str:
    """注入页面最前面的运行时补丁（ES5，不依赖任何东西；每个补丁 try 包住，坏一个不影响页面）。"""
    return ("<script " + MARK + ">(function(){var B=" + json.dumps(base) + ",P=" + json.dumps(PREFIX) + ";"
            "function fx(u){if(typeof u!=='string')return u;"
            "if(u.charAt(0)==='/'){var c=u.charAt(1);if(c==='/'||c==='\\\\')return u;return u.indexOf(P)===0?u:B+u.slice(1)}"
            "var m=/^(https?:|wss?:)\\/\\/([^\\/?#]*)(.*)$/i.exec(u);"
            "if(m&&m[2].replace(/:$/,'')===location.host){var p=m[3]||'/';if(p.charAt(0)!=='/')p='/'+p;"
            "return p.indexOf(P)===0?u:m[1]+'//'+location.host+B+p.slice(1)}return u}"
            "function fa(u){try{return(typeof URL!=='undefined'&&u instanceof URL)?fx(u.href):fx(u)}catch(e){return u}}"
            "function tr(f){try{f()}catch(e){}}var w=window;"
            "tr(function(){var F=w.fetch;if(!F)return;w.fetch=function(i,o){try{if(typeof Request!=='undefined'&&i instanceof Request)"
            "{var n=fx(i.url);if(n!==i.url)i=new Request(n,i)}else i=fa(i)}catch(e){}return F.call(this,i,o)}});"
            "tr(function(){var X=w.XMLHttpRequest.prototype,O=X.open;X.open=function(){var a=[].slice.call(arguments);"
            "a[1]=fa(a[1]);return O.apply(this,a)}});"
            "function wrap(n){tr(function(){var C=w[n];if(!C)return;var W=function(u,p){return arguments.length>1?new C(fa(u),p):new C(fa(u))};"
            "W.prototype=C.prototype;if(Object.setPrototypeOf)Object.setPrototypeOf(W,C);w[n]=W})}"
            "wrap('WebSocket');wrap('EventSource');"
            "tr(function(){var O=w.open;if(O)w.open=function(u){var a=[].slice.call(arguments);a[0]=fa(u);return O.apply(this,a)}});"
            "tr(function(){var n=w.navigator,S=n&&n.sendBeacon;if(S)n.sendBeacon=function(u,d){return S.call(n,fa(u),d)}});"
            "function prop(t,a){tr(function(){var T=w[t];if(!T)return;var d=Object.getOwnPropertyDescriptor(T.prototype,a);"
            "if(!d||!d.set)return;Object.defineProperty(T.prototype,a,{configurable:true,enumerable:d.enumerable,get:d.get,"
            "set:function(v){d.set.call(this,fa(v))}})})}"
            "prop('HTMLScriptElement','src');prop('HTMLLinkElement','href');prop('HTMLImageElement','src');"
            "prop('HTMLIFrameElement','src');prop('HTMLSourceElement','src');prop('HTMLMediaElement','src');"
            "prop('HTMLAnchorElement','href');prop('HTMLFormElement','action');"
            "tr(function(){var E=w.Element.prototype,S=E.setAttribute,A={src:1,href:1,action:1,formaction:1,poster:1};"
            "E.setAttribute=function(n,v){if(typeof v==='string'&&A[String(n).toLowerCase()])v=fx(v);return S.call(this,n,v)}});"
            "})();</script>")


def inject(html: str, base: str) -> str:
    """补丁脚本放进 <head> 最前（有 <meta charset> 就紧跟其后）；没有 head 就跟在 <html>/doctype 后；已注入过不再注入。"""
    if MARK in html:
        return html
    tag = shim(base)
    head = _HEAD.search(html)
    if head:
        at = head.end()
        cs = _CHARSET_TAG.search(html, at)
        close = html.lower().find("</head>", at)
        if cs and (close < 0 or cs.start() < close) and not html[at:cs.start()].lower().count("<script"):
            at = cs.end()
        return html[:at] + tag + html[at:]
    for rx in (_HTML_TAG, _DOCTYPE):
        m = rx.search(html)
        if m:
            return html[:m.end()] + tag + html[m.end():]
    return tag + html


def rewrite_html(text: str, base: str) -> str:
    text = _sub(_ATTR, text, base)
    text = _SRCSET.sub(lambda m: _srcset(m, base), text)
    text = _sub(_REFRESH, text, base)
    text = rewrite_css(text, base)  # <style> / style="" 里的 url()
    return inject(text, base)


def rewrite(k: str, text: str, token: str) -> str:
    base = _base(token)
    if k == "html":
        return rewrite_html(text, base)
    if k == "css":
        return rewrite_css(text, base)
    return rewrite_js(text, base)


# ---- 响应 ----
def wants(method: str, status: int, headers) -> str | None:
    """这条响应要不要改 → kind 或 None。HEAD、204/304、没正文、事件流、关掉开关都不改；Content-Length 已知且太大也不改。"""
    if not settings.preview_rewrite or method.upper() == "HEAD" or status in (204, 304) or 100 <= status < 200:
        return None
    k = kind(headers.get("content-type", ""))
    if k is None:
        return None
    n = headers.get("content-length")
    if n and n.isdigit() and int(n) > REWRITE_MAX:
        return None
    if _decoder(headers.get("content-encoding", "")) is False:
        return None
    return k


def _decoder(encoding: str):
    """→ 解码函数；None = 不用解；False = 认不了（原样转发）。"""
    enc = [e.strip().lower() for e in (encoding or "").split(",") if e.strip() and e.strip().lower() != "identity"]
    if not enc:
        return None
    if len(enc) > 1:
        return False
    e = enc[0]
    if e in ("gzip", "x-gzip"):
        return lambda b: _bounded(zlib.decompressobj(16 + zlib.MAX_WBITS), b)
    if e == "deflate":
        def inflate(b: bytes) -> bytes:
            try:
                return _bounded(zlib.decompressobj(), b)
            except zlib.error:
                return _bounded(zlib.decompressobj(-zlib.MAX_WBITS), b)  # 裸 deflate（不带 zlib 头）
        return inflate
    if e == "br":
        try:
            import brotli  # type: ignore
        except ImportError:
            return False
        return lambda b: _check(brotli.decompress(b))
    return False


def _bounded(d, b: bytes) -> bytes:
    out = d.decompress(b, DECODED_MAX + 1)
    if d.unconsumed_tail or len(out) > DECODED_MAX:
        raise ValueError("too big")
    return out


def _check(b: bytes) -> bytes:
    if len(b) > DECODED_MAX:
        raise ValueError("too big")
    return b


def _decode_text(raw: bytes, content_type: str, k: str) -> tuple[str, str] | None:
    cs = charset_of(content_type)
    if cs is None and k == "html":
        m = _META_CHARSET.search(raw[:4096])
        cs = m.group(1).decode("ascii", "ignore").lower() if m else None
    cs = cs or "utf-8"
    if raw.startswith(b"\xef\xbb\xbf") and cs.replace("-", "") == "utf8":
        raw, cs = raw[3:], "utf-8-sig"
    try:
        return raw.decode(cs), cs
    except (LookupError, UnicodeDecodeError):
        return None


async def _rest(head: list[bytes], it: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    for b in head:
        yield b
    async for b in it:
        yield b


async def collect(r, k: str, token: str) -> tuple[list[tuple[str, str]], bytes | AsyncIterator[bytes]]:
    """读上游正文（最多 REWRITE_MAX 原始字节）→ 改写后的 (头, bytes)；读超了 / 解不开 → (原头, 原样字节流)。
    r 是还没读正文的 httpx 流式响应；调用方负责 aclose()。"""
    items = list(r.headers.multi_items())
    it = r.aiter_raw()
    chunks, size = [], 0
    async for b in it:
        chunks.append(b)
        size += len(b)
        if size > REWRITE_MAX:
            return items, _rest(chunks, it)
    raw = b"".join(chunks)

    async def same():
        yield raw

    dec = _decoder(r.headers.get("content-encoding", ""))
    try:
        body = dec(raw) if dec else raw
    except Exception:  # zlib.error / 炸弹 / brotli.error：原样转发
        return items, same()
    ctype = r.headers.get("content-type", "")
    got = _decode_text(body, ctype, k)
    if got is None:
        return items, same()
    text, cs = got
    out = rewrite(k, text, token)
    enc = "utf-8" if cs == "utf-8-sig" else cs
    mime = ctype.split(";", 1)[0].strip() or "text/html"
    keep = [(h, v) for h, v in items if h.lower() not in ("content-encoding", "content-length", "content-type", "content-md5")]
    return keep + [("Content-Type", f"{mime}; charset={enc}")], out.encode(enc, "xmlcharrefreplace" if k == "html" else "strict")
