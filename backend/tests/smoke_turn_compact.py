# 冒烟：一轮回复里的上文压缩（agent/compact.py：移植 deepseek-harness compaction，嫁接 Gemini CLI / Codex）。
# 一、单元：token 估算、工具配对切口、剪工具结果（deepseek 阈值边界）、保护最近 3 批、选区不拆调用/结果、
#    retain=0 只留最新单元、超长错误识别、supersede 下标搬移、摘要请求超长时丢最旧一段；
# 二、模拟模型整轮：①上文过 80% → 写检查点（重放上文 + 指令在最后、带工具 tool_choice=none）→ 之后每次请求
#    都有检查点、当前这一问原样在、工具调用与结果从不拆散，时间线有“整理上文”；②再次过线 → 新检查点合并旧的（不叠层）；
#    ③只剪就够 → 不调摘要；④摘要失败 / 被截断 / 比原文还长 → 不换，之后只剪不再摘要，这一轮照常做完；
#    ⑤供应商报上文超长 → 强制压一次重试成功；压不动 → 原错误抛出；连续两次超长 → 不无限重试。
# 运行：python tests/smoke_turn_compact.py
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

from app import llm
from app.config import settings
settings.tool_mask_min_tokens = 0  # 只测压缩本身：旧输出遮盖（v1.65，tool_mask.py）在压缩之前跑，会先把长结果换掉
from app.agent import loop, compact, supersede
from app.agent.compact import (PRUNE_THRESHOLD as TH, PRUNE_HEAD as H, PRUNE_TAIL as TL, PRUNE_MARKER as MK,
                               CHECKPOINT_PREAMBLE, INSTRUCTION, SUMMARY_OPEN)
from app.agent.tools import ToolContext, ToolResult, tool, load_builtin
from app.db import SessionLocal
from app.models import Conversation

# —— 一、单元 ——
assert compact.approx_tokens("abcd") == 1 and compact.approx_tokens("abcde") == 2
assert compact.approx_tokens("中文字") == 3  # 9 字节 / 4 → 3
assert compact.message_tokens({"role": "user", "content": [{"type": "text", "text": "abcd"}, {"type": "image_url"}]}) \
    == 1 + compact.IMAGE_TOKENS + 4

def call(i, n=1):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": f"c{i}_{k}", "type": "function", "function": {"name": "t", "arguments": "{}"}} for k in range(n)]}
def res(i, text="ok", k=0):
    return {"role": "tool", "tool_call_id": f"c{i}_{k}", "content": text}

msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}, call(1, 2), res(1), res(1, k=1),
        {"role": "assistant", "content": "说一句"}, call(2), res(2)]
assert compact.balanced_cuts(msgs) == [True, True, True, False, False, True, True, False, True]
print("ok: estimate + balance")

# deepseek 阈值边界：正好 8192 不剪，8193 剪；结果 = 头 4096 + 说明 + 尾 1024
assert compact.prune_text("a" * TH) is None
p = compact.prune_text("h" * H + "m" * (TH + 1 - H - TL) + "t" * TL)
assert p == "h" * H + MK + "t" * TL and len(p) < TH
emoji = "😀" * (TH + 5)  # Python str 按码点切，不会拆坏
assert compact.prune_text(emoji) == "😀" * H + MK + "😀" * TL
big = "x" * (TH + 100)
m = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]
for i in range(5):
    m += [call(i), res(i, big + str(i))]
orig = [dict(x) for x in m]
removed = compact.prune(m, 2)
assert removed == 2 * (len(big) + 1 - H - len(MK) - TL), removed
assert m[3]["content"].endswith(MK + big[-(TL - 1):] + "0") and m[5]["content"].count(MK) == 1
assert all(m[i]["content"] == orig[i]["content"] for i in (7, 9, 11)), "最近 3 批原样"
assert orig[3]["content"] == big + "0", "不改原 dict"
assert compact.prune(m, 2) == 0  # 剪过的不再剪
print("ok: prune (thresholds, protected batches, idempotent)")

# 选区：保留尾巴 ≥ retain，切口不拆调用/结果
m = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]
for i in range(6):
    m += [call(i, 2), res(i, "r" * 400), res(i, "r" * 400, k=1)]
s, e = compact.select_range(m, 2, 250)
assert s == 2 and compact.balanced_cuts(m)[e] and m[e]["role"] == "assistant"
assert sum(compact.message_tokens(x) for x in m[e:]) >= 250
assert compact.select_range(m, 2, 10 ** 9) is None  # 整轮都在保留区内：不值得
s, e = compact.select_range(m, 2, 0)  # 强制：只留最新一个完整单元
assert m[e] is m[-3] and e == len(m) - 3
assert compact.select_range(m[:5], 2, 0) is None  # 只有一个单元：压不了
print("ok: select_range")

class Err(Exception):
    def __init__(self, msg, code=None, body=None):
        super().__init__(msg); self.code = code; self.body = body
assert compact.is_overflow(Err("x", code="context_length_exceeded"))
assert compact.is_overflow(Err("Error code: 400", body={"error": {"message": "This model's maximum context length is 8192 tokens"}}))
assert compact.is_overflow(Err("请求超出上下文长度限制"))
assert not compact.is_overflow(Err("rate limit", code="rate_limit_exceeded"))
print("ok: is_overflow")

t = supersede.Tracker()
t.snapshots, t.images = [3, 5, 9, 12], [6, 11]
t.splice(4, 8)  # [4,8) → 1 条：区间里的作废，后面的前移 3
assert t.snapshots == [3, 6, 9] and t.images == [8], (t.snapshots, t.images)
assert compact._drop_oldest([{"role": "system"}, call(1), res(1), {"role": "user", "content": "x"}]) == \
    [{"role": "system"}, {"role": "user", "content": "x"}]
assert compact._drop_oldest([{"role": "system"}, {"role": "user"}]) is None
print("ok: tracker splice + drop oldest")

# —— 二、模拟模型整轮 ——
@tool("fake_dump", "正在输出", "测试用", {"type": "object", "properties": {"n": {"type": "integer"}, "size": {"type": "integer"}}})
async def fake_dump(ctx, n: int = 0, size: int = 3000) -> ToolResult:
    return ToolResult(f"第{n}次输出：" + "日志" * (size // 2))

script: list = []
saw: list[dict] = []       # 对话请求
asked: list[dict] = []     # 摘要请求
summary_mode = {"kind": "ok"}
overflow_at: set[int] = set()

def chunk(text=None, tools=None, u=None):
    if text is None and tools is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tools))], usage=u)

async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    snap = json.loads(json.dumps(messages, ensure_ascii=False))
    if not stream:
        asked.append({"messages": snap, "tools": bool(tools), "tool_choice": kw.get("tool_choice"), "max_tokens": kw.get("max_tokens")})
        k = summary_mode["kind"]
        if k == "error":
            raise RuntimeError("upstream 502")
        text = {"ok": f"## 用户的请求与意图\n- 把服务跑起来（摘要{len(asked)}）\n## 下一步\n- 继续",
                "huge": "很长" * 200000, "cut": "## 用户的请求"}.get(k, "")
        return NS(choices=[NS(message=NS(content=text), finish_reason="length" if k == "cut" else "stop")],
                  usage=NS(prompt_tokens=10, completion_tokens=10))
    saw.append({"messages": snap, "tools": bool(tools)})
    if len(saw) in overflow_at:
        raise Err("Error code: 400", code="context_length_exceeded")
    step = script.pop(0) if script else "收尾"
    if isinstance(step, dict) and not tools:
        step = "收尾"
    prompt = compact.estimate(messages)
    async def gen():
        if isinstance(step, dict):
            yield chunk(tools=[NS(index=0, id=f"k{len(saw)}", function=NS(name="fake_dump", arguments=json.dumps(step)))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=prompt, completion_tokens=5))
    return gen()

llm.client.chat.completions.create = fake_create
load_builtin()
n = 0
ASK = "把服务跑起来，日志都看一遍"

async def run(steps, window=6000):
    global n
    n += 1
    settings.context_tokens = window
    script[:] = list(steps)
    saw.clear(); asked.clear()
    async with SessionLocal() as db:
        db.add(Conversation(id=f"c{n}", title="t")); await db.commit()
        evs = [e async for e in loop.run("sys", [{"role": "user", "content": ASK}], ToolContext(db=db, conversation_id=f"c{n}"))]
    done = evs[-1]
    assert isinstance(done, loop.Done)
    return evs, "".join(b.get("text", "") for b in done.blocks if b["type"] == "text")

def paired(msgs):
    """每条工具结果前面都有它的调用、每个调用都有结果（API 会拒绝拆散的）。"""
    open_ids = set()
    for m in msgs:
        if m["role"] == "assistant":
            assert not open_ids, "上一批调用还没答完"
            open_ids = {c["id"] for c in m.get("tool_calls") or []}
        elif m["role"] == "tool":
            assert m["tool_call_id"] in open_ids, m["tool_call_id"]
            open_ids.discard(m["tool_call_id"])
        else:
            assert not open_ids, "调用和结果之间插了别的"
    return True

def checkpoints(msgs):
    return [m for m in msgs if m["role"] == "user" and str(m["content"]).startswith(CHECKPOINT_PREAMBLE)]

def compact_steps(evs):
    return [e for e in evs if isinstance(e, loop.ToolStatus) and e.name == "compact_context"]

async def main():
    # ① 过线 → 检查点
    evs, text = await run([{"n": i} for i in range(12)])
    assert text == "收尾" and asked, "应该写过摘要"
    a = asked[0]
    assert a["messages"][-1]["content"] == INSTRUCTION and a["tools"] and a["tool_choice"] == "none"
    assert a["max_tokens"] == compact.SUMMARY_MAX_TOKENS
    assert a["messages"][0]["content"] == "sys" and a["messages"][1]["content"] == ASK, "重放的是原样前缀"
    assert paired(a["messages"][:-1])
    first = next(i for i, s in enumerate(saw) if checkpoints(s["messages"]))
    for s in saw[first:]:
        ms = s["messages"]
        assert ms[1]["content"] == ASK and paired(ms)
        assert len(checkpoints(ms)) == 1, "检查点不叠层"
        assert compact.estimate(ms) < settings.context_tokens, "压完不超窗口"
    assert SUMMARY_OPEN in checkpoints(saw[first]["messages"])[0]["content"]
    st = compact_steps(evs)
    assert st and st[0].state == "running" and st[1].state == "done" and "压成了摘要" in st[1].step["detail"]
    done = evs[-1]
    print(f"ok: checkpoint ({len(asked)} summaries, first at call {first + 1})")

    # ② 第二次过线：摘要请求里带着旧检查点（指令要求合并）
    assert len(asked) >= 2, len(asked)
    assert checkpoints(asked[1]["messages"]), "第二次摘要看得到旧检查点"
    assert f"摘要{len(asked)}" in checkpoints(saw[-1]["messages"])[0]["content"]
    print("ok: second checkpoint merges the first")

    # ③ 只剪就够：结果 10000 字（> 阈值）、窗口够大
    evs, text = await run([{"n": i, "size": 10000} for i in range(12)], window=80000)
    assert text == "收尾" and not asked, "剪就够了，不该写摘要"
    last = saw[-1]["messages"]
    tools_msgs = [m for m in last if m["role"] == "tool"]
    assert sum(MK in m["content"] for m in tools_msgs) >= 1
    assert all(MK not in m["content"] for m in tools_msgs[-3:]), "最近 3 批原样"
    assert any("精简了较早的长工具结果" in e.step.get("detail", "") for e in compact_steps(evs))
    print("ok: prune only")

    # ④ 摘要失败 / 截断 / 更长 → 不换，之后不再摘要，照常做完
    for kind in ("error", "cut", "huge"):
        summary_mode["kind"] = kind
        evs, text = await run([{"n": i} for i in range(12)])
        assert text == "收尾", kind
        assert len(asked) == 1, (kind, len(asked))  # 失败一次后本轮只剪不再摘要
        assert not any(checkpoints(s["messages"]) for s in saw), kind
        assert all(paired(s["messages"]) for s in saw)
    summary_mode["kind"] = "ok"
    print("ok: failed / truncated / inflated summary → keep original, no retry")

    # ⑤ 供应商报超长：强制压 → 重试成功（窗口设大，正常不会触发压缩）
    overflow_at.clear(); overflow_at.add(7)
    evs, text = await run([{"n": i} for i in range(8)], window=10 ** 6)
    assert text == "收尾" and len(asked) == 1
    assert saw[7]["messages"] == saw[6]["messages"] or len(saw[7]["messages"]) < len(saw[6]["messages"]) + 3
    assert checkpoints(saw[7]["messages"]), "重试的那次带检查点"
    assert paired(saw[7]["messages"])
    print("ok: overflow → forced compaction → retry")

    overflow_at.clear(); overflow_at.add(1)  # 第一步就超长：这一轮没有自己的消息可压 → 原错误
    try:
        await run([{"n": 0}], window=10 ** 6)
        raise AssertionError("应该抛出")
    except Err as e:
        assert e.code == "context_length_exceeded"
    overflow_at.clear(); overflow_at.update({5, 6})  # 压完重试还超长：不无限重试
    try:
        await run([{"n": i} for i in range(8)], window=10 ** 6)
        raise AssertionError("应该抛出")
    except Err:
        assert len(saw) == 6
    overflow_at.clear()
    print("ok: overflow without progress re-raises; no retry loop")

asyncio.run(main())
print("ALL OK")
