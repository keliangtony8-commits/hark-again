# 冒烟：v1.44 端口预览转发 WebSocket + 前缀头（核心回炉 #8：preview 对照 jupyter-server-proxy / OpenHands / E2B）。
# 整条链路是真的：本机起一个 websockets 服务（当作容器里的 Vite/Streamlit）→ 真 runner（uvicorn，docker 换假的，
# 容器 IP = 127.0.0.1）→ 真后端（uvicorn）→ websockets 客户端当浏览器。
# 1) 规则：关闭码映射、子协议解析、握手头过滤（Origin/握手头/App 登录不下传，前缀头换成我们的）；
# 2) HTTP 转发带 X-Forwarded-Prefix 三个头，客户端伪造的被替换；
# 3) WS：上游选的子协议带回浏览器（不是盲选第一个）、路径与查询原样、文本/二进制不变、Cookie 照传、Origin 不传、
#    App 的 Authorization 不下传、前缀头在；上游 4001 关 → 浏览器收到 4001；浏览器关 → 上游跟着关；有来往刷新 last_used；
# 4) 拒绝：签名过期 / 伪造、电脑休眠、端口上没人、runner 鉴权不对 → 握手失败（不接受）。
# 运行：env -u HTTP_PROXY -u HTTPS_PROXY python tests/smoke_preview_ws.py
import os, sys, asyncio, subprocess, tempfile, json, time, types, threading, socket
from types import SimpleNamespace as NS

tmp = tempfile.mkdtemp()


def bound() -> socket.socket:
    """绑好的端口直接交给服务用（不先 close 再让服务去绑：并行跑时中间会被别的进程抢走）。"""
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(("127.0.0.1", 0)); return s


runner_sock, back_sock, svc_sock = bound(), bound(), bound()
RUNNER_PORT, BACK_PORT, SVC = (x.getsockname()[1] for x in (runner_sock, back_sock, svc_sock))
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]',
  SANDBOX_URL=f"http://127.0.0.1:{RUNNER_PORT}", SANDBOX_TOKEN="t", PUBLIC_URL="https://me.example",
  INTERNAL_URL="http://backend:8000", NO_PROXY="*")
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

import websockets
from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.http11 import Response

# ---- “容器里的”服务：WS 回声 + 一个 HTTP 口子把收到的头吐回来 ----
seen: list = []          # 每次 WS 握手的 (path, headers)
upstream_closed: list = []


def process_request(conn, request):
    if request.path.startswith("/http"):
        body = json.dumps({k.lower(): v for k, v in request.headers.raw_items()}).encode()
        return Response(200, "OK", Headers([("Content-Type", "application/json"), ("Content-Length", str(len(body)))]), body)
    # 握手在这里记：它在回 101 之前跑，链路另一头的浏览器拿到握手结果时一定已经记下（handler 要等 101 发出去之后才被调度）
    seen.append((request.path, {k.lower(): v for k, v in request.headers.raw_items()}))
    return None


def select_subprotocol(conn, offered):
    return "b" if "b" in offered else (offered[0] if offered else None)


async def handler(conn):
    try:
        async for msg in conn:
            if msg == "close-4001":
                await conn.close(4001, "bye")
                break
            if msg == "bin":
                await conn.send(b"\x00\xffraw")
                continue
            await conn.send(msg)
    finally:
        upstream_closed.append(conn.close_code)


svc_ready = threading.Event()


def run_svc():
    async def main():
        async with serve(handler, sock=svc_sock, process_request=process_request, select_subprotocol=select_subprotocol):
            svc_ready.set()
            await asyncio.Future()
    asyncio.run(main())


threading.Thread(target=run_svc, daemon=True).start()
assert svc_ready.wait(10), "upstream service never came up"

# ---- 真 runner：docker 换假的 ----
class NotFound(Exception):
    pass
containers: dict = {}


class FakeContainer:
    def __init__(self, status="running"):
        self.status, self.name = status, "sbx-me"
        self.attrs = {"NetworkSettings": {"Networks": {"assistant-sandboxes": {"IPAddress": "127.0.0.1"}}}}

    def exec_run(self, cmd, **kw):
        return NS(exit_code=0, output=b"")

    def reload(self):
        pass


def get(name):
    if name not in containers:
        raise NotFound(name)
    return containers[name]


fake_client = NS(api=None, containers=NS(get=get, list=lambda **kw: []), images=NS(get=lambda name: NS(id="img")),
                 networks=NS(get=lambda name: NS(connect=lambda c: None)))
docker_mod = types.ModuleType("docker"); docker_mod.from_env = lambda: fake_client
errors_mod = types.ModuleType("docker.errors"); errors_mod.NotFound = NotFound
docker_mod.errors = errors_mod
sys.modules.update({"docker": docker_mod, "docker.errors": errors_mod})
os.environ.update(HOST_PROJECTS_DIR=tmp)
sys.path.insert(0, os.path.join(root, "..", "sandbox"))
import runner
import uvicorn

containers["sbx-me"] = FakeContainer()
from app import preview
from app.main import app as main_app


def up(app, sock):
    srv = uvicorn.Server(uvicorn.Config(app, log_level="warning", ws="websockets"))
    threading.Thread(target=srv.run, kwargs={"sockets": [sock]}, daemon=True).start()
    end = time.time() + 30
    while not srv.started:  # uvicorn 启动（含 lifespan）做完才置位：等这个条件，不按端口能不能连猜
        assert time.time() < end, f"port {sock.getsockname()[1]} never came up"
        time.sleep(0.02)
    return srv


rsrv, bsrv = up(runner.app, runner_sock), up(main_app, back_sock)

# 1) 规则（两边同一份）
for mod in (preview, runner):
    cc = mod.ws_close_code
    assert cc(None) == 1000 and cc(1005) == 1000 and cc(1006) == 1011 and cc(1015) == 1011 and cc(1000) == 1000
    assert cc(4001) == 4001 and cc(3000) == 3000 and cc(1001) == 1001 and cc(2000) == 1011 and cc(999) == 1011 and cc("x") == 1011
assert preview._WS_DROP == runner._WS_DROP, "握手头过滤两边要一致"
assert preview.ws_protocols(" a, b ,,c") == ["a", "b", "c"] and preview.ws_protocols("") == []
tok, _ = preview.sign("me", SVC)
h = dict(preview.ws_headers([("Origin", "null"), ("Cookie", "sid=1"), ("Sec-WebSocket-Key", "k"), ("Authorization", "Bearer app"),
                             ("X-Forwarded-Prefix", "/evil"), ("User-Agent", "ua")], tok))
assert h == {"Cookie": "sid=1", "User-Agent": "ua", "x-forwarded-prefix": f"/api/preview/{tok}",
             "x-forwarded-context": f"/api/preview/{tok}", "x-proxycontextpath": f"/api/preview/{tok}"}, h
assert preview.request_headers([("A", "1")]) == [("A", "1")], "不给 token 时不加前缀头（旧调用方）"

BASE = f"ws://127.0.0.1:{BACK_PORT}/api/preview"


async def main():
    import httpx
    # 2) HTTP 前缀头
    async with httpx.AsyncClient() as c:
        r = await c.get(f"http://127.0.0.1:{BACK_PORT}/api/preview/{tok}/http/x?y=1",
                        headers={"X-Forwarded-Prefix": "/evil", "Authorization": "Bearer app"})
        assert r.status_code == 200, (r.status_code, r.text[:300])
        got = r.json()
        assert got["x-forwarded-prefix"] == f"/api/preview/{tok}" and got["x-proxycontextpath"] == f"/api/preview/{tok}", got
        assert "authorization" not in got, got

    # 3) WS 全链路
    runner.last_used.pop("me", None)
    async with websockets.connect(f"{BASE}/{tok}/_stcore/stream?session=9", subprotocols=["a", "b"], proxy=None,
                                  additional_headers=[("Cookie", "sid=1"), ("Authorization", "Bearer app"),
                                                      ("Origin", "null")]) as ws:
        assert ws.subprotocol == "b", f"上游选的是 b，浏览器要拿到 b 而不是盲选的 a：{ws.subprotocol}"
        path, hdrs = seen[-1]
        assert path == "/_stcore/stream?session=9", path
        assert hdrs.get("cookie") == "sid=1" and "origin" not in hdrs and hdrs.get("authorization") is None, hdrs
        assert hdrs.get("x-forwarded-prefix") == f"/api/preview/{tok}", hdrs
        assert hdrs.get("sec-websocket-protocol") == "a, b", hdrs
        t0 = runner.last_used.get("me", 0)
        await ws.send("你好")
        assert await asyncio.wait_for(ws.recv(), 5) == "你好"
        await ws.send("bin")
        m = await asyncio.wait_for(ws.recv(), 5)
        assert m == b"\x00\xffraw" and isinstance(m, bytes)
        await ws.send(b"\x01\x02")
        assert await asyncio.wait_for(ws.recv(), 5) == b"\x01\x02"
        assert runner.last_used.get("me", 0) >= t0 > 0, "有来往要算在用"
        await ws.send("close-4001")
        try:
            await asyncio.wait_for(ws.recv(), 5)
            raise AssertionError("应该被关")
        except websockets.ConnectionClosed as e:
            assert e.rcvd is not None and e.rcvd.code == 4001, e

    # 浏览器先关 → 上游跟着关
    n = len(upstream_closed)
    async with websockets.connect(f"{BASE}/{tok}/", proxy=None) as ws:
        assert ws.subprotocol is None
        await ws.send("x")
        assert await asyncio.wait_for(ws.recv(), 5) == "x"
    for _ in range(50):
        if len(upstream_closed) > n:
            break
        await asyncio.sleep(0.1)
    assert len(upstream_closed) > n and upstream_closed[-1] == 1000, upstream_closed

    # 4) 拒绝
    async def refused(url, **kw):
        try:
            async with websockets.connect(url, proxy=None, open_timeout=10, **kw):
                return False
        except websockets.InvalidStatus as e:
            return e.response.status_code == 403
    old, _ = preview.sign("me", SVC, now=time.time() - 25 * 3600)
    assert await refused(f"{BASE}/{old}/x"), "过期签名"
    assert await refused(f"{BASE}/{tok[:-2]}zz/x"), "伪造签名"
    nobody = bound()  # 只 bind 不 listen：这个号被我们占着，别的进程拿不走，连上必被拒
    dead, _ = preview.sign("me", nobody.getsockname()[1])
    assert await refused(f"{BASE}/{dead}/x"), "端口上没人"
    containers["sbx-me"].status = "exited"
    assert await refused(f"{BASE}/{tok}/x"), "电脑休眠"
    containers["sbx-me"].status = "running"
    assert await refused(f"ws://127.0.0.1:{RUNNER_PORT}/preview/me/{SVC}/x", additional_headers=[("Authorization", "Bearer no")]), "runner 鉴权"
    assert await refused(f"ws://127.0.0.1:{RUNNER_PORT}/preview/me/{SVC}/x"), "runner 无鉴权"
    # runner 直连（鉴权对）能通
    async with websockets.connect(f"ws://127.0.0.1:{RUNNER_PORT}/preview/me/{SVC}/x", proxy=None,
                                  additional_headers=[("Authorization", "Bearer t")]) as ws:
        await ws.send("ok")
        assert await asyncio.wait_for(ws.recv(), 5) == "ok"


asyncio.run(main())
print("smoke_preview_ws OK")
rsrv.should_exit = bsrv.should_exit = True
