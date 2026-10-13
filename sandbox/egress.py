"""沙盒电脑的出网关卡（v2.37 CORE 37）——助手自己的命令（curl / pip / npm / git / apt / python 脚本…）上网都从这里过。

为什么要有：沙盒容器和本服务同在 sandboxes 网络上；不设防时，网页里一句提示注入就能让模型
`curl http://169.254.169.254/`（云主机元数据，里面有临时密钥）、扫 VPS 宿主机端口、或连别的内网机器。
做法（与云浏览器 browser/egress.py 同一套语义，Stripe Smokescreen 式）：
- 本服务起一个 HTTP 代理（CONNECT 走 https/wss，绝对地址走明文 http，一个连接一个请求）；
- 每条命令 / 每个后台任务拿自己的代理账号：用户名 = "<工作区>~<e|j><标签>"，口令 = HMAC(SANDBOX_TOKEN, 用户名)
  （确定性：本服务重启后旧任务的账号照样认；命令拿不到别的工作区的口令）；
- 解析一次 → 规则判 → 连的就是刚查过的那个 IP（不二次解析，DNS rebinding 无空子）；
- 被拦的记到这个账号名下：前台命令的结果带回给模型，后台任务另写一份到工作区 .jobs/<id>/egress（后端读）。
- 真正“绕不过去”靠部署：docker-compose 里 sandboxes 网络是 internal（容器没有直接出网的路由，只能找本代理）；
  只设环境变量时，故意不走代理的程序（裸 socket）还是能直连——那一层要在 VPS 上实测。

规则（顺序照 Codex network-proxy runtime.rs host_blocked：显式拒绝最先赢）：
1. 拒绝名单 SANDBOX_DENY_HOSTS 命中 → 拒（"*" 不许写进拒绝名单：那等于断网，应当直接关掉出网）；
2. 内网 / 本机 / 内部主机名（is_private_address，与后端 web_guard、浏览器同一张表）→ 拒，除非在允许名单
   SANDBOX_ALLOW_HOSTS（= 后端 OUTBOUND_ALLOW_HOSTS，给用户自己的 NAS）里；
3. 其余公网地址放行（消费级助手装包、下载、调 API 都要上网；逐域名放行是开发者向，普通用户受不了）。

名单写法（Ported from openai/codex codex-rs/network-proxy/src/domain_matcher.rs (Apache-2.0), modified）：
"example.com" 只配本身；"*.example.com" 只配子域；"**.example.com" 本身 + 子域；"?" 配一个字节；
不分大小写（只 ASCII）、去掉末尾的点、[v6] 去方括号。我们加的：CIDR（"192.168.1.0/24"）和单个 IP。
"""
import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import socket
import time
from collections import deque
from urllib.parse import urlsplit

INTERNAL_SUFFIXES = (".localhost", ".local", ".internal")
_BENCHMARK = ipaddress.ip_network("198.18.0.0/15")
_SHARED = ipaddress.ip_network("100.64.0.0/10")
HEAD_MAX = 64 * 1024        # 请求头最多读这么多
CONNECT_TIMEOUT = 15        # 连目标的超时（秒）
IDLE_TIMEOUT = 300          # 两头都没数据多久就断（大文件下载中途停顿比浏览器长）
BLOCKED_KEEP = 20           # 每个账号最多记几条被拦
RECENT_KEEP = 30            # 每个工作区最近被拦（电脑页 / 状态用）
USERS_KEEP = 512            # 内存里最多记多少个账号的被拦清单（老的丢掉）
JOB_FILE = "egress"         # 后台任务被拦的写进 .jobs/<id>/egress（JSON 行）
JOB_FILE_MAX = 20           # 这个文件最多几行
_CHUNK = 64 * 1024
SEP = "~"                   # 用户名里工作区和标签之间
KINDS = ("e", "j")          # e = 前台命令（exec 令牌），j = 后台任务（任务 id）
NO_PROXY = "localhost,127.0.0.1,::1"  # 容器里自己起的服务照常直连（不出容器）


class PatternError(ValueError):
    """名单里有写法不支持的条目（启动时报出来，不悄悄丢掉——Codex 同样拒绝而不是忽略）。"""


class Refused(Exception):
    """不许连（原因给模型看）。"""


def sanitize_host(host: str) -> str:
    host = (host or "").strip().lower().rstrip(".")
    return host[1:-1] if host.startswith("[") and host.endswith("]") else host


def is_private_address(address: str) -> bool:
    """与 backend/app/web_guard.is_private_address、browser/egress.py 同名函数一致（smoke 对表）。"""
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


# ---- 名单（domain_matcher.rs） ----
def normalize_host(host: str) -> str:
    """去空白、去端口（恰好一个冒号时）、去方括号、小写、去末尾的点。"""
    host = (host or "").strip()
    if host.startswith("[") and "]" in host:
        return _norm_literal(host[1:host.index("]")])
    if host.count(":") == 1:
        return _norm_literal(host.split(":")[0])
    return _norm_literal(host)


def _norm_literal(host: str) -> str:
    host = host.lower().rstrip(".")
    for delim in ("%25", "%"):
        ip, _, scope = host.partition(delim)
        if scope and _is_ip(ip):
            return f"{ip}%{scope}"
    return host


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def _normalize_pattern(pattern: str) -> str:
    pattern = pattern.strip()
    if pattern == "*":
        return "*"
    for prefix in ("**.", "*."):
        if pattern.startswith(prefix):
            return prefix + normalize_host(pattern[len(prefix):])
    return normalize_host(pattern)


def _expand(pattern: str) -> list[str]:
    for prefix in ("**.", "*."):
        if pattern.startswith(prefix):
            domain = pattern[len(prefix):].strip()
            if not domain:
                return [""]
            return [domain, f"?*.{domain}"] if prefix == "**." else [f"?*.{domain}"]
    return [pattern]


def _matches(pattern: bytes, host: bytes) -> bool:
    """通配：* 任意多字节，? 一个字节，ASCII 不分大小写；只回溯最近一个 *（O(模式长 × 主机长)）。"""
    p = h = 0
    star = None
    while h < len(host):
        c = pattern[p] if p < len(pattern) else None
        if c == 42:  # *
            star = [p + 1, h]
            p += 1
        elif c is not None and (c == 63 or bytes([c]).lower() == bytes([host[h]]).lower()):
            p += 1
            h += 1
        elif star is not None:
            star[1] += 1
            p, h = star[0], star[1]
        else:
            return False
    return all(ch == 42 for ch in pattern[p:])


def is_global_wildcard(pattern: str) -> bool:
    return "*" in _expand(_normalize_pattern(pattern))


class Patterns:
    """一张名单：域名通配（Codex 写法）+ 我们加的 CIDR / IP。"""

    def __init__(self, entries, allow_global: bool):
        self.globs: list[bytes] = []
        self.nets: list = []
        seen: set[bytes] = set()
        for raw in entries:
            raw = (raw or "").strip()
            if not raw:
                continue
            if "/" in raw:  # 我们加的：CIDR
                try:
                    self.nets.append(ipaddress.ip_network(raw, strict=False))
                    continue
                except ValueError as e:
                    raise PatternError(f"名单写法不支持：{raw}") from e
            if not allow_global and is_global_wildcard(raw):
                raise PatternError('拒绝名单不能写 "*"：要整个断网请关掉出网，或列出具体主机 / *.example.com')
            if any(ch in raw for ch in "{}\\") or any(ch.isspace() for ch in raw):
                raise PatternError(f"名单写法不支持：{raw}")
            host = raw[3:] if raw.startswith("**.") else raw[2:] if raw.startswith("*.") else raw
            if "**" in host:
                raise PatternError(f"名单里不能有连续的 **：{raw}")
            if "[" in host or "]" in host:
                inner = host[1:host.index("]")] if host.startswith("[") and "]" in host else ""
                if not inner or not _is_ip(inner.split("%")[0]):
                    raise PatternError(f"方括号只能包 IPv6 地址：{raw}")
            for cand in _expand(_normalize_pattern(raw)):
                if not cand:
                    raise PatternError(f"名单条目是空的：{raw}")
                b = cand.encode()
                if b not in seen:
                    seen.add(b)
                    self.globs.append(b)

    def __bool__(self) -> bool:
        return bool(self.globs or self.nets)

    def match(self, host: str) -> bool:
        h = normalize_host(host)
        if any(_matches(g, h.encode()) for g in self.globs):
            return True
        unscoped = h.split("%")[0]
        if unscoped != h and any(_matches(g, unscoped.encode()) for g in self.globs):
            return True
        if self.nets and _is_ip(unscoped):
            ip = ipaddress.ip_address(unscoped)
            return any(ip.version == n.version and ip in n for n in self.nets)
        return False


def _split(text: str) -> list[str]:
    return [p.strip() for p in (text or "").split(",") if p.strip()]


async def _system_resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    out: list[str] = []
    for i in infos:
        if i[4][0] not in out:
            out.append(i[4][0])
    return out


class Egress:
    def __init__(self, secret: str, allow: str = "", deny: str = "", resolve=None, on_block=None):
        self.key = hashlib.sha256(("sandbox-egress:" + secret).encode()).digest()
        self.allow = Patterns(_split(allow), allow_global=True)
        self.deny = Patterns(_split(deny), allow_global=False)
        self.resolve = resolve or _system_resolve
        self.on_block = on_block  # (pid, kind, tag, item) → None：本服务把后台任务的写进工作区
        self.port = 0
        self._server: asyncio.AbstractServer | None = None
        self._blocked: dict[str, deque] = {}
        self._recent: dict[str, deque] = {}

    # ---- 账号 ----
    @staticmethod
    def user(pid: str, kind: str, tag: str) -> str:
        return f"{pid}{SEP}{kind}{tag}"

    def password(self, user: str) -> str:
        return hmac.new(self.key, user.encode(), hashlib.sha256).hexdigest()[:32]

    def env(self, pid: str, kind: str, tag: str, host: str) -> dict[str, str]:
        """给容器里那条命令的环境变量：大小写两套都给（curl 只认小写 http_proxy，pip/requests 两种都认），
        Node 18+ 的 fetch 要 NODE_USE_ENV_PROXY=1 才看代理变量。"""
        if not self.port:
            return {}
        u = self.user(pid, kind, tag)
        url = f"http://{u}:{self.password(u)}@{host}:{self.port}"
        env = {"HTTP_PROXY": url, "HTTPS_PROXY": url, "NO_PROXY": NO_PROXY, "NODE_USE_ENV_PROXY": "1"}
        env.update({k.lower(): v for k, v in env.items() if k.endswith("PROXY")})
        return env

    def _parse_user(self, user: str) -> tuple[str, str, str] | None:
        pid, _, rest = user.partition(SEP)
        if not pid or not rest or rest[0] not in KINDS or not rest[1:]:
            return None
        return pid, rest[0], rest[1:]

    # ---- 服务 ----
    async def start(self, host: str = "0.0.0.0", port: int = 0) -> int:
        self._server = await asyncio.start_server(self._client, host, port)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self.port = 0

    def take_blocked(self, user: str) -> list[dict]:
        """取走这个账号被拦的 [{host, reason}]（同一主机只留一条）。"""
        q = self._blocked.pop(user, None) or ()
        seen: dict[str, dict] = {}
        for item in q:
            seen.setdefault(item["host"], {"host": item["host"], "reason": item["reason"]})
        return list(seen.values())

    def recent(self, pid: str) -> list[dict]:
        """这个工作区最近被拦的（新的在前），[{host, reason, at}]。"""
        return list(reversed(self._recent.get(pid) or ()))

    def forget(self, pid: str) -> None:
        self._recent.pop(pid, None)
        for u in [u for u in self._blocked if u.startswith(pid + SEP)]:
            self._blocked.pop(u, None)

    # ---- 规则 ----
    def _check_name(self, h: str) -> None:
        if self.deny.match(h):
            raise Refused(f"{h} 在拒绝名单里")

    async def pick(self, host: str, port: int) -> str:
        """检查目标，返回要连的那个 IP（已查过的，连接时不再解析）。不许 → Refused。"""
        h = sanitize_host(host)
        if not h:
            raise Refused("地址里没有主机名")
        if not 0 < port < 65536:
            raise Refused(f"端口 {port} 不对")
        self._check_name(h)
        allowed = self.allow.match(h)
        if _is_ip(h.split("%")[0]):
            if not allowed and is_private_address(h):
                raise Refused(f"{h} 是内网 / 本机地址")
            return h.split("%")[0]
        if not allowed and is_private_address(h):
            raise Refused(f"{h} 是内部主机名")
        try:
            addrs = await self.resolve(h, port)
        except (OSError, UnicodeError) as e:
            raise Refused(f"解析不了域名 {h}（{e.__class__.__name__}）") from e
        if not addrs:
            raise Refused(f"解析不了域名 {h}")
        for a in addrs:
            if self.deny.match(a):
                raise Refused(f"{h} 指向拒绝名单里的 {a}")
            if not allowed and is_private_address(a) and not self.allow.match(a):
                raise Refused(f"{h} 指向内网地址 {a}")
        return addrs[0]

    def _record(self, user: str, host: str, reason: str) -> None:
        item = {"host": sanitize_host(host), "reason": reason, "at": time.time()}
        if user not in self._blocked and len(self._blocked) >= USERS_KEEP:
            self._blocked.pop(next(iter(self._blocked)))
        self._blocked.setdefault(user, deque(maxlen=BLOCKED_KEEP)).append(item)
        parsed = self._parse_user(user)
        if parsed is None:
            return
        pid, kind, tag = parsed
        self._recent.setdefault(pid, deque(maxlen=RECENT_KEEP)).append(item)
        if self.on_block is not None:
            try:
                self.on_block(pid, kind, tag, item)
            except Exception:  # noqa: BLE001 — 记不下来不影响拦
                pass

    # ---- 代理本身（与 browser/egress.py 同一套） ----
    def _user_of(self, headers: dict[str, str]) -> str | None:
        raw = headers.get("proxy-authorization", "")
        if not raw.lower().startswith("basic "):
            return None
        try:
            user, _, pw = base64.b64decode(raw[6:].strip(), validate=True).decode().partition(":")
        except (ValueError, UnicodeDecodeError):
            return None
        if not user or self._parse_user(user) is None:
            return None
        return user if hmac.compare_digest(pw, self.password(user)) else None

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
        user = self._user_of(headers)
        if user is None:
            return await _reply(writer, 407, "Proxy Authentication Required",
                                extra="Proxy-Authenticate: Basic realm=\"sandbox\"\r\n")
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
            self._record(user, host, str(e))
            return await _reply(writer, 403, "Forbidden",
                                body=f"已拦下：{e}（助手的电脑只能访问公网，不能连内网 / 本机地址）\n")
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


def append_job_file(path: str, item: dict) -> None:
    """后台任务被拦的追加进 .jobs/<id>/egress（JSON 行，最多 JOB_FILE_MAX 行，同一主机只记一次）。"""
    try:
        with open(path, encoding="utf-8") as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
    except OSError:
        lines = []
    if len(lines) >= JOB_FILE_MAX:
        return
    for l in lines:
        try:
            if json.loads(l).get("host") == item["host"]:
                return
        except ValueError:
            continue
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"host": item["host"], "reason": item["reason"], "at": round(item["at"])},
                           ensure_ascii=False) + "\n")
