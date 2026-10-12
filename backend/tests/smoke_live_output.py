# 冒烟：v1.24 前台命令实时输出 + stdin。
# 1) 内核实时块：工具 ctx.live 推的块第一次 block.start、之后 block.update 原地换，结束换成最终块（不残留 live）；
# 2) run_command 带 stdin 交给沙盒；太长/后台带 stdin 不执行；
# 3) 用户中途停止：沙盒流被关闭（= 沙盒整组杀命令），半截回复里的实时块去掉 live；
# 4) 真的 sandbox/runner.py（docker 换成本机 bash 顶替）：包装脚本接 stdin、默认 EOF、/exec/stream 分批推 NDJSON、
#    断开连接整组杀掉还在跑的命令。模拟模型。
# 运行：python tests/smoke_live_output.py
import os, sys, asyncio, subprocess, tempfile, json, time, types
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import llm, sandbox_client
from app.agent.runner import run_turn
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.agent.builtin.workspace import live_tail
from app.blocks import Block, text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message, Project
from pydantic import TypeAdapter

# ---- 模拟模型 ----
script: list = []
seen: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append(messages)
    step = script.pop(0)
    async def gen():
        if isinstance(step, tuple):
            yield chunk(tool=[NS(index=0, id=f"c{len(script)}", function=NS(name=step[0], arguments=json.dumps(step[1], ensure_ascii=False)))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()

async def seed():
    async with SessionLocal() as db:
        p = Project(name="实验", emoji="🧪"); db.add(p); await db.flush()
        conv = Conversation(title="跑脚本", project_id=p.id); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("跑一下安装")))
        await db.commit()
        return p.id, conv.id
pid, cid = asyncio.run(seed())

# ---- 假沙盒流：分几批吐输出 ----
calls, closed = [], []
async def fake_stream(project_id, command, timeout=60, stdin=None):
    calls.append((project_id, command, timeout, stdin))
    try:
        if command == "hang":
            yield {"type": "out", "data": "开始下载…\n"}
            await asyncio.sleep(3600)
        for part in ["Collecting a\n", "下载 10%\r下载 60%\r下载 100%\n", "Installed\n"]:
            yield {"type": "out", "data": part}
            await asyncio.sleep(0.01)
        out = "Collecting a\n下载 100%\nInstalled\n" + (f"stdin={stdin}" if stdin else "")
        yield {"type": "exit", "exit_code": 0, "timed_out": False, "output": out}
    finally:
        closed.append(command)
sandbox_client.stream = fake_stream

# ---- 1. 一轮对话：实时块 start → update… → 最终块 ----
events = []
async def emit(ev):
    events.append(ev)
async def turn(**kw):
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=emit, **kw)
script.extend([("run_command", {"command": "pip install a", "stdin": "y\n"}), "装好了。"])
reply = asyncio.run(turn())
code_evs = [e for e in events if e["type"] in ("block.start", "block.update") and e["block"]["type"] == "code"]
assert code_evs[0]["type"] == "block.start" and code_evs[0]["block"]["live"] is True, code_evs
assert all(e["type"] == "block.update" and e["index"] == code_evs[0]["index"] for e in code_evs[1:]), code_evs
assert any(e["block"].get("live") and "下载 100%" in e["block"]["source"] and "下载 10%" not in e["block"]["source"] for e in code_evs), code_evs
final = code_evs[-1]["block"]
assert "live" not in final and final["source"].endswith("# 退出码 0") and "stdin=y" in final["source"], final
codes = [b for b in reply.blocks if b["type"] == "code"]
assert len(codes) == 1 and "live" not in codes[0], reply.blocks  # 一张卡，不是实时卡 + 结果卡两张
assert calls[-1] == (pid, "pip install a", 60, "y\n"), calls
tool_msg = [m for m in seen[-1] if m["role"] == "tool"][0]["content"]
assert tool_msg.startswith("退出码 0") and "Installed" in tool_msg, tool_msg
for b in reply.blocks:
    TypeAdapter(Block).validate_python(b)
TypeAdapter(Block).validate_python({**final, "live": True})

# ---- 2. stdin 规则 ----
async def tool(name, **args):
    async with SessionLocal() as db:
        return await REGISTRY[name].run(ToolContext(db=db, project_id=pid, conversation_id=cid), **args)
n = len(calls)
assert "太长" in asyncio.run(tool("run_command", command="cat", stdin="x" * (sandbox_client.STDIN_MAX + 1))).content
assert "不接受 stdin" in asyncio.run(tool("run_command", command="cat", stdin="x", background=True)).content
assert len(calls) == n
assert "stdin" in REGISTRY["run_command"].parameters["properties"]
r = asyncio.run(tool("run_command", command="echo"))  # 不在聊天里（没人挂 live）：照常出最终卡
assert r.blocks[0]["type"] == "code" and "live" not in r.blocks[0]
assert live_tail("a\nb 1%\rb 50%") == "a\nb 50%" and live_tail("x\r\ny") == "x\r\ny"
assert live_tail("\n".join(str(i) for i in range(100))).splitlines()[0] == "60"
assert len(live_tail("x" * 20000)) == 4000

# ---- 3. 中途停止：沙盒流被关、半截回复里没有 live ----
events.clear()
async def stop_midway():
    stop = asyncio.Event()
    t = asyncio.create_task(turn(stop=stop))
    for _ in range(200):
        await asyncio.sleep(0.01)
        if any(e["type"] == "block.start" and e["block"].get("live") for e in events):
            break
    else:
        raise AssertionError(events)
    stop.set(); t.cancel()
    return await t
script.extend([("run_command", {"command": "hang"})])
asyncio.run(stop_midway())
assert "hang" in closed, closed
done = [e for e in events if e["type"] == "message.done"][-1]["message"]
assert done["status"] == "stopped" and done["blocks"][0]["type"] == "code" and "live" not in done["blocks"][0], done
assert "开始下载" in done["blocks"][0]["source"]

# ---- 4. 真 runner：docker 换成本机 bash ----
procs = {}
class FakeApi:
    def exec_create(self, cid_, argv, workdir=None, environment=None):
        eid = f"e{len(procs)}"
        procs[eid] = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      env={**os.environ, **(environment or {})}, cwd=tmp)
        return {"Id": eid}
    def exec_start(self, eid, stream=False):
        p = procs[eid]
        while (b := p.stdout.read1(64)):
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
runner.FLUSH_S = 0.05

r = runner._exec("p1", "read a; read b; echo \"[$a][$b]\"; read c || echo EOF", 10, stdin="一\n二\n")
assert r["exit_code"] == 0 and r["output"] == "[一][二]\nEOF\n", r
r = runner._exec("p1", "read a || echo 空; exit 7", 10)
assert r == {"exit_code": 7, "timed_out": False, "output": "空\n"}, r
assert runner._exec("p1", "sleep 5", 1)["timed_out"] is True

async def collect(cmd, stop_after=None):
    resp = await runner.exec_stream(runner.ExecIn(project_id="p1", command=cmd, timeout=20))
    lines = []
    it = resp.body_iterator
    async for line in it:
        lines.append(json.loads(line))
        if stop_after and len(lines) >= stop_after:
            await it.aclose()
            break
    return lines
lines = asyncio.run(collect("for i in 1 2 3; do echo step$i; sleep 0.15; done"))
outs = [l for l in lines if l["type"] == "out"]
assert len(outs) >= 2 and "".join(l["data"] for l in outs) == "step1\nstep2\nstep3\n", lines
assert lines[-1]["type"] == "exit" and lines[-1]["exit_code"] == 0 and lines[-1]["output"] == "step1\nstep2\nstep3\n", lines
mark = os.path.join(tmp, "still-running")
t0 = time.time()
lines = asyncio.run(collect(f"echo go; sleep 1.5; touch {mark}", stop_after=1))
assert lines == [{"type": "out", "data": "go\n"}], lines
time.sleep(2)
assert not os.path.exists(mark), "断开后命令应被整组杀掉"
assert not any(f.startswith(".exec-") and os.path.getmtime(f"/tmp/{f}") > t0 for f in os.listdir("/tmp")), "pid 文件应被清掉"
try:
    asyncio.run(runner.exec_stream(runner.ExecIn(project_id="p1", command="cat", stdin="x" * (runner.STDIN_MAX + 1))))
    raise AssertionError("超长 stdin 应 413")
except runner.HTTPException as e:
    assert e.status_code == 413
print("smoke_live_output ok")
