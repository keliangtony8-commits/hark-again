# 冒烟：v1.60 同一步里的只读工具调用并行（agent/parallel.py，移植自 deepseek-harness tool-calls）。模拟模型。
# 1) mode 失败即独占：risk / form / quiet / grants / 非 dict 参数 / 判定函数返回非 True 或抛错 → 独占；
# 2) groups：连续可并行成组，独占自成屏障；并行关掉（≤1）每个独占；
# 3) pool：滚动池同时数不超过 cap；内核异常 → 取消其余并抛出；被关掉 → 已开始的全取消；
# 4) 真实一轮 [r1 r2 r3 w r4 r5]：前三个同时跑（峰值 3），w 等它们全结束才开始，r4 r5 等 w 结束；
#    工具结果按模型顺序、id 一一对应；时间线 6 步全 done；每个并行调用拿到独立的 ctx（共用 db）；
# 5) 并行工具抛错 → 只有它是错误结果，别的照常；
# 6) 真实内置 read_file / glob / grep 一起发 → 结果正确、顺序对；
# 7) 中途停止：loop.run 被关掉时并行中的工具全部被取消；
# 8) 关掉（AGENT_PARALLEL_TOOLS=1）→ 峰值 1；系统提示里有/没有并行提示。
# 运行：python tests/smoke_parallel_tools.py
import os, sys, asyncio, subprocess, tempfile, json, time
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', LLM_MAX_RETRIES="0")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from contextlib import aclosing
from app import llm
from app.config import settings
from app.agent import loop, parallel
from app.agent.context import build_system_prompt
from app.agent.runner import run_turn
from app.agent.tools import REGISTRY, Tool, ToolContext, ToolResult, tool, load_builtin
from app.agent.tool_args import Parsed
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message
from app.storage import project_dir
from app.workspaces import PERSONAL

OBJ = {"type": "object", "properties": {"k": {"type": "string"}}, "required": ["k"]}
log: list = []          # (事件, 名字, 时间)
live_now = [0]
peak = [0]
ctxs: list = []
cancelled: list = []

async def _work(name: str, ctx, delay: float = 0.3):
    ctxs.append(ctx)
    live_now[0] += 1; peak[0] = max(peak[0], live_now[0])
    log.append(("start", name, time.monotonic()))
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        cancelled.append(name); raise
    finally:
        live_now[0] -= 1
        log.append(("end", name, time.monotonic()))

@tool("slow_read", "正在读", "测试用只读", OBJ, parallel=True)
async def slow_read(ctx, k: str) -> ToolResult:
    if k == "boom":
        await asyncio.sleep(0.05)
        raise RuntimeError("读炸了")
    await _work(k, ctx, 2.0 if k.startswith("hang") else 0.3)
    return ToolResult(f"读到 {k}")

@tool("slow_write", "正在写", "测试用独占", OBJ)
async def slow_write(ctx, k: str) -> ToolResult:
    await _work(k, ctx)
    return ToolResult(f"写了 {k}")

# ---- 1. mode ----
async def _noop(ctx, **kw): return ToolResult("")
def T(**kw): return Tool("t", "t", "t", OBJ, _noop, **kw)
assert parallel.mode(T(parallel=True), {"k": "a"})
assert not parallel.mode(T(), {"k": "a"})                       # 默认独占
assert not parallel.mode(None, {})
assert not parallel.mode(T(parallel=True), None)                # 参数解析不了
assert not parallel.mode(T(parallel=True), "raw")
assert not parallel.mode(T(parallel=True, risk=lambda a, c: "x"), {})
async def _form(ctx, args): return None
assert not parallel.mode(T(parallel=True, form=_form), {})
assert not parallel.mode(T(parallel=True, quiet=True), {})
assert not parallel.mode(T(parallel=True, grants=True), {})
assert parallel.mode(T(parallel=lambda a: a.get("k") == "a"), {"k": "a"})
assert not parallel.mode(T(parallel=lambda a: "yes"), {"k": "a"})   # 只认确切的 True
def _raise(a): raise ValueError
assert not parallel.mode(T(parallel=_raise), {"k": "a"})
print("ok: mode fail-closed")

# ---- 2. groups ----
assert parallel.groups([]) == []
assert parallel.groups([True, True, True, False, True, True]) == [[0, 1, 2], [3], [4, 5]]
assert parallel.groups([False, False]) == [[0], [1]]
assert parallel.groups([True, False, True]) == [[0], [1], [2]]
assert parallel.groups([False, True, True]) == [[0], [1, 2]]
settings.agent_parallel_tools = 1
assert parallel.groups([True, True]) == [[0], [1]] and parallel.prompt() == ""
settings.agent_parallel_tools = 8
assert parallel.prompt() == parallel.PROMPT
print("ok: groups")

# ---- 3. pool ----
async def pool_cases():
    now, top = [0], [0]
    async def one(k):
        now[0] += 1; top[0] = max(top[0], now[0])
        await asyncio.sleep(0.05 * (5 - k))
        now[0] -= 1
        yield f"ev{k}"
        yield ToolResult(f"r{k}")
    got, evs = {}, []
    async with aclosing(parallel.pool(5, one, cap=2)) as it:
        async for x in it:
            if isinstance(x, parallel.Settled): got[x.index] = x.result.content
            else: evs.append(x)
    assert top[0] == 2 and got == {k: f"r{k}" for k in range(5)} and sorted(evs) == [f"ev{k}" for k in range(5)], (top, got)
    # 内核异常 → 其余取消 + 抛出
    hit = []
    async def bad(k):
        if k == 1:
            await asyncio.sleep(0.05); raise KeyError("bug")
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            hit.append(k); raise
        yield ToolResult("x")
    try:
        async with aclosing(parallel.pool(3, bad)) as it:
            async for _ in it: pass
        raise AssertionError("should raise")
    except KeyError:
        pass
    assert sorted(hit) == [0, 2], hit
    # 消费方提前关掉 → 已开始的全取消
    hit.clear()
    async def slow(k):
        try:
            yield f"go{k}"
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            hit.append(k); raise
        yield ToolResult("x")
    async with aclosing(parallel.pool(3, slow)) as it:
        n = 0
        async for _ in it:
            n += 1
            if n == 3: break
    assert sorted(hit) == [0, 1, 2], hit
asyncio.run(pool_cases())
print("ok: pool")

# ---- fake model ----
script: list = []
sent: list = []
def chunk(text=None, tools=None, u=None):
    if text is None and tools is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tools))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    sent.append(json.loads(json.dumps(messages, ensure_ascii=False)))
    step = script.pop(0) if script else "收尾"
    async def gen():
        if isinstance(step, list):
            yield chunk(tools=[NS(index=i, id=f"c{len(sent)}_{i}", function=NS(name=n, arguments=a))
                               for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=100, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()

async def seed():
    async with SessionLocal() as db:
        conv = Conversation(title="并行"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("读一堆东西")))
        await db.commit()
        return conv.id
async def turn(cid):
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid))
def run(steps):
    script[:] = list(steps); sent.clear(); log.clear(); ctxs.clear(); cancelled.clear(); peak[0] = 0
    cid = asyncio.run(seed())
    return asyncio.run(turn(cid))
def a(k): return json.dumps({"k": k})
def tool_msgs(msgs): return [m for m in msgs if m["role"] == "tool"]
def at(ev, name): return next(t for e, n, t in log if e == ev and n == name)

# ---- 4. 屏障 + 并行 + 顺序 ----
t0 = time.monotonic()
reply = run([[("slow_read", a("r1")), ("slow_read", a("r2")), ("slow_read", a("r3")), ("slow_write", a("w")),
              ("slow_read", a("r4")), ("slow_read", a("r5"))], "好了"])
took = time.monotonic() - t0
assert reply.status == "done", reply.status
assert peak[0] == 3, peak
assert at("start", "w") >= max(at("end", x) for x in ("r1", "r2", "r3")) - 0.001
assert min(at("start", x) for x in ("r4", "r5")) >= at("end", "w") - 0.001
assert took < 1.6, took   # 顺序跑要 1.8 秒+，并行约 0.9 秒
ass = next(m for m in sent[-1] if m["role"] == "assistant" and m.get("tool_calls"))
tm = tool_msgs(sent[-1])
assert [m["tool_call_id"] for m in tm] == [c["id"] for c in ass["tool_calls"]]
assert [m["content"] for m in tm] == ["读到 r1", "读到 r2", "读到 r3", "写了 w", "读到 r4", "读到 r5"], [m["content"] for m in tm]
steps = reply.steps
assert len(steps) == 6 and all(s["state"] == "done" for s in steps), steps
par = ctxs[:3]
assert len({id(c) for c in par}) == 3 and len({id(c.db) for c in par}) == 1  # 并行调用各自一份 ctx，共用 db
print(f"ok: barrier + parallel + model order ({took:.2f}s, peak {peak[0]})")

# ---- 5. 并行中一个出错 ----
reply = run([[("slow_read", a("x1")), ("slow_read", a("boom")), ("slow_read", a("x2"))], "好"])
tm = tool_msgs(sent[-1])
assert tm[0]["content"] == "读到 x1" and tm[1]["content"].startswith("工具出错：读炸了") and tm[2]["content"] == "读到 x2", tm
states = [s["state"] for s in reply.steps]
assert sorted(states) == ["done", "done", "error"], states
print("ok: one failure isolated")

# ---- 6. 真实内置只读工具 ----
ws = project_dir(PERSONAL); ws.mkdir(parents=True, exist_ok=True)
(ws / "a.txt").write_text("alpha 内容\n"); (ws / "b.md").write_text("beta needle\n")
reply = run([[("read_file", json.dumps({"path": "a.txt"})), ("glob", json.dumps({"pattern": "*.md"})),
              ("grep", json.dumps({"pattern": "needle"})), ("list_files", "{}")], "看完了"])
tm = tool_msgs(sent[-1])
assert "alpha 内容" in tm[0]["content"] and "b.md" in tm[1]["content"] and "b.md" in tm[2]["content"] \
    and "a.txt" in tm[3]["content"], [m["content"][:40] for m in tm]
assert reply.status == "done" and all(s["state"] == "done" for s in reply.steps)
for n in ("read_file", "glob", "grep", "list_files", "web_search", "web_fetch"):
    assert REGISTRY[n].parallel is True, n
for n in ("write_file", "edit_file", "run_command", "job_status", "browser_open", "update_plan"):
    assert n not in REGISTRY or not parallel.mode(REGISTRY[n], {}), n
print("ok: builtin read-only tools in parallel")

# ---- 7. 中途停止 ----
async def stop_midway():
    script[:] = [[("slow_read", a("hang1")), ("slow_read", a("hang2")), ("slow_read", a("hang3"))]]
    cancelled.clear()
    async with SessionLocal() as db:
        ctx = ToolContext(db=db)
        builder = loop.MessageBuilder()
        running = 0
        async with aclosing(loop.run("sys", [{"role": "user", "content": "x"}], ctx, builder)) as it:
            async for ev in it:
                if isinstance(ev, loop.ToolStatus) and ev.state == "running":
                    running += 1
                    if running == 3:
                        await asyncio.sleep(0.1)
                        break
        assert sorted(cancelled) == ["hang1", "hang2", "hang3"], cancelled
        assert all(s["state"] == "stopped" for s in builder.steps(stopped=True)), builder.steps(stopped=True)
        assert live_now[0] == 0
asyncio.run(stop_midway())
print("ok: stop cancels in-flight parallel calls")

# ---- 8. 关掉 ----
settings.agent_parallel_tools = 1
reply = run([[("slow_read", a("o1")), ("slow_read", a("o2"))], "好"])
assert peak[0] == 1 and reply.status == "done"
async def prompts():
    async with SessionLocal() as db:
        off = await build_system_prompt(db, None)
        settings.agent_parallel_tools = 8
        on = await build_system_prompt(db, None)
    assert parallel.PROMPT not in off and parallel.PROMPT in on
asyncio.run(prompts())
print("ok: off + prompt")
print("ALL OK")
