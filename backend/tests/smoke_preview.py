# 冒烟：v1.30 端口预览（sandbox/runner.py /sandboxes/{id}/ports + /preview 转发、app/preview.py 签名链接与头改写、
# routes/preview.py 公开转发 + POST …/computer/preview、computer.status 带端口、preview_port 工具）。
# 整条链路是真的：本机起一个网页服务（当作容器里的服务）→ 真 runner（uvicorn，docker 换假的，容器 IP = 127.0.0.1）
# → 后端 sandbox_client 走真 HTTP → 公开路由。
# 1) 端口脚本在本机真跑：0.0.0.0 / 127.0.0.1 区分、对回命令行；
# 2) 签名：篡改、过期、坏端口都不认；
# 3) 转发：无斜杠 307、GET 带查询、POST 原样、App 的 Authorization 不下传、跳转与 cookie 路径改写、CSP sandbox + ACAO、
#    预检直接答、链接过期 410 页、端口没服务 502 页、电脑休眠 503 页；
# 4) 电脑页：status 带端口；POST preview 成功不带 internal_url，只听本机 / 没在听 409 写明怎么改；
# 5) preview_port：不给端口且只有一个 → 预览卡；只听本机 → 失败带原因；多个 → 列出来。
# 运行：env -u HTTP_PROXY -u HTTPS_PROXY python tests/smoke_preview.py
import os, sys, asyncio, subprocess, tempfile, json, time, types, threading, socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace as NS

tmp = tempfile.mkdtemp()


def free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


RUNNER_PORT = free_port()
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

# ---- “容器里的”网页服务 ----
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, headers=()):
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/hello"):
            info = {"path": self.path, "auth": self.headers.get("Authorization"), "host": self.headers.get("Host"),
                    "cookie": self.headers.get("Cookie")}
            self._send(200, json.dumps(info).encode(), [("Content-Type", "application/json"),
                                                       ("Set-Cookie", "sid=1; Path=/; HttpOnly")])
        elif self.path == "/go":
            self._send(302, b"", [("Location", "/hello?from=go")])
        elif self.path == "/abs":
            self._send(302, b"", [("Location", f"http://127.0.0.1:{SVC}/hello")])
        else:
            self._send(404, b"nope", [("Content-Type", "text/plain")])

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self._send(201, self.rfile.read(n), [("Content-Type", "application/octet-stream")])


svc = ThreadingHTTPServer(("0.0.0.0", 0), H)
SVC = svc.server_address[1]
threading.Thread(target=svc.serve_forever, daemon=True).start()
loop_srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
LOOP = loop_srv.server_address[1]
threading.Thread(target=loop_srv.serve_forever, daemon=True).start()

# ---- 真 runner：docker 换假的 ----
class NotFound(Exception):
    pass
containers: dict = {}
connected: list = []


class FakeContainer:
    def __init__(self, status="running", nets=None):
        self.status, self.name = status, "sbx-me"
        self.attrs = {"NetworkSettings": {"Networks": nets if nets is not None else {}}}

    def exec_run(self, cmd, **kw):
        if cmd[:2] == ["python3", "-c"]:  # 端口脚本：在本机真跑
            return NS(exit_code=0, output=subprocess.run([sys.executable, "-c", cmd[2]], capture_output=True).stdout)
        return NS(exit_code=0, output=b"")

    def reload(self):
        pass


class FakeNet:
    def connect(self, c):
        connected.append(c.name)
        c.attrs["NetworkSettings"]["Networks"]["assistant-sandboxes"] = {"IPAddress": "127.0.0.1"}


def get(name):
    if name not in containers:
        raise NotFound(name)
    return containers[name]


fake_client = NS(api=None, containers=NS(get=get, list=lambda **kw: []), images=NS(get=lambda name: NS(id="img")),
                 networks=NS(get=lambda name: FakeNet()))
docker_mod = types.ModuleType("docker"); docker_mod.from_env = lambda: fake_client
errors_mod = types.ModuleType("docker.errors"); errors_mod.NotFound = NotFound
docker_mod.errors = errors_mod
sys.modules.update({"docker": docker_mod, "docker.errors": errors_mod})
os.environ.update(HOST_PROJECTS_DIR=tmp)
sys.path.insert(0, os.path.join(root, "..", "sandbox"))
import runner
import uvicorn

containers["sbx-me"] = FakeContainer(nets={})  # 旧版建的容器：不在专用网络上，第一次预览时接上
server = uvicorn.Server(uvicorn.Config(runner.app, host="127.0.0.1", port=RUNNER_PORT, log_level="warning"))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(100):
    try:
        socket.create_connection(("127.0.0.1", RUNNER_PORT), 0.2).close(); break
    except OSError:
        time.sleep(0.1)

# 1) 端口脚本
rows = runner.parse_ports(FakeContainer().exec_run(["python3", "-c", runner.PORTS_PY]).output.decode())
by = {p["port"]: p for p in rows}
assert by[SVC]["loopback"] is False and "smoke_preview" in by[SVC]["command"], by.get(SVC)
assert by[LOOP]["loopback"] is True, by.get(LOOP)
assert runner.parse_ports("garbage") == [] and runner.parse_ports("") == []

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import preview, computer
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.auth import require_user
from app.db import SessionLocal
from app.main import app as main_app
load_builtin()

# 2) 签名
tok, exp = preview.sign("me", SVC)
assert preview.verify(tok) == ("me", SVC) and exp > time.time() + 23 * 3600
assert preview.verify(tok.replace(f".{SVC}.", ".22."), ) is None, "改端口要失效"
assert preview.verify(tok[:-2] + ("AA" if not tok.endswith("AA") else "BB")) is None
assert preview.verify(tok, now=exp + 1) is None
assert preview.verify("../x.80.1.abc") is None and preview.verify("me.0.99999999999.x") is None
old, _ = preview.sign("me", SVC, now=time.time() - 25 * 3600)

main_app.dependency_overrides[require_user] = lambda: "u"
with TestClient(main_app) as cl:
    # 3) 转发
    r = cl.get(f"/api/preview/{tok}", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == f"/api/preview/{tok}/", r.status_code
    r = cl.get(f"/api/preview/{tok}/hello?x=1", headers={"Authorization": "Bearer app-jwt", "Cookie": "sid=1"})
    assert r.status_code == 200, (r.status_code, r.text[:300])
    info = r.json()
    assert info["path"] == "/hello?x=1" and info["auth"] is None and info["cookie"] == "sid=1", info
    assert info["host"] == f"127.0.0.1:{SVC}", info
    assert connected == ["sbx-me"], connected
    assert "sandbox allow-scripts" in r.headers["content-security-policy"] and r.headers["access-control-allow-origin"] == "*"
    assert r.headers["set-cookie"].endswith(f"Path=/api/preview/{tok}/") and "Path=/;" not in r.headers["set-cookie"], r.headers["set-cookie"]
    assert "x-sandbox-preview" not in r.headers
    r = cl.get(f"/api/preview/{tok}/go", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"/api/preview/{tok}/hello?from=go", (r.status_code, r.headers, r.text[:200])
    r = cl.get(f"/api/preview/{tok}/abs", follow_redirects=False)
    assert r.headers["location"] == f"/api/preview/{tok}/hello", r.headers.get("location")
    r = cl.post(f"/api/preview/{tok}/echo", content=b"\x00\x01hello")
    assert r.status_code == 201 and r.content == b"\x00\x01hello"
    r = cl.get(f"/api/preview/{tok}/missing")
    assert r.status_code == 404 and r.text == "nope", "服务自己的 404 原样回"
    r = cl.options(f"/api/preview/{tok}/hello", headers={"Origin": "null", "Access-Control-Request-Method": "PUT"})
    assert r.status_code == 204 and r.headers["access-control-allow-methods"] == "PUT"
    r = cl.get(f"/api/preview/{old}/hello")
    assert r.status_code == 410 and "失效" in r.text and "sandbox" in r.headers["content-security-policy"]
    dead, _ = preview.sign("me", free_port())
    r = cl.get(f"/api/preview/{dead}/")
    assert r.status_code == 502 and "端口上没有服务" in r.text, (r.status_code, r.text[:200])

    # 4) 电脑页
    st = cl.get("/api/projects/me/computer").json()
    ports = {p["port"]: p for p in st["ports"]}
    assert SVC in ports and ports[LOOP]["loopback"] is True, st["ports"]
    r = cl.post("/api/projects/me/computer/preview", json={"port": SVC, "path": "hello"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["url"].startswith("https://me.example/api/preview/me.") and out["url"].endswith("/hello"), out
    assert "internal_url" not in out and out["expires_at"].endswith("Z") or "+" in out["expires_at"], out
    r = cl.post("/api/projects/me/computer/preview", json={"port": LOOP})
    assert r.status_code == 409 and "0.0.0.0" in r.json()["detail"], r.text
    r = cl.post("/api/projects/me/computer/preview", json={"port": dead and 1})
    assert r.status_code == 409 and "没有在监听" in r.json()["detail"], r.text
    assert cl.post("/api/projects/nope/computer/preview", json={"port": SVC}).status_code == 404

    # 休眠：runner 503 → 预览页
    containers["sbx-me"].status = "exited"
    r = cl.get(f"/api/preview/{tok}/hello")
    assert r.status_code == 503 and "休眠" in r.text, r.status_code
    assert cl.get("/api/projects/me/computer").json()["ports"] == []
    containers["sbx-me"].status = "running"

# 5) 工具
async def tool_checks():
    async with SessionLocal() as db:
        ctx = ToolContext(db=db)
        res = await REGISTRY["preview_port"].run(ctx, port=SVC, title="小网页")
        assert not res.failed and res.blocks[0]["type"] == "preview" and res.blocks[0]["title"] == "小网页", res
        assert "http://backend:8000/api/preview/" in res.content and res.blocks[0]["url"] in res.content and "绝不能自己编" in res.content  # v2.48 B20：给真链接防编造
        res = await REGISTRY["preview_port"].run(ctx, port=LOOP)
        assert res.failed and "0.0.0.0" in res.content
        res = await REGISTRY["preview_port"].run(ctx)  # 不给端口：本机可能还有别的监听端口，所以只要列出或直接用
        assert (res.blocks and res.blocks[0]["type"] == "preview") or str(SVC) in res.content, res.content
        # 只有一个对外端口时直接用
        real = preview.listening
        async def one(ws):
            return {"running": True, "ports": [{"port": SVC, "loopback": False, "pid": 1, "command": "x"},
                                               {"port": LOOP, "loopback": True, "pid": 2, "command": "y"}]}
        preview.listening = one
        res = await REGISTRY["preview_port"].run(ctx)
        assert res.blocks and res.blocks[0]["port"] == SVC, res.content
        async def none(ws):
            return {"running": False, "ports": []}
        preview.listening = none
        res = await REGISTRY["preview_port"].run(ctx)
        assert res.failed and "休眠" in res.content
        preview.listening = real
asyncio.run(tool_checks())

from app.blocks import blocks_to_text
assert "端口 8000" in blocks_to_text([{"type": "preview", "workspace": "me", "port": 8000, "url": "u"}])
print("smoke_preview OK")
server.should_exit = True
