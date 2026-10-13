"""云浏览器的出网关卡——Chromium 的每一个连接都从这里过（页面里的跳转、重定向、图片、脚本、WebSocket、
Service Worker 发的请求都算），只放行公网地址。

为什么不只靠 Playwright 的 route：route 只看到第一跳（302 跳到 http://postgres:5432 它看不见），也拦不住
WebSocket 和 Service Worker；而且它查完 DNS 后 Chromium 自己再解析一次，中间能被换成内网 IP（DNS rebinding）。
这里是一个只听 127.0.0.1 的小 HTTP 代理（每个会话用自己的代理账号 = 会话名，口令是本进程随机生成的）：
- CONNECT host:port（https / wss）和绝对地址的 http 请求都支持；
- 解析一次 → 任何一个地址是内网 / 本机 → 403 拒，并记到这个会话的“被拦清单”（快照带给模型）；
- 否则**连的就是刚查过的那个 IP**（不再二次解析，rebinding 没有空子可钻）；
- 允许名单 BROWSER_ALLOW_HOSTS（后端 OUTBOUND_ALLOW_HOSTS 同义）里的主机放行，给用户自己的 NAS 用。

地址规则 is_private_address 与后端 app/web_guard.py 的同名函数逐条一致（浏览器是单独的容器，镜像里没有后端代码）；
backend/tests/smoke_browser_egress.py 用同一张表对两边做一致性检查，改一边必须改另一边。
"""
import asyncio
import base64
import ipaddress
import os
import secrets
import socket
import time
from collections import deque
from urllib.parse import urlsplit

INTERNAL_SUFFIXES = (".localhost", ".local", ".internal")
_BENCHMARK = ipaddress.ip_network("198.18.0.0/15")
_SHARED = ipaddress.ip_network("100.64.0.0/10")
HEAD_MAX = 64 * 1024        # 请求头最多读这么多
CONNECT_TIMEOUT = 15        # 连目标的超时（秒）
IDLE_TIMEOUT = 120          # 两头都没数据多久就断
BLOCKED_KEEP = 20           # 每个会话最多记几条被拦
_CHUNK = 64 * 1024


def sanitize_host(host: str) -> str:
    host = (host or "").strip().lower().rstrip(".")
    return host[1:-1] if host.startswith("[") and host.endswith("]") else host


def is_private_address(address: str) -> bool:
    """与 backend/app/web_guard.is_private_address 一致：IP 是不是公网以外；不是 IP 的名字只看内部后缀。"""
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


class Refused(Exception):
    """不许连（原因给模型看）。"""


async def _system_resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    out: list[str] = []
    for i in infos:
        if i[4][0] not in out:
            out.append(i[4][0])
    return out


class Egress:
    def __init__(self, allow_hosts: str = "", resolve=None):
        self.secret = secrets.token_urlsafe(24)
        self.allow = {sanitize_host(h) for h in allow_hosts.split(",") if h.strip()}
        self.resolve = resolve or _system_resolve
        self.port = 0
        self._server: asyncio.AbstractServer | None = None
        self._blocked: dict[str, deque] = {}

    # ---- 对 service.py 的接口 ----
    async def start(self) -> int:
        self._server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    def proxy_for(self, session: str) -> dict:
        """给 browser.new_context(proxy=…) 用：这个会话的代理账号。"""
        return {"server": f"http://127.0.0.1:{self.port}", "username": session, "password": self.secret}

    def take_blocked(self, session: str) -> list[dict]:
        """取走这个会话上次以来被拦的请求 [{host, reason}]（同一主机只留一条）。"""
        q = self._blocked.pop(session, None) or ()
        seen: dict[str, dict] = {}
        for item in q:
            seen.setdefault(item["host"], {"host": item["host"], "reason": item["reason"]})
        return list(seen.values())

    def forget(self, session: str) -> None:
        self._blocked.pop(session, None)

    # ---- 规则 ----
    async def pick(self, host: str, port: int) -> str:
        """检查主机，返回要连的那个 IP（已查过的，连接时不再解析）。不许 → Refused。"""
        h = sanitize_host(host)
        if not h:
            raise Refused("地址里没有主机名")
        if not 0 < port < 65536:
            raise Refused(f"端口 {port} 不对")
        allowed = h in self.allow
        if not allowed and (h == "localhost" or h.endswith(INTERNAL_SUFFIXES)):
            raise Refused(f"{h} 是内部主机名")
        try:
            ipaddress.ip_address(h.split("%")[0])
            if not allowed and is_private_address(h):
                raise Refused(f"{h} 是内网 / 本机地址")
            return h
        except ValueError:
            pass
        try:
            addrs = await self.resolve(h, port)
        except (OSError, UnicodeError) as e:
            raise Refused(f"解析不了域名 {h}（{e.__class__.__name__}）") from e
        if not addrs:
            raise Refused(f"解析不了域名 {h}")
        if not allowed:
            for a in addrs:
                if is_private_address(a):
                    raise Refused(f"{h} 指向内网地址 {a}")
        return addrs[0]

    def _record(self, session: str, host: str, reason: str) -> None:
        q = self._blocked.setdefault(session, deque(maxlen=BLOCKED_KEEP))
        q.append({"host": sanitize_host(host), "reason": reason, "at": time.time()})

    # ---- 代理本身 ----
    def _session_of(self, headers: dict[str, str]) -> str | None:
        raw = headers.get("proxy-authorization", "")
        if not raw.lower().startswith("basic "):
            return None
        try:
            user, _, pw = base64.b64decode(raw[6:].strip(), validate=True).decode().partition(":")
        except (ValueError, UnicodeDecodeError):
            return None
        return user if user and secrets.compare_digest(pw, self.secret) else None

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await self._handle(reader, writer)
        except (ConnectionError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError):
            pass
        finally:
            writer.close()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), IDLE_TIMEOUT)
        if len(head) > HEAD_MAX:
            return await _reply(writer, 431, "Request Header Fields Too Large")
        lines = head.decode("latin-1").split("\r\n")
        parts = lines[0].split(" ")
        if len(parts) != 3:
            return await _reply(writer, 400, "Bad Request")
        method, target, version = parts
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        session = self._session_of(headers)
        if session is None:
            return await _reply(writer, 407, "Proxy Authentication Required",
                                extra="Proxy-Authenticate: Basic realm=\"browser\"\r\n")
        if method.upper() == "CONNECT":
            host, _, port_s = target.rpartition(":")
            port = int(port_s) if port_s.isdigit() else 443
            rest = b""
        else:
            u = urlsplit(target)
            if u.scheme != "http" or not u.hostname:
                return await _reply(writer, 400, "Bad Request")
            host, port = u.hostname, u.port or 80
            path = (u.path or "/") + (f"?{u.query}" if u.query else "")
            keep = [l for l in lines[1:] if l and l.split(":", 1)[0].strip().lower()
                    not in ("proxy-authorization", "proxy-connection", "connection", "keep-alive")]
            rest = (f"{method} {path} {version}\r\n" + "".join(f"{l}\r\n" for l in keep)
                    + "Connection: close\r\n\r\n").encode("latin-1")
        try:
            ip = await self.pick(host, port)
        except Refused as e:
            self._record(session, host, str(e))
            return await _reply(writer, 403, "Forbidden", body=f"已拦下：{e}（助手的浏览器不能访问内网 / 本机地址）")
        try:
            up_r, up_w = await asyncio.wait_for(asyncio.open_connection(ip, port), CONNECT_TIMEOUT)
        except (OSError, asyncio.TimeoutError):
            return await _reply(writer, 502, "Bad Gateway")
        try:
            if method.upper() == "CONNECT":
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await writer.drain()
            else:
                up_w.write(rest)
                await up_w.drain()
                # 明文 http 一个连接只转一个请求（上游已被要求 Connection: close）：上游回完就整条断开，
                # 浏览器想复用这条连接发下一个请求会自己重连，下一个请求也就重新过检查
                tasks = [asyncio.ensure_future(_pipe(up_r, writer)), asyncio.ensure_future(_pipe(reader, up_w))]
                await asyncio.wait(tasks[:1])
                tasks[1].cancel()
                return
            await asyncio.gather(_pipe(reader, up_w), _pipe(up_r, writer))
        finally:
            up_w.close()


async def _reply(writer: asyncio.StreamWriter, code: int, text: str, extra: str = "", body: str = "") -> None:
    data = body.encode()
    writer.write(f"HTTP/1.1 {code} {text}\r\n{extra}Content-Type: text/plain; charset=utf-8\r\n"
                 f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n".encode() + data)
    await writer.drain()


async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await asyncio.wait_for(src.read(_CHUNK), IDLE_TIMEOUT)
            if not data:
                break
            dst.write(data)
            await dst.drain()
    except (ConnectionError, asyncio.TimeoutError):
        pass
    finally:
        try:
            if dst.can_write_eof():
                dst.write_eof()
        except (OSError, RuntimeError):
            pass


ALLOW_HOSTS = os.environ.get("BROWSER_ALLOW_HOSTS", "")
