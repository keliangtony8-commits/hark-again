# 冒烟：长任务预算 + 原地打转检测（loop_guard.py 移植自 Gemini CLI loopDetectionService，Apache-2.0）。
# 一、Gemini 的单元用例（工具调用周期 1/2/3/5、内容复读、代码块/表格/列表/标题/引用/分隔线重置、两次 strike、复位）翻译过来；
# 二、我们的改动：结果不同 = 有进展不算打转；分隔线正则不再把 "OK"/数字当分隔线；
# 三、模拟模型整轮：①同样调用同样结果 5 次 → 提醒，模型再犯 → 停下并说明；②提醒后改正 → 正常收尾；
#    ③结果每次不同（轮询有新输出）跑 12 步不误判；④步数预算到 → 最后一步不给工具 + 交代进度提示；⑤token 预算；
#    ⑥文字复读 → 流被掐断、提醒、再复读 → 停下；⑦同批剩余调用不执行但都有结果；⑧旧的 6 步上限不再有。
# 运行：python tests/smoke_loop_guard.py
import os, sys, asyncio, subprocess, tempfile, json, random, string
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import llm
from app.config import settings
from app.agent import loop, loop_guard
from app.agent.loop_guard import LoopGuard, TOOL_CALL_LOOP_THRESHOLD as T, CONTENT_LOOP_THRESHOLD as C, CONTENT_CHUNK_SIZE as K
from app.agent.tools import ToolContext, ToolResult, tool, load_builtin
from app.db import SessionLocal
from app.models import Conversation

# —— 一、Gemini 用例 ——
def rep(i, n):
    base, s = f"This is a unique sentence, id={i}. ", ""
    while len(s) < n:
        s += base
    return s[:n]

def rnd(n):
    return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(n))

g = LoopGuard()
assert all(g.tool("t", {"p": "v"}) == 0 for _ in range(T - 1))
assert g.tool("t", {"p": "v"}) == 1
g = LoopGuard()
for _ in range(T - 2):
    assert g.tool("t", {"p": "1"}) == 0 and g.tool("t", {"p": "2"}) == 0 and g.tool("o", {"p": "1"}) == 0
for k in (2, 3, 5):  # 周期 k 的循环
    g, seq, out = LoopGuard(), [("t", {"i": j}) for j in range(k)], 0
    for _ in range(T):
        for n, a in seq:
            out = g.tool(n, a) or out
    assert out == 1, k
g, out = LoopGuard(), 0  # 交替但会变：不算
for i in range(T * 2):
    out = g.tool("read", {"f": "a"}) or out
    out = g.tool("edit", {"f": "a", "v": i}) or out
assert out == 0
print("ok: tool cycles")

g = LoopGuard()
assert all(g.content(rnd(10)) == 0 for _ in range(1000))
g, out = LoopGuard(), 0
for _ in range(C):
    out = g.content(rep(1, K))
assert out == 1
g = LoopGuard()
prefix = "projects/my-google-cloud-project-12345/locations/us-central1/services/"
assert g.content("".join(f"- {prefix}{i}\n" for i in range(15))) == 0
g, out = LoopGuard(), 0
for _ in range(C):
    out = g.content(rep(1, K)) or g.content(rnd(500)) or out
assert out == 0
for pat, times in ((rep(1, 150), C + 2), ("I will not output any text.\n  I will just end the turn.\n  I am done.\n", C + 5),
                   ("I have added all the requested logs and verified the test file. I will now mark the task as complete.\n  ", C + 5),
                   ("Thinking... Done. ", C * 3), ("我需要检查文件。文件不存在。我来创建文件。", C + 5)):
    g, out = LoopGuard(), 0
    for _ in range(times):
        if (out := g.content(pat)):
            break
    assert out == 1, pat
g, out = LoopGuard(), 0  # 代码块里的重复不算
g.content("```python\n")
for _ in range(C + 5):
    out = g.content(rep(1, K)) or out
assert out == 0
g.content("\n```\n")
for _ in range(C + 1):
    out = g.content(rep(2, K)) or out
assert out == 1  # 代码块之后的复读照算
for marker in ("| a | b |\n", "- item\n", "1. item\n", "## 标题\n", "> 引用\n"):
    g = LoopGuard()
    for _ in range(C - 1):
        g.content(rep(1, K))
    g.content(marker)  # 换了排版元素：计数重来
    assert g.content(rep(1, K)) == 0, marker
for div in ("-" * K, "╭─" * (K // 2)):
    g = LoopGuard()
    assert all(g.content(div) == 0 for _ in range(C + 5))
assert LoopGuard().content("") == 0
g = LoopGuard()  # 两次 strike
for _ in range(T):
    g.tool("t", {"p": "v"})
assert g.tool("t", {"p": "v"}) == 1
g.recovered()
assert g.tool("t", {"p": "v"}) == 2
g = LoopGuard()
for _ in range(T):
    g.tool("t", {"p": "v"})
g.recovered()
assert g.content("Recovery text") == 0
g = LoopGuard()  # 工具调用清掉文字计数
for _ in range(9):
    g.content("Some content.")
g.tool("t", {})
assert g.content("Fresh content.") == 0 and g.stream == "Fresh content."
print("ok: gemini content cases")

# —— 二、我们的改动 ——
g = LoopGuard()
assert all(g.tool("job_status", {"job_id": "j"}, f"新输出 {i}") == 0 for i in range(20))  # 有进展
g = LoopGuard()
assert all(g.tool("t", {"a": 1, "b": 2}, "同") == 0 for _ in range(T - 1))
assert g.tool("t", {"b": 2, "a": 1}, "同") == 1  # 参数键顺序不同也是同一个调用
g = LoopGuard()
g.content("OK")
assert g.stream == "OK"  # 原版会把 "OK" 当分隔线跳过
assert loop_guard._DIVIDER.match("2026") is None and loop_guard._DIVIDER.match("=====")
print("ok: our changes")

# —— 三、模拟模型整轮 ——
calls: list[dict] = []
@tool("fake_probe", "正在探测", "测试用", {"type": "object", "properties": {"x": {"type": "integer"}, "same": {"type": "boolean"}}})
async def fake_probe(ctx, x: int = 0, same: bool = True) -> ToolResult:
    calls.append({"x": x})
    return ToolResult("端口还没起来" if same else f"第 {len(calls)} 次：新进展")

script: list = []
saw: list[dict] = []
def chunk(text=None, tools=None, u=None):
    if text is None and tools is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tools))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    saw.append({"messages": json.loads(json.dumps(messages, ensure_ascii=False)), "tools": bool(tools)})
    step = script.pop(0) if script else "收尾"
    if isinstance(step, list) and not tools:
        step = "收尾"  # 没给工具：模型只能说话
    async def gen():
        if isinstance(step, list):  # 一批工具调用
            yield chunk(tools=[NS(index=i, id=f"c{len(saw)}_{i}", function=NS(name="fake_probe", arguments=json.dumps(a)))
                               for i, a in enumerate(step)])
        elif isinstance(step, tuple):  # 流式文字片段
            for piece in step:
                yield chunk(piece)
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=1000, completion_tokens=0))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()
n = 0

async def run(*steps):
    global n
    n += 1
    script[:] = list(steps)
    saw.clear(); calls.clear()
    async with SessionLocal() as db:
        db.add(Conversation(id=f"c{n}", title="t")); await db.commit()
        evs = [e async for e in loop.run("sys", [{"role": "user", "content": "把服务跑起来"}], ToolContext(db=db, conversation_id=f"c{n}"))]
    done = evs[-1]
    assert isinstance(done, loop.Done)
    return "".join(b.get("text", "") for b in done.blocks if b["type"] == "text")

def nudged(i):
    return any(m["role"] == "user" and str(m["content"]).startswith("[系统提示] 可能在原地打转") for m in saw[i]["messages"])

async def main():
    same = [{"x": 1}]
    text = await run(*[same] * 10)
    assert len(calls) == T + 1, len(calls)  # 第 5 次提醒，第 6 次再犯就停
    assert not nudged(T - 1) and nudged(T), "提醒出现在第 6 次调用模型时"
    assert text.endswith(loop_guard.STOP_NOTE) and len(saw) == T + 1
    print("ok: repeated call → nudge → stop")

    text = await run(*[same] * T, [{"x": 2}], "改了端口，跑起来了")
    assert text == "改了端口，跑起来了" and nudged(T) and len(calls) == T + 1
    print("ok: nudge → model changes course")

    text = await run(*[[{"x": 1, "same": False}]] * 12, "装好了")
    assert text == "装好了" and len(calls) == 12 and not any(nudged(i) for i in range(len(saw)))
    print("ok: progress is not a loop; >6 steps allowed")

    settings.agent_max_steps = 4
    text = await run(*[[{"x": i}] for i in range(10)])
    assert len(saw) == 4 and len(calls) == 3 and text == "收尾"
    assert saw[3]["tools"] is False and saw[3]["messages"][-1]["content"] == loop.WRAP_UP
    assert all(s["tools"] for s in saw[:3])
    settings.agent_max_steps = 1
    text = await run([{"x": 1}])
    assert len(saw) == 1 and not saw[0]["tools"] and saw[0]["messages"][-1]["content"] == "把服务跑起来"
    settings.agent_max_steps = 40
    print("ok: step budget wraps up without tools")

    settings.agent_turn_tokens = 2500
    await run(*[[{"x": i}] for i in range(10)])
    assert len(saw) == 4 and len(calls) == 3 and saw[3]["messages"][-1]["content"] == loop.WRAP_UP
    settings.agent_turn_tokens = 0
    await run(*[[{"x": i}] for i in range(45)])
    assert len(saw) == 40 and len(calls) == 39  # 默认 40 步
    settings.agent_turn_tokens = 600_000
    print("ok: token budget")

    chant = tuple(["我再检查一下。"] * 60)
    text = await run(chant, "查清楚了：端口被占用")
    assert text.endswith("查清楚了：端口被占用") and text.count("我再检查一下。") < 60 and nudged(1)
    asst = [m for m in saw[1]["messages"] if m["role"] == "assistant"]
    assert asst and asst[-1]["content"].startswith("我再检查一下。")
    text = await run(chant, chant, "不会到这里")
    assert text.endswith(loop_guard.STOP_NOTE) and len(saw) == 2
    print("ok: chanting → cut → nudge → stop")

    text = await run(*[same] * (T - 1), [{"x": 1}, {"x": 9}, {"x": 8}], [{"x": 3}], "好了")
    assert [c["x"] for c in calls[T - 1:]] == [1, 3], calls  # 第 5 次命中后同批剩下的不执行
    batch = saw[T]["messages"]
    ids = [c["id"] for m in batch if m.get("tool_calls") for c in m["tool_calls"]]
    answered = {m["tool_call_id"] for m in batch if m["role"] == "tool"}
    assert set(ids) <= answered and sum(m["content"] == loop.SKIPPED for m in batch if m["role"] == "tool") == 2
    assert text == "好了"
    print("ok: rest of batch skipped but answered")

asyncio.run(main())
print("ALL OK")
