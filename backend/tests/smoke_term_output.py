# 冒烟：v1.40 终端输出回炉（移植 Codex head_tail_buffer + Gemini CLI 的去 ANSI / 二进制判定）。
# 1) term_text：颜色/清行/光标/OSC 标题与超链接去掉，\r 进度帧折叠，杂控制字符去掉，二进制判定；
#    runner.ANSI_PATTERN 与 backend 一字不差；
# 2) runner.Cleaner 流式去转义（序列被切在两块之间）；runner.HeadTail 跑 Codex 的单测；Sink 一批有上限；
# 3) 真 sandbox/runner.py（docker 换成本机 bash）：带颜色输出洗干净、刷屏输出内存有界 + 全文边跑边落盘且与结果拼得上、
#    落盘上限截断标记、二进制输出只报字节数不落盘；
# 4) 后台任务日志：log_tail / read_new 去颜色、二进制日志一句话且游标跳到末尾；
# 5) run_command（模拟模型 + 假沙盒流）：二进制、截断说明、颜色进模型前已洗。
# 运行：python tests/smoke_term_output.py
import os, sys, asyncio, subprocess, tempfile, json, types
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import jobs, sandbox_client, term_text as tt
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.db import SessionLocal
from app.models import Job
from app.storage import project_dir

# ---- 1. term_text ----
E = "\x1b"
cases = {
    f"{E}[31mred{E}[0m": "red",
    f"{E}[1;32mok{E}[39;49m done": "ok done",
    f"a{E}[Kb": "ab",
    f"{E}]0;title\x07x": "x",
    f"{E}]8;;https://a.com/x?y=1{E}\\link{E}]8;;{E}\\": "link",
    f"{E}]0;t\x9cz": "z",
    f"{E}[?25lhide{E}[?25h": "hide",
    f"{E}[10A up": " up",
    "\x9b31mc": "c",
    "tab\tok\bx\x07": "tab\tokx",
    "plain [x] (y); z \\ ok": "plain [x] (y); z \\ ok",
    "中文\x1b[33m警告\x1b[0m": "中文警告",
}
for raw, want in cases.items():
    assert tt.clean(raw) == want, (raw, tt.clean(raw))
assert tt.frames("a\nb 1%\rb 50%\nc\r\nd\r") == "a\nb 50%\nc\nd"
assert tt.clean(f"{E}[2K\r下载 10%{E}[0m\r{E}[2K下载 100%\n") == "下载 100%\n"
assert tt.is_binary(b"PK\x03\x04\x00\x00") and not tt.is_binary(b"x" * 600 + b"\x00") and not tt.is_binary("中".encode())
assert "1234 字节" in tt.binary_note(1234) and "> out.bin" in tt.binary_note(1)
assert tt.tail(f"{E}[32m" * 3000 + "end") == "end"  # 转义不占名额
assert tt.tail("\n".join(str(i) for i in range(100))).splitlines()[0] == "60"

# ---- 2. runner 组件（docker 换成本机 bash）----
procs = {}
class FakeApi:
    def exec_create(self, cid_, argv, workdir=None, environment=None):
        eid = f"e{len(procs)}"
        procs[eid] = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      env={**os.environ, **(environment or {})}, cwd=tmp)
        return {"Id": eid}
    def exec_start(self, eid, stream=False):
        p = procs[eid]
        while (b := p.stdout.read1(4096)):
            yield b
    def exec_inspect(self, eid):
        return {"ExitCode": procs[eid].wait()}
class FakeContainer:
    id, status = "c1", "running"
    image = NS(id="img")
    def exec_run(self, cmd, workdir=None, detach=False):
        r = subprocess.run(cmd, capture_output=True, cwd=tmp)
        return NS(exit_code=r.returncode, output=r.stdout)
fake_client = NS(api=FakeApi(), containers=NS(get=lambda name: FakeContainer(), list=lambda **kw: []),
                 images=NS(get=lambda name: NS(id="img")))
docker_mod = types.ModuleType("docker"); docker_mod.from_env = lambda: fake_client
errors_mod = types.ModuleType("docker.errors"); errors_mod.NotFound = type("NotFound", (Exception,), {})
docker_mod.errors = errors_mod
sys.modules.update({"docker": docker_mod, "docker.errors": errors_mod})
os.environ.update(SANDBOX_TOKEN="t", HOST_PROJECTS_DIR=tmp)
sys.path.insert(0, os.path.join(root, "..", "sandbox"))
import runner
runner.PROJECTS_ROOT = os.path.join(tmp, "projects")
assert runner.ANSI_PATTERN == tt.ANSI_PATTERN, "沙盒和后端的 ANSI 规则必须一致"

c = runner.Cleaner()
assert c.feed(f"ok{E}[3") == "ok" and c.feed("1mred") == "red" and tt.clean(c.feed(f"{E}", final=True)) == ""
c = runner.Cleaner()
assert c.feed(f"a{E}") + c.feed("[0mb") == "ab"
assert c.feed(f"x{E}]0;long title") == "x" and c.feed(f" here\x07y") == "y"
assert tt.clean(c.feed(f"{E}" + "z" * 100)) == "z" * 100  # 远超 ESC_HOLD 的“转义”不是转义，不会一直扣着
c = runner.Cleaner()
assert c.feed("半截 \x1b[3") == "半截 " and c.feed("", final=True) == ""  # 收尾时扣着的半截照样洗掉
assert c.feed("尾巴\x1b[0m") == "尾巴" and c.feed("", final=True) == ""

# Codex head_tail_buffer_tests.rs（按字符）
b = runner.HeadTail(10); b.push("0123456789"); assert b.omitted == 0
b.push("ab"); assert b.omitted == 2 and b.text().startswith("01234") and b.text().endswith("89ab") and b.text() == "01234789ab"
b = runner.HeadTail(0); b.push("abc"); assert b.retained() == 0 and b.omitted == 3 and b.text() == ""
b = runner.HeadTail(1); b.push("abc"); assert b.retained() == 1 and b.omitted == 2 and b.text() == "c"
b = runner.HeadTail(10); b.push("0123456789"); b.push("ABCDEFGHIJK")
assert b.text().startswith("01234") and b.text().endswith("GHIJK") and b.omitted > 0 and b.total() == 21
b = runner.HeadTail(10); b.push("01"); b.push("234"); assert b.text() == "01234"
b.push("567"); b.push("89"); assert b.text() == "0123456789" and b.omitted == 0
b.push("a"); assert b.text() == "012346789a" and b.omitted == 1
b = runner.HeadTail(10)
for ch in "0123456789ab":
    b.push(""); b.push(ch)
assert b.retained() == 10 and b.omitted == 2 and len(b.head) == 5 and len(b._tail) <= 5

s = runner.Sink()
for _ in range(100):
    s.put("x" * 1000)
assert s._size <= runner.SINK_MAX * 2 and len(s.take()) == runner.SINK_MAX and s.take() == ""

# ---- 3. 真 runner._exec ----
r = runner._exec("p1", "printf '\\033[32mPASS\\033[0m 3 tests\\n\\033]0;title\\007done\\n'", 10)
assert r["output"] == "PASS 3 tests\ndone\n" and "spill" not in r, r
# 刷屏：40 万字，内存里只留 MAX_OUTPUT，全文边跑边写盘，结果的头尾与盘上全文对得上
r = runner._exec("p1", "for i in $(seq 1 40000); do printf '\\033[1mline %05d\\033[0m\\n' $i; done", 60)
full = "".join(f"line {i:05d}\n" for i in range(1, 40001))
head, _, tail = r["output"].partition(runner.SPILL_MARK)
assert full.startswith(head) and full.endswith(tail) and len(head) + len(tail) == runner.MAX_OUTPUT, (len(head), len(tail))
assert r["total"] == len(full) and r["omitted"] == len(full) - runner.MAX_OUTPUT and "spill_truncated" not in r
spilled = os.path.join(runner.PROJECTS_ROOT, "p1", r["spill"])
assert open(spilled, encoding="utf-8").read() == full, "落盘文件 = 洗过的全文"
assert runner.SPILL_NAME_RE.match(os.path.basename(spilled))
# 落盘上限
runner.SPILL_MAX_BYTES = 30000
r = runner._exec("p1", "seq 1 100000", 60)
assert r["spill_truncated"] is True and r["total"] == len("".join(f"{i}\n" for i in range(1, 100001)))
body = open(os.path.join(runner.PROJECTS_ROOT, "p1", r["spill"]), encoding="utf-8").read()
assert body.startswith("1\n2\n") and "后面没有保存" in body and len(body.encode()) < 30200
runner.SPILL_MAX_BYTES = 64 * 1024 * 1024
# 二进制：不进缓冲、不落盘，只报字节数
before = set(os.listdir(os.path.join(runner.PROJECTS_ROOT, "p1", ".spill")))
r = runner._exec("p1", "printf 'PK\\003\\004\\000\\000'; head -c 200000 /dev/zero", 10)
assert r["output"] == "" and r["binary"] == 200006 and r["exit_code"] == 0, {k: v for k, v in r.items() if k != "output"}
assert set(os.listdir(os.path.join(runner.PROJECTS_ROOT, "p1", ".spill"))) == before
sink = runner.Sink()
runner._exec("p1", "printf 'abc\\000def'", 10, sink=sink)
assert "二进制输出" in sink.take()
# 中文跨块 + 颜色跨块
r = runner._exec("p1", "for i in $(seq 1 3000); do printf '\\033[3%dm中文%d\\033[0m ' $((i%7)) $i; done", 30)
assert "\x1b" not in r["output"] and "\ufffd" not in r["output"] and "中文3000" in r["output"]

# ---- 4. 后台任务日志 ----
def mkjob(jid, data: bytes):
    d = project_dir("me") / jobs.JOBS_DIR / jid
    d.mkdir(parents=True, exist_ok=True)
    (d / "log").write_bytes(data)
    return Job(id=jid, project_id="me", read_offset=0, title="t", command="c", state="running", tail="")
j = mkjob("jaaa111", f"{E}[32mCollecting x{E}[0m\n{E}[2K\r 10%\r 100%\nok\n".encode())
assert jobs.log_tail(j) == "Collecting x\n 100%\nok\n", repr(jobs.log_tail(j))
text, nxt, dropped = jobs.read_new(j)
assert text == "Collecting x\n 100%\nok\n" and dropped == 0 and nxt == jobs.log_size(j)
j = mkjob("jbbb222", b"\x1f\x8b\x08\x00" + b"\x00" * 5000)
assert "二进制" in jobs.log_tail(j)
text, nxt, dropped = jobs.read_new(j)
assert "二进制" in text and nxt == 5004 and dropped == 0
j.read_offset = nxt
assert jobs.read_new(j) == ("", 5004, 0)

# ---- 5. run_command ----
load_builtin()
fake = {}
async def fake_stream(project_id, command, timeout=60, stdin=None, **kw):
    yield {"type": "out", "data": f"{E}[33mwarn{E}[0m\n"}
    yield {"type": "exit", "exit_code": 0, "timed_out": False, **fake}
sandbox_client.stream = fake_stream
async def run(cmd):
    async with SessionLocal() as db:
        return await REGISTRY["run_command"].run(ToolContext(db=db, project_id=None, conversation_id=None), command=cmd)
fake.update(output="", binary=4096)
res = asyncio.run(run("cat a.zip"))
assert "4096 字节" in res.content and "display_file" in res.content and "4096 字节" in res.blocks[0]["source"], res.content
fake.clear(); fake.update(output=f"{E}[31mE{E}[0m 1\r 2\n")
res = asyncio.run(run("x"))
assert res.content == "退出码 0\n 2\n" and "\x1b" not in res.blocks[0]["source"], repr(res.content)
fake.clear(); fake.update(output="a" + runner.SPILL_MARK + "b", omitted=99, total=101, spill=".spill/x.txt", spill_truncated=True)
res = asyncio.run(run("y"))
assert "只存了开头" in res.content and ".spill/x.txt" in res.content and "中间省略 99 字符" in res.blocks[0]["source"]
print("smoke_term_output ok")
