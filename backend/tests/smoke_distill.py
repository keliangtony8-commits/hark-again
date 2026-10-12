# 冒烟：v1.66 超长日志型工具输出的中间段要点（agent/distill.py，移植自 Gemini CLI toolDistillationService）。
# 1) 移植的单测（toolDistillationService.test.ts）：超过摘要阈值 → 调便宜模型、结果带摘要段；超过上限但低于摘要阈值 → 不调；
#    超过 MAX_SOURCE → 不调；截断结果带落盘路径。
# 2) 我们的规则：信号行只取被省略的中间段、带字符位置、相同行合并 ×N、超量保留前 1/3 后 2/3；rules 零调用；off / 非日志工具
#    与 spill.bound 一字不差；没截断原样；沙盒已落盘的结果读回全文挑行、不另存文件；模型失败 / 超时 → 退回信号行；
#    结果总长 ≤ 上限；落盘全文仍是原文。
# 3) 模拟模型：一轮里 run_command 吐 120k 字日志，报错在正中间；模型下一次调用里看得到那行报错和摘要。
# 运行：python tests/smoke_distill.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import llm, spill
from app.config import settings
from app.storage import project_dir
from app.agent import distill, loop
from app.agent.tools import ToolContext, ToolResult, REGISTRY, load_builtin, tool
from app.db import SessionLocal
from app.models import Conversation, UsageRecord
from sqlalchemy import select

WS = "wsdistill"
LIMIT = 16000
calls: list[dict] = []
reply = {"text": "退出码 2；src/app.py:42 TypeError", "fail": None}


async def fake_complete(messages, model=None, kind="summary", **kw):
    calls.append({"messages": messages, "model": model, "kind": kind, **kw})
    if reply["fail"] == "error":
        raise RuntimeError("boom")
    if reply["fail"] == "slow":
        await asyncio.sleep(5)
    return reply["text"]

real_complete = llm.complete
llm.complete = fake_complete


def log(n_lines, middle=None, width=60):
    lines = [f"compiling module {i:05d} " + "." * width for i in range(n_lines)]
    if middle:
        k = n_lines // 2
        lines[k:k] = middle
    return "\n".join(lines)


def run(coro):
    return asyncio.run(coro)

files = lambda: sorted((project_dir(WS) / ".spill").iterdir()) if (project_dir(WS) / ".spill").exists() else []

# ---- 1. 移植的单测 ----
# 超过摘要阈值（80k）：调模型，结果带摘要段 + 落盘路径
big = log(1500, ["ERROR: src/app.py:42 TypeError: bad operand"])
assert len(big) > settings.tool_distill_chars
out = run(distill.bound(big, LIMIT, WS, "run_command"))
assert len(calls) == 1 and calls[0]["kind"] == "distill" and calls[0]["model"] == settings.summary_model
assert "便宜模型从全文摘的" in out and reply["text"] in out, out[-300:]
assert "完整内容（" in out and ".spill/" in out
body = calls[0]["messages"][0]["content"]
assert "ERROR: src/app.py:42" in body and "run_command" in body and len(body) < distill.INPUT_MAX + 2000
assert len(out) <= LIMIT
saved = files()[-1].read_text(encoding="utf-8")
assert saved == big, "落盘是原文"
print("ok: over summarization threshold → model summary")

# 超过上限但低于摘要阈值：不调模型（信号行仍补上）
calls.clear()
mid = log(400, ["npm ERR! code ELIFECYCLE"])
assert LIMIT < len(mid) < settings.tool_distill_chars
out = run(distill.bound(mid, LIMIT, WS, "run_command"))
assert not calls and "npm ERR! code ELIFECYCLE" in out and "本地挑出的" in out and len(out) <= LIMIT
print("ok: below summarization threshold → no model call")

# 超过 MAX_SOURCE：不调模型
massive = log(16000, ["Traceback (most recent call last):"], width=60)
assert len(massive) > distill.MAX_SOURCE
out = run(distill.bound(massive, LIMIT, WS, "run_command"))
assert not calls and "Traceback" in out and len(out) <= LIMIT
print("ok: over MAX_SOURCE → no model call")

# ---- 2. 我们的规则 ----
# 信号行：只取中间段；位置正确；相同行合并；首尾的报错不重复列
text = "error at head\n" + log(300, ["warning: x unused", "warning: x unused", "FAILED test_a"]) + "\nerror at tail"
lines = distill.signals(text, 20, len(text) - 20)
assert any("FAILED test_a" in l for l in lines) and any("（×2）" in l for l in lines), lines
assert not any("error at head" in l or "error at tail" in l for l in lines)
for l in lines:
    pos = int(l.split()[0][1:])
    assert text[pos:].startswith(l.split(" ", 1)[1].split("（×")[0]), l
# 超量：前 1/3 + 后 2/3
many = "\n".join(f"error {i}" for i in range(200))
lines = distill.signals(many, 0, len(many))
assert len(lines) == distill.SIGNAL_LINES + 1 and "error 0" in lines[0] and "error 199" in lines[-1]
assert "还有 170 行" in lines[distill.SIGNAL_LINES // 3]
# 中间段从行中间开始 → 从下一整行算
assert distill.signals("aaa error\nok\nerror b", 2, 21) == ["@13 error b"]
print("ok: signals")

# rules 零调用；off / 非日志工具 / 没截断 = spill.bound
settings.tool_distill = "rules"
out = run(distill.bound(big, LIMIT, WS, "run_command"))
assert not calls and "ERROR: src/app.py:42" in out and "本地挑出的" in out
settings.tool_distill = "off"
n = len(files())
out = run(distill.bound(big, LIMIT, WS, "run_command"))
assert "中间段里的要点" not in out and len(files()) == n + 1
settings.tool_distill = "auto"
out = run(distill.bound(big, LIMIT, WS, "web_fetch"))
assert not calls and "中间段里的要点" not in out
small = "退出码 1\nerror: tiny"
assert run(distill.bound(small, LIMIT, WS, "run_command")) == small
assert distill.mode() == "auto"
settings.tool_distill = "bogus"; assert distill.mode() == "auto"; settings.tool_distill = "auto"
# 中间没有信号、低于摘要阈值：就是普通截断（无要点段）
plain = log(400)
out = run(distill.bound(plain, LIMIT, WS, "run_command"))
assert "中间段里的要点" not in out and "中间省略" in out and len(out) <= LIMIT
print("ok: modes, non-log tools, small output")

# 沙盒已截断并落盘：读回全文挑行，不另存
full = log(800, ["E   AssertionError: expected 3 got 4", "1 failed, 87 passed in 3.2s"])
prior = spill.save(WS, "run_command", full)
head, tail = full[:6000], full[-6000:]
content = "退出码 1\n" + head + spill.notice(len(full) - 12000, prior, len(full)) + tail
loc = spill.located(content)
assert loc and content[loc[0]:loc[1]].startswith("\n…（中间省略") and content[loc[1]:] == tail
n = len(files())
out = run(distill.bound(content, LIMIT, WS, "run_command"))
assert len(files()) == n, "沿用沙盒存的文件"
assert "AssertionError: expected 3 got 4" in out and "1 failed, 87 passed" in out and len(out) <= LIMIT
assert out.startswith(content), "沙盒结果原样保留，只在末尾补要点"
assert not calls  # 全文 < 80k
print("ok: sandbox-spilled result read back")

# 模型失败 / 超时 → 退回信号行
reply["fail"] = "error"
out = run(distill.bound(big, LIMIT, WS, "run_command"))
assert len(calls) == 1 and "本地挑出的" in out and "ERROR: src/app.py:42" in out
distill.TIMEOUT_S = 0.2
reply["fail"] = "slow"; calls.clear()
out = run(distill.bound(big, LIMIT, WS, "run_command"))
assert len(calls) == 1 and "本地挑出的" in out
reply["fail"] = None; distill.TIMEOUT_S = 15
# 空摘要 → 信号行
reply["text"] = "  "; calls.clear()
out = run(distill.bound(big, LIMIT, WS, "run_command"))
assert "本地挑出的" in out
reply["text"] = "退出码 2；src/app.py:42 TypeError"
# 各种长度都 ≤ 上限
for n_lines in (250, 260, 300, 1000, 3000):
    t = log(n_lines, [f"error line {i}" for i in range(50)])
    for lim in (4000, 8000, 16000):
        assert len(run(distill.bound(t, lim, WS, "run_command"))) <= lim
print("ok: fallbacks + length bound")

# ---- 3. 模拟模型 ----
calls.clear()
llm.complete = real_complete
load_builtin()
DUMP = log(1800, ["src/server.ts:88:13 - error TS2345: Argument of type 'string' is not assignable"])

@tool("run_command", "正在运行", "跑命令（测试替身）", {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]})
async def fake_run(ctx, command):
    return ToolResult("退出码 2\n" + DUMP)

script: list = []
model_saw: list[list] = []
judge: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    if not stream:  # 便宜模型摘要
        judge.append(messages)
        return NS(choices=[NS(message=NS(content="退出码 2；src/server.ts:88 TS2345"), finish_reason="stop")],
                  usage=NS(prompt_tokens=6000, completion_tokens=30))
    model_saw.append(json.loads(json.dumps(messages, ensure_ascii=False)))
    step = script.pop(0)
    async def gen():
        if isinstance(step, tuple):
            name, args = step
            yield chunk(tool=[NS(index=0, id="k1", function=NS(name=name, arguments=json.dumps(args)))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create


async def main():
    script.extend([("run_command", {"command": "npm run build"}), "构建失败：TS2345 在 src/server.ts:88。"])
    async with SessionLocal() as db:
        db.add(Conversation(id="d1", title="t")); await db.commit()
        ctx = ToolContext(db=db, conversation_id="d1")
        _ = [e async for e in loop.run("sys", [{"role": "user", "content": "构建一下"}], ctx)]
        ws = ctx.workspace
    assert len(model_saw) == 2 and len(judge) == 1, (len(model_saw), len(judge))
    seen = [m["content"] for m in model_saw[1] if m["role"] == "tool"][0]
    assert len(seen) <= settings.tool_result_max
    assert "退出码 2；src/server.ts:88 TS2345" in seen and "中间省略" in seen
    assert "error TS2345" not in seen.split("中间段里的要点")[0], "报错在正中间：首尾截断本来看不到"
    path = seen.split("存在 ")[1].split("，")[0]
    assert (project_dir(ws) / path).read_text(encoding="utf-8") == "退出码 2\n" + DUMP
    async with SessionLocal() as db:
        kinds = [r.kind for r in (await db.execute(select(UsageRecord))).scalars()]
    assert "distill" in kinds, kinds
    print("ok: turn sees the middle error via summary")

asyncio.run(main())
print("ALL OK")
