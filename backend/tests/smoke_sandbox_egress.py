# 冒烟：v2.37 CORE 37 沙盒电脑出网关卡（sandbox/egress.py + runner 接线 + backend app/egress_note.py）。无迁移。
# 1) 一致性：sandbox/egress.is_private_address 与后端 web_guard、浏览器 egress 三份对一张大表逐条同结论；
# 2) 名单写法（Codex domain_matcher 测试移植 + 我们加的 CIDR / IP）：*.x 只子域、**.x 本身 + 子域、? 一个字节、大小写 / 末尾点、
#    不支持的写法报错不丢、拒绝名单不许 "*"；
# 3) 规则 pick：拒绝最先赢（压过允许）、内网字面量 / 内部名 / 解析到内网 → 拒、允许名单放行、元数据地址拦、连的是查过的 IP；
# 4) 真代理（本机）：没账号 / 错口令 / 别的工作区口令 → 407；内网 → 403 + 记账；允许 → http 转发 200、CONNECT 隧道通；
#    curl 只靠 egress.env() 给的环境变量就走代理（被拦 403、放行 200）；
# 5) runner：命令环境带代理（用户同名变量被覆盖）、结果带 egress_blocked、后台任务写 .jobs/<id>/egress；关掉时不带；
# 6) 后端：egress_note 文案（命令 / 浏览器 / 任务 / 拒绝名单 / 用户卡片）；run_command 结果 ⚠ + OUTBOUND_ALLOW_HOSTS；
#    jobs.describe 读任务文件；一轮模拟模型：工具结果交回模型带 ⚠。
# 运行：python tests/smoke_sandbox_egress.py
import os, sys, asyncio, subprocess, tempfile, json, ipaddress, random, threading, socket, time, types, base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

import importlib.util
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
sbx = load("sandbox_egress", os.path.join(root, "..", "sandbox", "egress.py"))
brw = load("browser_egress", os.path.join(root, "..", "browser", "egress.py"))
from app import egress_note, web_guard

# ---- 1. 一致性 ----
table = ["127.0.0.1", "10.1.2.3", "172.16.0.1", "172.32.0.1", "192.168.0.1", "169.254.169.254", "100.64.0.1",
         "100.128.0.1", "198.18.0.1", "198.20.0.1", "0.0.0.0", "224.0.0.1", "240.0.0.1", "255.255.255.255",
         "::1", "::", "fe80::1", "fe80::1%eth0", "fc00::1", "ff02::1", "2001:db8::1", "::ffff:127.0.0.1",
         "::ffff:10.0.0.1", "::ffff:8.8.8.8", "[::1]", "8.8.8.8", "93.184.216.34", "2606:4700::1111", "1.1.1.1",
         "localhost", "LOCALHOST.", "db.internal", "printer.local", "x.localhost", "example.com", "", "not an ip",
         "192.0.2.1", "203.0.113.5", "64:ff9b::808:808", "fd00:ec2::254"]
rng = random.Random(11)
table += [str(ipaddress.IPv4Address(rng.getrandbits(32))) for _ in range(3000)]
table += [str(ipaddress.IPv6Address(rng.getrandbits(128))) for _ in range(500)]
diff = [a for a in table if not (web_guard.is_private_address(a) == sbx.is_private_address(a) == brw.is_private_address(a))]
assert not diff, diff[:10]
assert sbx.INTERNAL_SUFFIXES == web_guard.INTERNAL_SUFFIXES == brw.INTERNAL_SUFFIXES
print("ok: parity", len(table))

# ---- 2. 名单 ----
P = lambda *e, g=True: sbx.Patterns(list(e), allow_global=g)
for pattern, host, want in [("*.example.com", "api.example.com", True), ("*.example.com", "example.com", False),
                            ("*.example.com", "a.b.example.com", True), ("**.example.com", "example.com", True),
                            ("**.example.com", "x.example.com", True), ("**.example.com", "badexample.com", False),
                            ("example.com", "EXAMPLE.com.", True), ("example.com", "api.example.com", False),
                            ("api?.com", "api1.com", True), ("api?.com", "api.com", False), ("api?.com", "api12.com", False),
                            ("xn--*.de", "xn--bcher-kva.de", True), ("bücher.de", "xn--bcher-kva.de", False),
                            ("É.COM", "É.com", True), ("*", "anything.at.all", True), ("[::1]", "::1", True),
                            ("[::1]", "[::1]", True), ("192.168.1.0/24", "192.168.1.77", True),
                            ("192.168.1.0/24", "192.168.2.1", False), ("10.0.0.5", "10.0.0.5", True),
                            ("fd00::/8", "fd12::1", True), ("fd00::/8", "10.0.0.1", False), ("nas.home", "nas.home:445", True)]:
    assert P(pattern).match(host) is want, (pattern, host, want)
for bad in ["*.", "**.", "**", "a**b.com", "[ab].com", "a[bc].com", "a{b}.com", "a b.com", "a\\b.com", "10.0.0.0/99"]:
    try:
        P(bad); raise AssertionError(f"should reject {bad!r}")
    except sbx.PatternError:
        pass
assert not P("", " ") and P("x.com")  # 空条目跳过（逗号分隔的空段）
for g in ("*", " * ", "**.*"):
    try:
        P(g, g=False); raise AssertionError(g)
    except sbx.PatternError as e:
        assert "不能写" in str(e)
assert P("*.x.com", g=False).match("a.x.com")
print("ok: patterns")

# ---- 3. 规则 ----
DNS = {"evil.example": ["10.0.0.5"], "news.example": ["93.184.216.34"], "nas.home": ["192.168.1.20"],
       "meta.example": ["169.254.169.254"], "mixed.example": ["93.184.216.35", "127.0.0.1"], "blocked.example": ["93.184.216.36"],
       "app.test": ["127.0.0.1"], "public.test": ["127.0.0.1"]}
async def fake_resolve(host, port):
    if host not in DNS:
        raise socket.gaierror("nope")
    return DNS[host]
E = sbx.Egress("tok", allow="nas.home, 192.168.9.0/24", deny="*.bad.example, blocked.example, 203.0.113.0/24", resolve=fake_resolve)
def pick(h, port=443):
    try:
        return asyncio.run(E.pick(h, port))
    except sbx.Refused as e:
        return "X:" + str(e)
assert pick("news.example") == "93.184.216.34"
assert pick("evil.example") == "X:evil.example 指向内网地址 10.0.0.5"
assert pick("meta.example").startswith("X:meta.example 指向内网地址 169.254.169.254")
assert pick("169.254.169.254", 80) == "X:169.254.169.254 是内网 / 本机地址"
assert pick("mixed.example").startswith("X:") and "127.0.0.1" in pick("mixed.example")  # 有一个是内网就拒
assert pick("localhost", 9000) == "X:localhost 是内部主机名" and pick("db.internal").startswith("X:db.internal 是内部")
assert pick("sandbox", 9000).startswith("X:解析不了域名 sandbox")
assert pick("nas.home") == "192.168.1.20" and pick("192.168.9.3") == "192.168.9.3"  # 允许名单
assert pick("x.bad.example").startswith("X:x.bad.example 在拒绝名单里")
assert pick("blocked.example") == "X:blocked.example 在拒绝名单里"
assert pick("203.0.113.9") == "X:203.0.113.9 在拒绝名单里"
assert pick("8.8.8.8") == "8.8.8.8" and pick("[2606:4700::1111]") == "2606:4700::1111"
assert pick("news.example", 0).startswith("X:端口") and pick("").startswith("X:地址里没有")
E2 = sbx.Egress("tok", allow="nas.home", deny="nas.home", resolve=fake_resolve)
try:
    asyncio.run(E2.pick("nas.home", 445)); raise AssertionError("deny should win")
except sbx.Refused as e:
    assert "拒绝名单" in str(e)
DNS["sneaky.example"] = ["203.0.113.50"]
assert pick("sneaky.example").startswith("X:sneaky.example 指向拒绝名单里的 203.0.113.50")
print("ok: rules")

# ---- 4. 真代理 ----
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = f"hello {self.path} host={self.headers.get('Host')}".encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a):
        pass
web = ThreadingHTTPServer(("127.0.0.1", 0), H); WEB = web.server_address[1]
threading.Thread(target=web.serve_forever, daemon=True).start()

job_writes = []
loop = asyncio.new_event_loop()
threading.Thread(target=loop.run_forever, daemon=True).start()
def on_block(pid, kind, tag, item):
    job_writes.append((pid, kind, tag, item["host"]))
# 允许 public.test（解析到 127.0.0.1，模拟“公网”）；app.test 同样解析到 127.0.0.1 但不在允许名单 → 拦
PX = sbx.Egress("secret-token", allow="public.test", resolve=fake_resolve, on_block=on_block)
port = asyncio.run_coroutine_threadsafe(PX.start("127.0.0.1", 0), loop).result(5)
u = PX.user("p1", "e", "abc")
assert u == "p1~eabc" and PX.password(u) == sbx.Egress("secret-token").password(u) != sbx.Egress("other").password(u)
assert PX.password(u) != PX.password(PX.user("p2", "e", "abc"))

def raw(req: bytes) -> bytes:
    s = socket.create_connection(("127.0.0.1", port), 5); s.sendall(req)
    out = b""
    s.settimeout(5)
    try:
        while chunk := s.recv(65536):
            out += chunk
    except socket.timeout:
        pass
    s.close(); return out
def auth(user, pw):
    return b"Proxy-Authorization: Basic " + base64.b64encode(f"{user}:{pw}".encode()) + b"\r\n"
r = raw(f"GET http://public.test:{WEB}/x HTTP/1.1\r\nHost: public.test\r\n\r\n".encode())
assert r.startswith(b"HTTP/1.1 407"), r[:40]
r = raw(f"GET http://public.test:{WEB}/x HTTP/1.1\r\nHost: public.test\r\n".encode() + auth(u, "wrong") + b"\r\n")
assert r.startswith(b"HTTP/1.1 407")
r = raw(f"GET http://public.test:{WEB}/x HTTP/1.1\r\n".encode() + auth("p1", PX.password("p1")) + b"\r\n")
assert r.startswith(b"HTTP/1.1 407")  # 用户名不合格式
r = raw(f"GET http://public.test:{WEB}/x?q=1 HTTP/1.1\r\nHost: public.test:{WEB}\r\n".encode() + auth(u, PX.password(u)) + b"\r\n")
assert r.startswith(b"HTTP/1.0 200") and b"hello /x?q=1" in r, r
r = raw(f"GET http://app.test:{WEB}/ HTTP/1.1\r\n".encode() + auth(u, PX.password(u)) + b"\r\n")
assert r.startswith(b"HTTP/1.1 403") and "已拦下：app.test 指向内网地址 127.0.0.1".encode() in r, r
r = raw(b"CONNECT 169.254.169.254:80 HTTP/1.1\r\n" + auth(u, PX.password(u)) + b"\r\n")
assert r.startswith(b"HTTP/1.1 403")
got = PX.take_blocked(u)
assert [b["host"] for b in got] == ["app.test", "169.254.169.254"] and PX.take_blocked(u) == [], got
assert [x["host"] for x in PX.recent("p1")] == ["169.254.169.254", "app.test"]  # 新的在前
# CONNECT 隧道（放行的）：隧道里说 http
r = raw(f"CONNECT public.test:{WEB} HTTP/1.1\r\n".encode() + auth(u, PX.password(u)) + b"\r\n"
        + f"GET /tunnel HTTP/1.1\r\nHost: public.test\r\nConnection: close\r\n\r\n".encode())
assert r.startswith(b"HTTP/1.1 200 Connection Established") and b"hello /tunnel" in r, r
# curl 只靠 env()（小写 http_proxy；NO_PROXY 不含 app.test）
uj = PX.user("p1", "j", "job1")
env = {**{k: v for k, v in os.environ.items() if "proxy" not in k.lower()}, **PX.env("p1", "j", "job1", "127.0.0.1")}
assert env["http_proxy"] == env["HTTP_PROXY"] and env["NODE_USE_ENV_PROXY"] == "1" and "127.0.0.1" in env["NO_PROXY"]
c = subprocess.run(["curl", "-s", "-o", "-", "-w", "|%{http_code}", f"http://public.test:{WEB}/c"], env=env, capture_output=True, text=True, timeout=20)
assert c.stdout.endswith("|200") and "hello /c" in c.stdout, c
c = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", f"http://app.test:{WEB}/"], env=env, capture_output=True, text=True, timeout=20)
assert c.stdout == "403", c
c = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "https://app.test/"], env=env, capture_output=True, text=True, timeout=20)
assert c.stdout in ("000", "403"), c  # https：CONNECT 被 403，curl 报连接失败
assert ("p1", "j", "job1", "app.test") in job_writes
assert PX.env("p1", "e", "x", "sandbox").get("HTTP_PROXY", "").startswith("http://p1~ex:")
PX.forget("p1")
assert PX.recent("p1") == [] and PX.take_blocked(uj) == []
print("ok: proxy")

# ---- 5. runner 接线（假 docker）----
class NotFound(Exception):
    pass
captured = {}
class FakeC:
    def __init__(s, name): s.name, s.status, s.id, s.image, s.attrs = name, "running", name, NS(id="img"), {"State": {"StartedAt": ""}}
    def exec_run(s, cmd, **kw):
        captured.setdefault("exec_run", []).append((cmd, kw.get("environment")))
        return NS(exit_code=0, output=b"0\n")
    def start(s): pass
    def remove(s, force=False): cs.pop(s.name, None)
cs = {}
def get(name):
    if name not in cs:
        raise NotFound(name)
    return cs[name]
def run_c(image, name, **kw):
    cs[name] = FakeC(name); return cs[name]
def exec_create(cid, cmd, **kw):
    captured["env"] = kw.get("environment"); return {"Id": "x"}
def exec_start(eid, stream=True):
    # 命令跑的时候出网被拦（真代理里记账）：模拟一次
    import urllib.parse
    if not (captured["env"] or {}).get("HTTP_PROXY"):
        yield b"ok\n"; return
    tok = captured["env"]["HTTP_PROXY"].split("//")[1].split(":")[0]
    runner.egress._record(urllib.parse.unquote(tok), "169.254.169.254", "169.254.169.254 是内网 / 本机地址")
    yield b"curl: (56) CONNECT tunnel failed, response 403\n"
fake = NS(containers=NS(get=get, list=lambda **k: list(cs.values()), run=run_c), images=NS(get=lambda n: NS(id="img")),
          networks=NS(get=lambda n: (_ for _ in ()).throw(NotFound(n))),
          api=NS(exec_create=exec_create, exec_start=exec_start, exec_inspect=lambda e: {"ExitCode": 56}))
dm = types.ModuleType("docker"); dm.from_env = lambda: fake
em = types.ModuleType("docker.errors"); em.NotFound = NotFound; dm.errors = em
sys.modules.update({"docker": dm, "docker.errors": em})
os.environ.update(SANDBOX_TOKEN="t", HOST_PROJECTS_DIR=tmp, SANDBOX_ALLOW_HOSTS="nas.home", SANDBOX_STATE=os.path.join(tmp, "st.json"))
sys.path.insert(0, os.path.join(root, "..", "sandbox"))
import runner
runner.PROJECTS_ROOT = tmp
runner.os.chown = lambda *a, **k: None
_mk = os.makedirs
runner.os.makedirs = lambda p, exist_ok=False: _mk(p.replace("/projects", tmp, 1), exist_ok=True)
runner.MEMINFO = os.path.join(tmp, "nomem")
assert runner.EGRESS_ON and runner.egress.allow.match("nas.home")
runner.egress.port = 3128  # 不真起服务：env() 只看端口
r = runner._exec("w1", "curl http://169.254.169.254/", 10, env={"HTTP_PROXY": "http://evil:1", "MY_VAR": "1"})
env = captured["env"]
assert env["MY_VAR"] == "1" and env["HTTP_PROXY"].startswith("http://w1~e") and env["HTTP_PROXY"].endswith("@sandbox:3128")
assert env["https_proxy"] == env["HTTP_PROXY"] and "evil" not in env["HTTP_PROXY"]
assert r["egress_blocked"] == [{"host": "169.254.169.254", "reason": "169.254.169.254 是内网 / 本机地址"}], r
captured.pop("exec_run", None)
asyncio.run(runner.job_start(runner.JobIn(project_id="w1", job_id="ja1b2c3")))
cmd, jenv = captured["exec_run"][-1]
assert cmd[:2] == ["setsid", "-f"] and jenv["HTTP_PROXY"].startswith("http://w1~jja1b2c3:"), jenv
os.makedirs(os.path.join(tmp, "w1", ".jobs", "ja1b2c3"), exist_ok=True)
for _ in range(2):
    runner.egress._record("w1~jja1b2c3", "10.0.0.9", "10.0.0.9 是内网 / 本机地址")
runner.egress._record("w1~jdeadbeef", "10.0.0.9", "x")  # 任务目录不在：不写
lines = open(os.path.join(tmp, "w1", ".jobs", "ja1b2c3", "egress")).read().splitlines()
assert len(lines) == 1 and json.loads(lines[0])["host"] == "10.0.0.9", lines  # 同一主机只记一次
assert not os.path.exists(os.path.join(tmp, "w1", ".jobs", "jdeadbeef"))
runner.EGRESS_ON = False
r = runner._exec("w1", "true", 10)
assert "HTTP_PROXY" not in (captured["env"] or {}), captured["env"]
runner.EGRESS_ON = True
asyncio.run(runner.remove("w1"))
assert runner.egress.recent("w1") == []
print("ok: runner")

# ---- 6. 后端 ----
N = egress_note.note
assert N(None) == "" and N([]) == "" and N(["x", {"reason": "no host"}]) == ""
one = N([{"host": "169.254.169.254", "reason": "169.254.169.254 是内网 / 本机地址"}])
assert one.startswith("⚠ 这条命令连网时有地址被拦下（169.254.169.254 是内网") and "别换地址、换工具或换端口" in one and "OUTBOUND_ALLOW_HOSTS" in one
many = N([{"host": f"10.0.0.{i}", "reason": f"10.0.0.{i} 是内网"} for i in range(5)] + [{"host": "10.0.0.1", "reason": "dup"}])
assert "10.0.0.2" in many and "10.0.0.3" not in many and "等 5 个地址" in many
deny = N([{"host": "x.bad.example", "reason": "x.bad.example 在拒绝名单里"}])
assert "用户设的拒绝名单" in deny and "OUTBOUND_ALLOW_HOSTS" not in deny
assert N([{"host": "a", "reason": "a 是内部主机名"}], "browser").startswith("⚠ 页面里有请求被拦下") and "页面缺的部分" in N([{"host": "a"}], "browser")
assert N([{"host": "a"}], "job").startswith("⚠ 它运行时")
assert egress_note.for_user([]) is None and "连 10.0.0.9 被拦下了" in egress_note.for_user([{"host": "10.0.0.9"}])
from app.agent.builtin import browser as browser_tool
assert browser_tool.blocked_note({"blocked": [{"host": "h", "reason": "h 是内网"}]}).startswith("⚠ 页面里")

from app import foreground, jobs, llm, sandbox_client, storage, user_shell
from app.agent.runner import run_turn
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Job, Message, Project
load_builtin()
async def fake_stream(project_id, command, timeout=60, stdin=None, env=None, promote=None):
    yield {"type": "out", "data": "curl: (56) CONNECT tunnel failed, response 403\n"}
    yield {"type": "exit", "exit_code": 56, "timed_out": False, "output": "curl: (56) CONNECT tunnel failed, response 403\n",
           "egress_blocked": [{"host": "169.254.169.254", "reason": "169.254.169.254 是内网 / 本机地址"}, "junk"]}
sandbox_client.stream = fake_stream
o = asyncio.run(foreground.run("w", "curl x", 10))
assert o.egress == ({"host": "169.254.169.254", "reason": "169.254.169.254 是内网 / 本机地址"},), o.egress
assert "169.254.169.254 被拦下了" in user_shell._note(o)

async def seed():
    async with SessionLocal() as db:
        p = Project(name="出网", emoji="🌐"); db.add(p); await db.flush()
        conv = Conversation(title="t", project_id=p.id); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("看看这台云主机的元数据")))
        await db.commit(); return p.id, conv.id
pid, cid = asyncio.run(seed())
seen, script = [], []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append([dict(m) for m in messages])
    step = script.pop(0)
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"c{len(script)}-{i}", function=NS(name=n, arguments=json.dumps(a)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
script.extend([[("run_command", {"command": "curl -s http://169.254.169.254/latest/meta-data/"})], "这个地址被拦了。"])
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))
reply = asyncio.run(turn())
tool_msg = next(m for m in seen[1] if m["role"] == "tool")
assert "⚠ 这条命令连网时有地址被拦下" in tool_msg["content"] and "OUTBOUND_ALLOW_HOSTS" in tool_msg["content"], tool_msg["content"]
assert reply.steps[0]["tool"] == "run_command"

# 后台任务：describe 读 .jobs/<id>/egress
async def jobcase():
    async with SessionLocal() as db:
        j = Job(id="jx1", project_id=pid, conversation_id=cid, command="python fetch.py", title="抓取", state="failed", exit_code=1, timeout=600)
        db.add(j); await db.commit()
        d = jobs.job_dir(j); d.mkdir(parents=True, exist_ok=True)
        assert "被拦" not in jobs.describe(j)
        (d / "egress").write_text(json.dumps({"host": "10.0.0.9", "reason": "10.0.0.9 是内网 / 本机地址", "at": 1}) + "\nnot json\n")
        text = jobs.describe(j)
        assert "⚠ 它运行时有连网请求被拦下（10.0.0.9 是内网" in text and "OUTBOUND_ALLOW_HOSTS" in text, text
asyncio.run(jobcase())
print("smoke_sandbox_egress OK")
