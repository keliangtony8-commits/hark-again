# 冒烟：v1.58 连续写错工具参数（tool_args.Streak）。模拟模型。
# 1) signature 规则：必填在前、类型/enum/array、说明截断、无参数；
# 2) Streak 规则：同一工具第 3 次起附签名，通过一次清零；不存在的工具第 3 次列出可用名；不分工具第 6 次 stopped；
# 3) 错两次再写对 → 没有加重提醒，工具执行，done；
# 4) 三种不同写错方式（缺必填 / 类型错 / 坏 JSON）→ 第 3 次结果带完整签名；之后写对 → done；
# 5) 连续 6 次写错 → 停下 looped + STOP_NOTE；同一批里后面的调用 SKIPPED_BAD 不执行；下一轮历史有 <turn_looped>；
# 6) 连调 3 次不存在的工具 → 列出可用工具名。
# 运行：python tests/smoke_bad_args.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', LLM_MAX_RETRIES="0")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import llm
from app.agent import loop, tool_args as ta
from app.agent.runner import run_turn
from app.agent.tools import ToolResult, tool, load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message

SCHEMA = {"type": "object", "properties": {
    "mode": {"type": "string", "enum": ["w", "a"], "description": "写入方式"},
    "path": {"type": "string", "description": "相对工作区的路径" + "很长" * 50},
    "content": {"type": "string", "description": "完整内容"},
    "tags": {"type": "array", "items": {"type": "string"}}}, "required": ["path", "content"]}
ran: list = []

@tool("fake_write", "正在写", "测试用", SCHEMA)
async def fake_write(ctx, path: str, content: str, mode: str = "w", tags: list | None = None) -> ToolResult:
    ran.append(path)
    return ToolResult(f"写好了 {path}")

# ---- 1. signature ----
sig = ta.signature("fake_write", SCHEMA)
lines = sig.splitlines()
assert lines[0] == "fake_write 的参数：", sig
assert lines[1].startswith("- path（string，必填）：相对工作区的路径") and lines[1].endswith("…"), lines[1]
assert lines[2] == "- content（string，必填）：完整内容", lines[2]
assert lines[3] == '- mode（"w"|"a"，可选）：写入方式', lines[3]
assert lines[4] == "- tags（array<string>，可选）", lines[4]
assert ta.signature("x", {"type": "object", "properties": {}}) == "x 不需要参数，传 {} 即可。"
many = {"type": "object", "properties": {f"p{i}": {"type": ["integer", "null"]} for i in range(20)}}
ms = ta.signature("m", many)
assert "- p0（integer|null，可选）" in ms and f"还有 {20 - ta.SIG_PARAMS_MAX} 个可选参数" in ms, ms
assert '"x"|"y"' in ta.signature("o", {"properties": {"k": {"oneOf": [{"const": "x"}, {"const": "y"}]}}}).replace(" 或 ", "|")
print("ok: signature")

# ---- 2. Streak ----
s = ta.Streak()
assert s.fail("a", SCHEMA) == "" and s.fail("a", SCHEMA) == ""
h = s.fail("a", SCHEMA)
assert "连续第 3 次" in h and "- path（string，必填）" in h and f"连续写错 {ta.STOP_AT} 次" in h, h
s.ok("a"); assert s.total == 0 and s.fail("a", SCHEMA) == ""
s = ta.Streak()
s.fail("a", SCHEMA); s.fail("b", SCHEMA)
assert s.fail("a", SCHEMA) == ""  # a 只错了两次（中间夹着 b），不附签名
s = ta.Streak()
for _ in range(2): assert s.fail("nope", names=["x", "y"]) == ""
u = s.fail("nope", names=["y", "x"])
assert "连续 3 次调用了不存在的工具" in u and "x、y" in u, u
s = ta.Streak()
for i in range(ta.STOP_AT - 1): s.fail(f"t{i}", SCHEMA)
assert not s.stopped
assert s.fail("t", SCHEMA) == "" and s.stopped  # 停的那一次不再附签名（loop 直接停）
print("ok: streak")

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
        if isinstance(step, list):  # [(name, raw_args), …]
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
        conv = Conversation(title="写错参数"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("写个文件")))
        await db.commit()
        return conv.id
async def say(cid, text):
    async with SessionLocal() as db:
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks(text))); await db.commit()
async def turn(cid):
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid))
def run(steps, cid=None):
    script[:] = list(steps); sent.clear(); ran.clear()
    cid = cid or asyncio.run(seed())
    return cid, asyncio.run(turn(cid))
def results(msgs):
    return [m["content"] for m in msgs if m["role"] == "tool"]
def text(reply):
    return "".join(b.get("text", "") for b in reply.blocks)

GOOD = json.dumps({"path": "a.txt", "content": "hi"})
MISSING = json.dumps({"path": "a.txt"})
WRONG = json.dumps({"path": "a.txt", "content": {"x": 1}})
BROKEN = '{"path": "a.txt", "content": "hi'

# ---- 3. 错两次再写对 ----
cid, reply = run([[("fake_write", MISSING)], [("fake_write", WRONG)], [("fake_write", GOOD)], "写好了"])
rs = results(sent[-1])
assert len(rs) == 3 and all("连续第" not in x for x in rs), rs
assert ran == ["a.txt"] and reply.status == "done", (ran, reply.status)
print("ok: two misses no hint")

# ---- 4. 三种写错方式 → 第 3 次附签名 ----
cid, reply = run([[("fake_write", MISSING)], [("fake_write", WRONG)], [("fake_write", BROKEN)], [("fake_write", GOOD)], "好了"])
rs = results(sent[-1])
assert "连续第" not in rs[0] and "连续第" not in rs[1], rs
assert "连续第 3 次没把 fake_write 的参数写对" in rs[2] and "- content（string，必填）" in rs[2], rs[2]
assert rs[3] == "写好了 a.txt" and reply.status == "done"
print("ok: third miss carries signature")

# ---- 5. 连续 6 次 → 停下；同批后面的不执行 ----
bad = [[("fake_write", MISSING)]] * (ta.STOP_AT - 1) + [[("fake_write", WRONG), ("fake_write", GOOD)]] + ["不该走到这"]
cid, reply = run(bad)
assert reply.status == "looped", reply.status
assert text(reply).endswith(ta.STOP_NOTE), text(reply)
assert len(sent) == ta.STOP_AT and ran == [], (len(sent), ran)
assert script == ["不该走到这"]
asyncio.run(say(cid, "继续"))
cid, again = run(["好的，我换个办法"], cid)
assert any(m["role"] == "assistant" and isinstance(m.get("content"), str) and "<turn_looped>" in m["content"] for m in sent[0])
assert again.status == "done"
# 被跳过的那条在落库的工具轨迹里是 SKIPPED_BAD（下一轮回放可见）
tools = [m for m in sent[0] if m["role"] == "tool"]
assert any(m["content"] == loop.SKIPPED_BAD for m in tools), [m["content"][:30] for m in tools]
print("ok: six misses stop + skipped + looped note")

# ---- 6. 不存在的工具 ----
cid, reply = run([[("fake_wirte", GOOD)], [("nope_tool", "{}")], [("zzz", "{}")], "算了"])
rs = results(sent[-1])
assert "是不是想用" in rs[0] and "fake_write" in rs[0], rs[0]
assert "连续 3 次调用了不存在的工具" in rs[2] and "fake_write" in rs[2], rs[2]
assert reply.status == "done"
print("ok: unknown tools listed")
print("ALL OK")
