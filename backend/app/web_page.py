"""web_fetch 读一个网址——唯一的规则：取回什么、怎么变成给模型的正文、什么时候用缓存。

- 地址先过 web_guard（协议、内网、每跳重定向）；github.com/…/blob/… 换成 raw（Gemini convertGithubUrlToRaw）；
- 同一主机一分钟最多 RATE_MAX 次（Gemini checkRateLimit），超了告诉模型等几秒，不去真请求；
- 边读边数字节，超过 MAX_BYTES 就停（Gemini MAX_EXPERIMENTAL_FETCH_SIZE 10MB；小 VPS 取 5MB），按已读部分处理并注明；
- 按类型变成正文：HTML → trafilatura 提正文（带标题）；JSON → 原样缩进；text/* 与 XML → 原样；
  PDF → pypdf 逐页抽文字，带“第 N 页”标记，没文字的页注明（多半是扫描件）；图片 / 压缩包等 → 说明类型与大小，不塞进上下文；
- 正文给模型最多 MAX_CHARS 字，超出注明已截断（调用方可用 limit 要更长的正文，如 extract 结构化提取最多 extract.SOURCE_MAX）；
- 缓存：同一规范化地址 CACHE_TTL 秒内再读直接用（max_age 可以更短，0 = 必须现读）；最多 CACHE_MAX 条（LRU）。"""
import io
import json
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from urllib.parse import urlsplit, urlunsplit

import httpx
import trafilatura

from . import web_guard

MAX_BYTES = 5 * 1024 * 1024
MAX_CHARS = 8000      # 控制 token 成本
PDF_PAGES = 50        # PDF 最多抽前几页
TIMEOUT = 20
CACHE_TTL = 900
CACHE_MAX = 64
UA = "Mozilla/5.0 (compatible; assistant-fetch/1.0)"
TEXT_TYPES = ("application/json", "application/xml", "application/rss+xml", "application/atom+xml",
              "application/javascript", "application/x-yaml", "application/yaml", "application/x-ndjson")


class FetchError(Exception):
    """读不到（原因是给模型看的中文）。"""


@dataclass(frozen=True)
class Page:
    url: str          # 最后落到的地址（跟随重定向后）
    kind: str         # html | json | text | pdf | binary
    text: str         # 给模型的正文（已截断）
    title: str = ""
    truncated: bool = False
    partial: bool = False   # 超过 MAX_BYTES 只读了前面
    status: int = 200
    cached: bool = False
    fetched_at: float = 0.0

    def for_model(self) -> str:
        head = [f"地址：{self.url}"] + ([f"标题：{self.title}"] if self.title else [])
        if self.status >= 400:
            head.append(f"HTTP {self.status}（对方返回了错误页，下面是错误页的内容）")
        if self.cached:
            head.append(f"（{int(time.time() - self.fetched_at)} 秒前读过，用的缓存）")
        tail = []
        if self.partial:
            tail.append(f"…（文件超过 {MAX_BYTES // (1024 * 1024)}MB，只读了前面一部分）")
        if self.truncated:
            tail.append("…（已截断）")
        return "\n".join(head) + "\n\n" + self.text + ("\n" + "\n".join(tail) if tail else "")

    def detail(self) -> str:
        host = urlsplit(self.url).hostname or self.url
        label = {"html": "网页", "json": "JSON", "text": "文本", "pdf": "PDF", "binary": "文件"}[self.kind]
        return f"{host} · {label}" + (" · 缓存" if self.cached else "")


def normalize(url: str) -> str:
    """缓存键：主机小写、去默认端口、去尾斜杠（根除外）、去 #片段（Gemini normalizeUrl）。"""
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    port = p.port
    if port and not ((p.scheme == "http" and port == 80) or (p.scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    path = p.path[:-1] if len(p.path) > 1 and p.path.endswith("/") else p.path
    return urlunsplit((p.scheme.lower(), host, path, p.query, ""))


_cache: "OrderedDict[str, Page]" = OrderedDict()


def _cached(key: str, max_age: int | None, chars: int = MAX_CHARS) -> Page | None:
    page = _cache.get(key)
    if page is None:
        return None
    if page.truncated and len(page.text) < chars:  # 缓存里存的是更短的截断版，满足不了这次要的长度 → 现读
        return None
    age = time.time() - page.fetched_at
    limit = CACHE_TTL if max_age is None else min(CACHE_TTL, max(0, max_age))
    if age > limit:
        return None
    _cache.move_to_end(key)
    return replace(page, cached=True, text=page.text[:chars], truncated=page.truncated or len(page.text) > chars)


def _store(key: str, page: Page) -> None:
    _cache[key] = page
    _cache.move_to_end(key)
    while len(_cache) > CACHE_MAX:
        _cache.popitem(last=False)


def _kind(ctype: str, body: bytes, url: str) -> str:
    c = ctype.split(";")[0].strip().lower()
    if c == "application/pdf" or body[:5] == b"%PDF-" or (not c and url.lower().endswith(".pdf")):
        return "pdf"
    if c in ("text/html", "application/xhtml+xml") or (not c and body.lstrip()[:1] == b"<"):
        return "html"
    if c == "application/json" or c.endswith("+json"):
        return "json"
    if c.startswith("text/") or c in TEXT_TYPES or c.endswith("+xml"):
        return "text"
    if not c:
        try:
            body[:2000].decode("utf-8")
            return "text"
        except UnicodeDecodeError:
            return "binary"
    return "binary"


def _decode(body: bytes, ctype: str) -> str:
    charset = "utf-8"
    for part in ctype.split(";")[1:]:
        k, _, v = part.strip().partition("=")
        if k.lower() == "charset" and v:
            charset = v.strip('"\' ')
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def _pdf(body: bytes) -> str:
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(body))
        pages = reader.pages
    except Exception as e:  # pypdf 对坏文件抛各种异常
        raise FetchError(f"这个 PDF 打不开（{e.__class__.__name__}），可能文件不完整或加密了。") from e
    out, blank = [], []
    for i, p in enumerate(pages[:PDF_PAGES], 1):
        try:
            t = (p.extract_text() or "").strip()
        except Exception:
            t = ""
        if t:
            out.append(f"--- 第 {i} 页 ---\n{t}")
        else:
            blank.append(i)
    note = []
    if blank:
        note.append(f"（第 {', '.join(map(str, blank[:20]))}{'…' if len(blank) > 20 else ''} 页没有可提取的文字，可能是扫描图片）")
    if len(pages) > PDF_PAGES:
        note.append(f"（共 {len(pages)} 页，只抽了前 {PDF_PAGES} 页）")
    if not out:
        return "这个 PDF 没有可提取的文字（多半是扫描件）。" + "".join(note[1:])
    return "\n\n".join(out) + ("\n" + "\n".join(note) if note else "")


def to_text(body: bytes, ctype: str, url: str) -> tuple[str, str, str]:
    """(kind, 正文, 标题)。"""
    kind = _kind(ctype, body, url)
    if kind == "pdf":
        return kind, _pdf(body), ""
    if kind == "binary":
        c = ctype.split(";")[0].strip() or "未知类型"
        return kind, f"这是 {c} 文件（{len(body)} 字节），不是文字，没有放进上下文。要处理它就用 run_command 下载到工作区。", ""
    raw = _decode(body, ctype)
    if kind == "json":
        try:
            return kind, json.dumps(json.loads(raw), ensure_ascii=False, indent=1), ""
        except ValueError:
            return "text", raw, ""
    if kind == "text":
        return kind, raw, ""
    text = trafilatura.extract(raw, include_links=False, url=url) or ""
    title = ""
    try:
        meta = trafilatura.extract_metadata(raw)
        title = (meta.title or "").strip() if meta else ""
    except Exception:
        title = ""
    if not text:
        text = "这个页面提取不到正文（可能要 JavaScript 渲染或登录）。需要的话用 browser_open 打开看。"
    return "html", text, title


async def _download(url: str, transport: httpx.AsyncBaseTransport | None) -> tuple[bytes, str, str, int, bool]:
    async with web_guard.client(transport=transport, timeout=TIMEOUT, follow_redirects=True,
                                headers={"User-Agent": UA}) as c:
        async with c.stream("GET", url) as r:
            buf, partial = bytearray(), False
            async for chunk in r.aiter_bytes():
                buf += chunk
                if len(buf) > MAX_BYTES:
                    del buf[MAX_BYTES:]
                    partial = True
                    break
            return bytes(buf), r.headers.get("content-type", ""), str(r.url), r.status_code, partial


async def fetch(url: str, max_age: int | None = None, transport: httpx.AsyncBaseTransport | None = None,
                limit: int = MAX_CHARS) -> Page:
    """limit = 正文最多多少字（默认 MAX_CHARS 给模型直接看；结构化提取要整篇时给更大值）。"""
    url = (url or "").strip()
    try:
        url = await web_guard.check(web_guard.github_raw(url if "://" in url else "https://" + url))
    except web_guard.Blocked as e:
        raise FetchError(str(e)) from e
    key = normalize(url)
    hit = _cached(key, max_age, limit)
    if hit is not None:
        return hit
    wait = web_guard.rate_wait(url)
    if wait > 0:
        raise FetchError(f"一分钟内读这个网站太多次了，{int(wait) + 1} 秒后再试，或者先用已经读到的内容。")
    try:
        body, ctype, final, status, partial = await _download(url, transport)
    except web_guard.Blocked as e:  # 重定向跳到了内网
        raise FetchError(f"这个网址跳转到了不允许的地址：{e}") from e
    except httpx.TimeoutException as e:
        raise FetchError(f"读取超时（{TIMEOUT} 秒）。网站可能很慢，可以稍后再试或换个来源。") from e
    except httpx.TooManyRedirects as e:
        raise FetchError("重定向太多次，读不到。") from e
    except httpx.HTTPError as e:
        raise FetchError(f"连不上这个网站（{e.__class__.__name__}）。") from e
    kind, text, title = to_text(body, ctype, final)
    page = Page(url=final, kind=kind, text=text[:limit], title=title, truncated=len(text) > limit,
                partial=partial, status=status, fetched_at=time.time())
    if status < 400:
        _store(key, page)
    return page
