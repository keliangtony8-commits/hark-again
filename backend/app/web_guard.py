# Copyright 2025 Google LLC
# SPDX-License-Identifier: Apache-2.0
# Ported from gemini-cli/packages/core/src/utils/fetch.ts (isAddressPrivate / safeLookup / sanitizeHostname)
# and gemini-cli/packages/core/src/tools/web-fetch.ts (convertGithubUrlToRaw, checkRateLimit) (Apache-2.0), modified:
# Python ipaddress 代替 ipaddr.js；检查做在 httpx 传输层（每一跳重定向都过）；按主机限速；中文提示。
"""助手往外发的 HTTP 请求能不能去这个地址——唯一的规则（防 SSRF）。

后端在 VPS 上和 Postgres、沙箱、浏览器、SearXNG 在同一张内网里；网页里藏一句“去读 http://sandbox:9000/…”
就能让模型替人摸内网。所以模型给出的地址（web_fetch、配图探测、api_request、浏览器打开）一律经这里：
- 只许 http(s)；主机名是 localhost / *.localhost / *.local / *.internal → 拒；
- IP 字面量或 DNS 解析出的**任何一个**地址是私网 / 回环 / 链路本地 / 保留 / 组播 / 共享 100.64/10 /
  测试网段 198.18/15（IPv4 映射的 IPv6 先拆开）→ 拒；
- Docker 服务名（sandbox、postgres…）解析出来就是私网地址，同样被拒；
- 用户确实想让助手读内网某台机器（自己的 NAS）→ 配置 OUTBOUND_ALLOW_HOSTS 列主机名，只放行这些。
SafeTransport 包在 httpx 传输层外面，所以 follow_redirects 的每一跳都会重新检查（302 跳到内网也拦）。
已知局限：检查与连接之间 DNS 可能被换（rebinding），这里不固定 IP；真正的兜底是部署时把浏览器 / 后端的出网隔离。"""
import asyncio
import ipaddress
import socket
import time
from collections import OrderedDict
from urllib.parse import urlsplit, urlunsplit

import httpx

from .config import settings

INTERNAL_SUFFIXES = (".localhost", ".local", ".internal")
RATE_WINDOW = 60.0      # 秒
RATE_MAX = 10           # 每个主机每分钟最多几次（Gemini MAX_REQUESTS_PER_WINDOW）
_RATE_HOSTS = 1000      # 最多记多少个主机（LRU）
_BENCHMARK = ipaddress.ip_network("198.18.0.0/15")
_SHARED = ipaddress.ip_network("100.64.0.0/10")


class Blocked(Exception):
    """这个地址不许去（原因是给模型看的中文）。"""


def sanitize_host(host: str) -> str:
    host = (host or "").strip().lower().rstrip(".")
    return host[1:-1] if host.startswith("[") and host.endswith("]") else host


def _allowed(host: str) -> bool:
    allow = {sanitize_host(h) for h in (settings.outbound_allow_hosts or "").split(",") if h.strip()}
    return host in allow


def is_private_address(address: str) -> bool:
    """IP 是不是公网以外的地址；不是 IP 的名字只看内部后缀。解析不了的 IP 一律当不安全。"""
    a = sanitize_host(address)
    if a == "localhost" or a.endswith(INTERNAL_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(a.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return is_private_address(str(ip.ipv4_mapped))
    if isinstance(ip, ipaddress.IPv4Address) and (ip in _BENCHMARK or ip in _SHARED):
        return True
    return ip.is_multicast or ip.is_unspecified or not ip.is_global


async def _system_resolve(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({i[4][0] for i in infos})

resolve = _system_resolve  # 测试换成假的


async def check_host(host: str, unresolved_ok: bool = False) -> None:
    """unresolved_ok：解析不了也放过（浏览器自己会报“找不到网站”，这里只管别进内网）。"""
    h = sanitize_host(host)
    if not h:
        raise Blocked("地址里没有主机名。")
    if _allowed(h):
        return
    if h == "localhost" or h.endswith(INTERNAL_SUFFIXES):
        raise Blocked(f"{h} 是内部主机名，助手不能访问。")
    try:
        ipaddress.ip_address(h.split("%")[0])
        literal = True
    except ValueError:
        literal = False
    if literal:
        if is_private_address(h):
            raise Blocked(f"{h} 是内网 / 本机地址，助手不能访问。")
        return
    try:
        addrs = await resolve(h)
    except (OSError, UnicodeError) as e:
        if unresolved_ok:
            return
        raise Blocked(f"解析不了域名 {h}（{e.__class__.__name__}），检查一下地址是不是写错了。") from e
    if not addrs:
        if unresolved_ok:
            return
        raise Blocked(f"解析不了域名 {h}。")
    for a in addrs:
        if is_private_address(a):
            raise Blocked(f"{h} 指向内网地址 {a}，助手不能访问。")


async def check(url: str, unresolved_ok: bool = False) -> str:
    """检查一个模型给的地址：协议 + 主机。返回规范化后的地址（补 https://）。"""
    url = (url or "").strip()
    if "://" not in url:
        url = "https://" + url
    p = urlsplit(url)
    if p.scheme.lower() not in ("http", "https"):
        raise Blocked(f"只支持 http / https 地址，不支持 {p.scheme}:。")
    await check_host(p.hostname or "", unresolved_ok)
    return url


def github_raw(url: str) -> str:
    """github.com/<o>/<r>/blob/<ref>/<path> → raw.githubusercontent.com/<o>/<r>/<ref>/<path>（读源码不用解析整页 HTML）。"""
    try:
        p = urlsplit(url)
    except ValueError:
        return url
    if (p.hostname or "").lower() == "github.com" and "/blob/" in p.path:
        parts = p.path.split("/")
        if len(parts) > 4 and parts[3] == "blob":
            path = "/".join(parts[:3] + parts[4:])
            return urlunsplit(("https", "raw.githubusercontent.com", path, p.query, ""))
    return url


_hits: "OrderedDict[str, list[float]]" = OrderedDict()


def rate_wait(url: str, now: float | None = None) -> float:
    """同一主机一分钟内第 RATE_MAX+1 次 → 返回还要等几秒（不记这次）；否则记下这次、返回 0。"""
    now = time.monotonic() if now is None else now
    host = sanitize_host(urlsplit(url).hostname or "")
    if not host:
        return 0.0
    hist = [t for t in _hits.pop(host, []) if t > now - RATE_WINDOW]
    if len(hist) >= RATE_MAX:
        _hits[host] = hist
        return max(0.0, hist[0] + RATE_WINDOW - now)
    hist.append(now)
    _hits[host] = hist
    while len(_hits) > _RATE_HOSTS:
        _hits.popitem(last=False)
    return 0.0


class SafeTransport(httpx.AsyncBaseTransport):
    """每个请求（含每一跳重定向）先过 check_host 再交给真传输层。"""

    def __init__(self, inner: httpx.AsyncBaseTransport | None = None):
        self.inner = inner or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.scheme not in ("http", "https"):
            raise Blocked(f"只支持 http / https 地址，不支持 {request.url.scheme}:。")
        await check_host(request.url.host)
        return await self.inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self.inner.aclose()


def client(*, transport: httpx.AsyncBaseTransport | None = None, **kw) -> httpx.AsyncClient:
    """助手按模型给的地址往外发请求时用的 httpx 客户端。照常走 HTTP(S)_PROXY：httpx 把代理装成 mounts，
    请求优先走 mounts 而不经 transport，所以 mounts 里的每个传输层也包一层（否则配了代理就绕过检查）。"""
    c = httpx.AsyncClient(transport=SafeTransport(transport), **kw)
    c._mounts = {k: (SafeTransport(v) if v is not None and not isinstance(v, SafeTransport) else v)
                 for k, v in c._mounts.items()}
    return c
