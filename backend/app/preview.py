"""端口预览的唯一入口（对标 OpenHands 的 App 标签页、Manus 的“部署预览”、E2B 的 getHost(port)）：
助手在工作区电脑里起了网页服务（run_command background=true 跑 `python -m http.server 8000 --bind 0.0.0.0`、
`npm run dev -- --host 0.0.0.0`…），用户点一下就能在手机/电脑上打开看。

数据流：preview_port 工具 / 电脑页“预览”按钮 → open(ws, port) 先问沙盒这个端口有没有在听（listening）→
签一个带期限的链接 <public_url>/api/preview/<token>/ → 用户的浏览器请求它 → routes/preview.py 验签（verify）→
forward() 经 sandbox_client.preview_send 交给沙盒服务，沙盒在专用网络上直连容器（容器端口从不映射到宿主机）。

规则都在这里：
  - 链接 = 工作区 + 端口 + 到期时间 + HMAC 签名（JWT_SECRET 派生的子密钥），不进库、不用登录，谁拿到链接谁能看，
    TTL 小时后失效；换 JWT_SECRET 全部作废。
  - 响应一律加 CSP sandbox（不透明源）：预览页面是模型写的代码，跑在和 App 同一个域名下，绝不能读到 App 的登录信息；
    同时放行脚本、表单、弹窗、下载，并给跨源请求开 ACAO *（不透明源发出的 fetch 都算跨源，否则页面连自己的接口都调不了）。
  - 改写跳转（Location 指向 / 或容器地址 → 改回预览前缀）和 Set-Cookie 的 Path（只在这条预览链接下生效，不落到 App 的根路径）。
  - 转发时告诉服务它挂在哪个前缀下（X-Forwarded-Prefix / X-Forwarded-Context / X-ProxyContextPath，取自
    jupyter-server-proxy）：Flask(ProxyFix)/Werkzeug、Jupyter、Streamlit 一类会据此生成带前缀的链接。
  - WebSocket 照样转（热更新、Streamlit/Gradio、Jupyter 内核）：签名同一条，先和上游握手、带回上游选的子协议再接受，
    帧原样搬运（文本/二进制不变），关闭码两边互传；有来往就算电脑在用。
  - 已知限制（写进工具说明）：页面里以 / 开头的绝对路径会跳出预览前缀，要用相对路径或框架的 base 选项。
"""
import base64
import hashlib
import hmac
import re
import time
from datetime import datetime, timezone

import httpx

from . import sandbox_client
from .config import settings
from .wire_time import iso

TTL_HOURS = 24
PREFIX = "/api/preview"
_WS = re.compile(r"[A-Za-z0-9_-]{1,64}")
# 预览页面的 CSP：不透明源（拿不到 App 的 localStorage / cookie），其余能力照常给
CSP = "sandbox allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox allow-modals allow-downloads"
# 转发时去掉的头：逐跳头、App 自己的登录（Authorization 是 App 的 JWT，不能给模型写的服务看到）
_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "trailers",
        "transfer-encoding", "upgrade", "host", "authorization", "content-length"}
BODY_MAX = 32 * 1024 * 1024


class PreviewError(RuntimeError):
    """给用户 / 模型看的中文原因。"""


def _key() -> bytes:
    return hmac.new(settings.jwt_secret.encode(), b"sandbox-preview", hashlib.sha256).digest()


def _sig(body: str) -> str:
    return base64.urlsafe_b64encode(hmac.new(_key(), body.encode(), hashlib.sha256).digest()[:16]).decode().rstrip("=")


def sign(ws: str, port: int, now: float | None = None) -> tuple[str, int]:
    """→ (token, 到期 Unix 秒)。token 形如 me.8000.1791800000.<签名>，只含 URL 安全字符。"""
    exp = int((now if now is not None else time.time()) + TTL_HOURS * 3600)
    body = f"{ws}.{port}.{exp}"
    return f"{body}.{_sig(body)}", exp


def verify(token: str, now: float | None = None) -> tuple[str, int] | None:
    """签名对、没过期 → (工作区, 端口)；否则 None（过期和伪造对外一个样）。"""
    parts = token.split(".")
    if len(parts) != 4 or not _WS.fullmatch(parts[0]) or not parts[1].isdigit() or not parts[2].isdigit():
        return None
    body = ".".join(parts[:3])
    if not hmac.compare_digest(parts[3], _sig(body)):
        return None
    if int(parts[2]) < (now if now is not None else time.time()):
        return None
    port = int(parts[1])
    return (parts[0], port) if 1 <= port <= 65535 else None


def base_path(token: str) -> str:
    return f"{PREFIX}/{token}/"


def link(token: str, path: str = "", root: str | None = None) -> str:
    """root 默认外网地址（给用户）；助手自己的浏览器用 settings.internal_url（容器之间直连后端）。"""
    return (root or settings.public_url).rstrip("/") + base_path(token) + path.lstrip("/")


# ---- 端口 ----
async def listening(ws: str) -> dict:
    """{running: bool, ports: [{port, loopback, pid, command}]}。沙盒连不上抛 PreviewError。"""
    try:
        raw = await sandbox_client.ports(ws)
    except httpx.HTTPError as e:
        raise PreviewError("沙盒服务连不上，没法看端口") from e
    rows = [p for p in (raw.get("ports") or []) if isinstance(p, dict) and isinstance(p.get("port"), int)]
    return {"running": raw.get("state") == "running",
            "ports": [{"port": p["port"], "loopback": bool(p.get("loopback")), "pid": p.get("pid"),
                       "command": str(p.get("command") or "")[:200]} for p in rows]}


def describe_ports(ports: list[dict]) -> str:
    return "；".join(f"{p['port']}（{p['command'][:60] or '未知程序'}{'，只监听本机' if p['loopback'] else ''}）"
                    for p in ports) or "没有"


def wire(ws: str, port: int, path: str = "", command: str = "", now: float | None = None) -> dict:
    token, exp = sign(ws, port, now)
    return {"workspace": ws, "port": port, "url": link(token, path), "command": command,
            "expires_at": iso(datetime.fromtimestamp(exp, timezone.utc))}


async def open_port(ws: str, port: int, path: str = "") -> dict:
    """确认端口真有服务在听、外面连得到，再签链接 → wire + internal_url（只给助手自己）。不行抛 PreviewError，原因说清怎么改。"""
    if not 1 <= port <= 65535:
        raise PreviewError("端口要在 1–65535 之间")
    st = await listening(ws)
    if not st["running"]:
        raise PreviewError("电脑在休眠，里面没有在跑的服务。先用 run_command background=true 把服务起来"
                           "（绑 0.0.0.0），等它开始监听再预览。")
    hit = next((p for p in st["ports"] if p["port"] == port), None)
    if hit is None:
        raise PreviewError(f"端口 {port} 上没有在监听的服务。现在在监听的端口：{describe_ports(st['ports'])}。"
                           "服务刚启动的话等几秒、用 job_status 看日志确认它起来了。")
    if hit["loopback"]:
        raise PreviewError(f"端口 {port} 的服务只监听 127.0.0.1，预览连不到。改成监听 0.0.0.0 重启它"
                           "（如 --host 0.0.0.0 / --bind 0.0.0.0 / app.run(host='0.0.0.0')）。")
    out = wire(ws, port, path, hit["command"])
    token = out["url"].split(PREFIX + "/", 1)[1].split("/", 1)[0]
    out["internal_url"] = link(token, path, settings.internal_url)
    return out


# ---- 转发 ----
_PREFIX_HEADERS = ("x-forwarded-prefix", "x-forwarded-context", "x-proxycontextpath")


def prefix_headers(token: str) -> list[tuple[str, str]]:
    """告诉上游自己挂在哪个路径前缀下（jupyter-server-proxy 的三个头，Werkzeug ProxyFix 认 X-Forwarded-Prefix）。"""
    p = base_path(token).rstrip("/")
    return [(h, p) for h in _PREFIX_HEADERS]


def request_headers(items: list[tuple[str, str]], token: str | None = None) -> list[tuple[str, str]]:
    """浏览器请求头 → 转给服务的头：去逐跳头和 App 登录；客户端自带的前缀头不信，换成我们的。"""
    out = [(k, v) for k, v in items if k.lower() not in _HOP and k.lower() not in _PREFIX_HEADERS]
    return out + (prefix_headers(token) if token else [])


# ---- WebSocket ----
# 握手时不往下传的头：逐跳头 + 握手头（客户端库自己生成）+ Origin（预览页是不透明源，Origin: null 常被 tornado 系拒；
# 不带 Origin 则放行）。和 sandbox/runner.py 的 _WS_DROP 同一份。
_WS_DROP = _HOP | {"sec-websocket-key", "sec-websocket-version", "sec-websocket-extensions", "sec-websocket-protocol",
                   "origin", "cookie2"}
WS_MAX = 16 * 1024 * 1024


def ws_headers(items: list[tuple[str, str]], token: str) -> list[tuple[str, str]]:
    return [(k, v) for k, v in items if k.lower() not in _WS_DROP and k.lower() not in _PREFIX_HEADERS] + prefix_headers(token)


def ws_protocols(header: str) -> list[str]:
    return [p.strip() for p in (header or "").split(",") if p.strip()]


def ws_close_code(code) -> int:
    """对端的关闭码 → 能发出去的码：1005/1006/1015 是保留码不能发（无码 → 1000，异常断开 → 1011）。"""
    if code in (None, 1005):
        return 1000
    if not isinstance(code, int) or code in (1006, 1015) or not 1000 <= code <= 4999 or 1016 <= code < 3000:
        return 1011
    return code


async def ws_relay(client_ws, upstream, touch=lambda: None) -> None:
    """双向搬运（与 sandbox/runner.py 的 ws_relay 同一份逻辑）：文本仍是文本、二进制仍是二进制；
    一边断了另一边跟着关，并带上对方的关闭码。client_ws 是 Starlette WebSocket，upstream 是 websockets 连接。"""
    import asyncio

    async def down():
        try:
            async for msg in upstream:
                touch()
                if isinstance(msg, bytes):
                    await client_ws.send_bytes(msg)
                else:
                    await client_ws.send_text(msg)
        except Exception:
            pass
        try:
            await client_ws.close(ws_close_code(getattr(upstream, "close_code", None)))
        except Exception:
            pass

    async def up():
        code = 1000
        try:
            while True:
                m = await client_ws.receive()
                if m["type"] == "websocket.disconnect":
                    code = m.get("code", 1000)
                    break
                touch()
                if m.get("bytes") is not None:
                    await upstream.send(m["bytes"])
                elif m.get("text") is not None:
                    await upstream.send(m["text"])
        except Exception:
            pass
        try:
            await upstream.close(ws_close_code(code))
        except Exception:
            pass

    tasks = [asyncio.create_task(down()), asyncio.create_task(up())]
    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    await asyncio.wait(tasks, timeout=5)
    for t in tasks:
        t.cancel()


def _location(value: str, token: str) -> str:
    base = base_path(token)
    if value.startswith("/") and not value.startswith("//") and not value.startswith(base):
        return base + value[1:]
    m = re.match(r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1?\]|\d+\.\d+\.\d+\.\d+)(?::\d+)?(/.*)?$", value)
    return base + (m.group(1) or "/")[1:] if m else value


def _cookie(value: str, token: str) -> str:
    parts = [p for p in value.split(";") if not p.strip().lower().startswith(("path=", "domain="))]
    return ";".join(parts) + f"; Path={base_path(token)}"


def response_headers(items: list[tuple[str, str]], token: str) -> list[tuple[str, str]]:
    """上游响应头 → 回给浏览器的头：去逐跳头、改跳转和 cookie 路径、加 CSP sandbox 与跨源放行。"""
    out, has_acao = [], False
    for k, v in items:
        lk = k.lower()
        if lk in _HOP or lk in ("x-sandbox-preview", "date", "server"):
            continue
        if lk == "location":
            v = _location(v, token)
        elif lk == "set-cookie":
            v = _cookie(v, token)
        elif lk == "access-control-allow-origin":
            has_acao = True
        out.append((k, v))
    out.append(("Content-Security-Policy", CSP))  # 和上游自己的 CSP 叠加生效，删不掉
    out += [("X-Robots-Tag", "noindex"), ("Referrer-Policy", "no-referrer")]
    if not has_acao:
        out.append(("Access-Control-Allow-Origin", "*"))
    return out


def preflight_headers(request_method: str, request_headers_: str) -> list[tuple[str, str]]:
    """不透明源的跨源预检（OPTIONS + Access-Control-Request-Method）由这里直接答，不劳开发服务器。"""
    return [("Access-Control-Allow-Origin", "*"), ("Access-Control-Allow-Methods", request_method or "GET, POST"),
            ("Access-Control-Allow-Headers", request_headers_ or "*"), ("Access-Control-Max-Age", "600")]


# 打不开时给浏览器看的页（用户点链接看到的是网页，不是 JSON）
_PAGES = {
    "expired": (410, "预览链接失效了", "这条预览链接已过期或不完整。回到聊天里让助手重新给一条，或在“我的电脑”里点端口旁的预览。"),
    "asleep": (503, "电脑在休眠", "这台工作区电脑空闲后休眠了，里面的服务也停了。让助手重新把服务跑起来再预览。"),
    "no_service": (502, "端口上没有服务", "服务可能已经停了或还没启动好。等几秒刷新；还不行就让助手看看后台任务的日志。"),
    "unreachable": (502, "连不上沙盒", "后台的沙盒服务暂时连不上，稍后刷新试试。"),
    "too_large": (413, "请求太大", "一次请求超过 32 MB，预览不转发这么大的内容。"),
}


def error_page(kind: str) -> tuple[int, str]:
    code, title, text = _PAGES.get(kind, _PAGES["unreachable"])
    html = (f'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{title}</title><body style="font:16px/1.6 system-ui,sans-serif;max-width:32rem;margin:18vh auto;'
            f'padding:0 1.5rem;color:#333"><h2 style="font-weight:600">{title}</h2><p style="color:#666">{text}</p></body>')
    return code, html
