# 冒烟：v1.65 旧的大块工具结果遮盖（agent/tool_mask.py，移植自 Gemini CLI toolOutputMaskingService）。
# 1) 移植的单测（toolOutputMaskingService.test.ts，阈值按原值 50k / 30k 传入）：低于保护线不动；保护最新一批，
#    超出 50k 保护线且可遮总量 > 30k 才遮；很多小块跨线后全部归入可遮（6 条）；shell 与普通工具的预览不同；
#    已遮过的跳过且不计入总量；遮了更长就不遮；豁免工具永不遮。
# 2) 我们的修改：start 之前（历史）不碰；结果里已有落盘说明 → 沿用原文件、不再存；存不下 → 不遮；
#    浏览器结果不遮；run_command 保留第一行退出码；单行过长按字符截；不改原 dict；关闭开关。
# 3) 模拟模型：一轮 6 次大输出工具调用，后几次调模型时最早的结果已换成预览 + .spill 路径，文件里是全文；
#    最新一批始终完整；已遮的条目在后续调用中逐字不变（提示缓存前缀稳定）。
# 运行：python tests/smoke_tool_mask.py
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
from app.agent import loop, tool_mask
from app.agent.tool_mask import TAG
from app.agent.tools import ToolContext, ToolResult, load_builtin, tool
from app.db import SessionLocal
from app.models import Conversation

WS = "wsmask"
G = dict(protect=50000, minimum=30000)  # Gemini 默认值


def batch(i, name, content):
    cid = f"c{i}"
    return [{"role": "assistant", "content": None, "tool_calls": [
        {"id": cid, "type": "function", "function": {"name": name, "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": cid, "content": content}]


def hist(*items):
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "做事"}]
    for i, (name, content) in enumerate(items):
        msgs += batch(i, name, content)
    return msgs


def tools_of(msgs):
    return [m["content"] for m in msgs if m["role"] == "tool"]


def tok(n, ch="A"):  # approx_tokens = UTF-8 字节 / 4
    return ch * (n * 4)

# ---- 1. 移植的单测 ----
# 低于保护线：不动
msgs = hist(("t1", tok(20000)), ("t2", tok(20000)), ("t3", tok(5000)))
before = tools_of(msgs)
assert tool_mask.mask(msgs, WS, **G).masked == 0 and tools_of(msgs) == before

# 保护最新一批；60k + 20k + 10k(最新)：t2 累计 20k 受保护，t1 跨线可遮，可遮 60k > 30k
msgs = hist(("t1", tok(60000)), ("t2", tok(20000, "B")), ("t3", tok(10000, "C")))
res = tool_mask.mask(msgs, WS, **G)
t = tools_of(msgs)
assert res.masked == 1 and res.saved > 50000, res
assert t[0].startswith(f"<{TAG}>") and t[1] == tok(20000, "B") and t[2] == tok(10000, "C")
path = t[0].split("完整内容在 ")[1].split("，")[0]
assert path.startswith(".spill/") and "masked-t1" in path
assert (project_dir(WS) / path).read_text(encoding="utf-8") == tok(60000), "全文落盘"
print("ok: protect latest + boundary")

# 很多小块：12 批每批 10k，最新一批跳过；10..6 累计到 50k 不超线 → 受保护，5..0 共 6 条可遮
msgs = hist(*[(f"tool{i}", tok(10000)) for i in range(12)])
res = tool_mask.mask(msgs, WS, **G)
t = tools_of(msgs)
assert res.masked == 6 and res.saved > 0, res
assert all(x.startswith(f"<{TAG}>") for x in t[:6]) and all(TAG not in x for x in t[6:])
print("ok: global aggregation")

# 预览：shell 留第一行状态 + 首尾 10 行；普通工具首尾 250 字
lines = "\n".join(f"line {i} " + "x" * 200 for i in range(50))
msgs = hist(("run_command", "退出码 1\n" + lines), ("web_fetch", "H" * 300 + "M" * 200000 + "T" * 300),
            ("t3", tok(40000)), ("latest", "x"))
res = tool_mask.mask(msgs, WS, protect=0, minimum=1)
sh, gen = tools_of(msgs)[:2]
assert sh.startswith(f"<{TAG}>\n退出码 1\n"), sh[:80]
assert "line 0 " in sh and "line 49 " in sh and "line 25 " not in sh
assert len(sh) < 3000, len(sh)  # 行太长：再按字符截
inner = gen.split(f"<{TAG}>\n")[1]
assert inner.startswith("H" * 250) and "（截断）" in inner and "T" * 250 in inner and "M" * 300 not in inner
print("ok: previews")

# 已遮过的跳过、不计入：只剩 20k 可遮 < 30k → 不动
masked = tool_mask.snippet("预览", ".spill/x.txt", 999)
msgs = hist(("t1", masked), ("t2", tok(20000)), ("t3", tok(50000)), ("latest", "x"))
before = tools_of(msgs)
assert tool_mask.mask(msgs, WS, **G).masked == 0 and tools_of(msgs) == before

# 遮了更长：不遮，也不白落盘
n_before = len(list((project_dir(WS) / ".spill").iterdir()))
msgs = hist(*[(f"s{i}", "短" * 30) for i in range(40)])
assert tool_mask.mask(msgs, WS, protect=0, minimum=1).masked == 0
assert len(list((project_dir(WS) / ".spill").iterdir())) == n_before, "没省就不存文件"

# 豁免工具：再深也不遮
msgs = hist(("use_skill", tok(60000)), ("ask_user", tok(60000)), ("update_plan", tok(1000)), ("delegate", tok(60000)),
            ("browser_open", tok(60000)), ("t", tok(10)), ("latest", "x"))
res = tool_mask.mask(msgs, WS, protect=0, minimum=1)
assert all(TAG not in x for x in tools_of(msgs)[:5]), [x[:40] for x in tools_of(msgs)]
print("ok: skip masked / no gain / exempt")

# ---- 2. 我们的修改 ----
# start 之前不碰
msgs = hist(("old", tok(60000)), ("new", tok(60000)), ("latest", "x"))
res = tool_mask.mask(msgs, WS, start=4, protect=0, minimum=1)  # 下标 0..3 = system/user/第一批
t = tools_of(msgs)
assert TAG not in t[0] and TAG in t[1] and res.masked == 1
# 已有落盘说明 → 沿用原文件，不再存
prior = spill.save(WS, "run_command", "完整全文" * 10000)
content = "退出码 0\n" + "头" * 6000 + spill.notice(5000, prior, 40000) + "尾" * 6000
n_before = len(list((project_dir(WS) / ".spill").iterdir()))
msgs = hist(("run_command", content), ("latest", "x"))
assert tool_mask.mask(msgs, WS, protect=0, minimum=1).masked == 1
t = tools_of(msgs)[0]
assert f"完整内容在 {prior}" in t and "全文 40000 字符" in t, t[-200:]
assert len(list((project_dir(WS) / ".spill").iterdir())) == n_before, "沿用原文件"
# 存不下 → 不遮
real = spill.save
def boom(*a, **k): raise OSError("disk full")
spill.save = boom
msgs = hist(("t1", tok(60000)), ("latest", "x"))
assert tool_mask.mask(msgs, WS, protect=0, minimum=1).masked == 0 and tools_of(msgs)[0] == tok(60000)
spill.save = real
# 不改原 dict
msgs = hist(("t1", tok(60000)), ("latest", "x"))
orig = msgs[3]
tool_mask.mask(msgs, WS, protect=0, minimum=1)
assert orig["content"] == tok(60000) and msgs[3] is not orig
# 没有工作区 → 不动；开关
msgs = hist(("t1", tok(60000)), ("latest", "x"))
assert tool_mask.mask(msgs, None, protect=0, minimum=1).masked == 0
assert tool_mask.enabled()
settings.tool_mask_min_tokens = 0
assert not tool_mask.enabled()
settings.tool_mask_min_tokens = 12000
# 默认阈值（24k + 12k）：小任务（几千 token 的输出）完全不动
msgs = hist(*[(f"t{i}", tok(3000)) for i in range(8)])
assert tool_mask.mask(msgs, WS).masked == 0
print("ok: our rules")

# ---- 3. 模拟模型 ----
@tool("big_dump", "正在导出", "导出一大段", {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]})
async def big_dump(ctx, n):
    return ToolResult(f"第 {n} 份\n" + (chr(0x4e00 + n) * 15000))  # 15000 个汉字 ≈ 11k token（不超 tool_result_max 16000）

script: list = []
model_saw: list[list] = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    model_saw.append(json.loads(json.dumps(messages, ensure_ascii=False)))
    step = script.pop(0)
    async def gen():
        if isinstance(step, tuple):
            name, args = step
            yield chunk(tool=[NS(index=0, id=f"k{len(script)}", function=NS(name=name, arguments=json.dumps(args)))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()


async def main():
    script.extend([("big_dump", {"n": i}) for i in range(6)] + ["导完了"])
    history = [{"role": "user", "content": "导出六份"}]
    async with SessionLocal() as db:
        db.add(Conversation(id="m1", title="t")); await db.commit()
        ctx = ToolContext(db=db, conversation_id="m1")
        evs = [e async for e in loop.run("sys", history, ctx)]
        ws = ctx.workspace
    assert len(model_saw) == 7
    last = [m["content"] for m in model_saw[-1] if m["role"] == "tool"]
    assert len(last) == 6
    assert TAG not in last[-1] and chr(0x4e00 + 5) * 15000 in last[-1], "最新一批完整"
    masked = [i for i, c in enumerate(last) if TAG in c]
    assert masked and masked == list(range(len(masked))), masked  # 从最旧开始遮
    assert masked == [0, 1], masked  # 第 5 次调模型时 0、1 成批遮；第 6 次只多出 1 份 11k < 12k 起批线 → 不动
    p = last[0].split("完整内容在 ")[1].split("，")[0]
    assert (project_dir(ws) / p).read_text(encoding="utf-8") == "第 0 份\n" + chr(0x4e00) * 15000
    assert "第 0 份" in last[0]  # 预览留开头
    # 遮过的条目在之后每次调用里逐字不变（缓存前缀稳定）
    first_seen = None
    for saw in model_saw:
        t0 = [m["content"] for m in saw if m["role"] == "tool"]
        if t0 and TAG in t0[0]:
            if first_seen is None:
                first_seen = t0[0]
            assert t0[0] == first_seen
    assert first_seen is not None
    total_last = sum(len(m.get("content") or "") for m in model_saw[-1])
    assert total_last < 6 * 15000 * 0.75, total_last
    assert history == [{"role": "user", "content": "导出六份"}]
    print("ok: turn masks oldest outputs, stable once masked")

asyncio.run(main())
print("ALL OK")
