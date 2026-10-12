# 冒烟：v1.56 一轮怎么结束的落进消息 status（loop.Done.ended → runner），客户端据此给“继续”。模拟模型。
# 1) 正常说完 → done（to_wire 不带 status）；
# 2) 步数预算用完收尾 → wrapped；下一轮（用户回“继续”）历史里有 <turn_wrapped> 说明，模型照常有工具；
# 3) 原地打转第二次被叫停 → looped；下一轮历史里有 <turn_looped>；
# 4) 文字复读被叫停 → looped；预算用完那一步同时复读 → 仍算 looped（先判打转）；
# 5) 只有一步预算（第一步就是最后一步，不交代）→ done；
# 6) history_note 规则单测。
# 运行：python tests/smoke_reply_end.py
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

from sqlalchemy import select
from app import llm, turn_journal as tj
from app.config import settings
from app.agent import loop, loop_guard
from app.agent.loop_guard import TOOL_CALL_LOOP_THRESHOLD as T
from app.agent.runner import run_turn
from app.agent.tools import ToolResult, tool, load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message

@tool("fake_probe", "正在探测", "测试用", {"type": "object", "properties": {"x": {"type": "integer"}}})
async def fake_probe(ctx, x: int = 0) -> ToolResult:
    return ToolResult("端口还没起来")

script: list = []
sent: list = []
def chunk(text=None, tools=None, u=None):
    if text is None and tools is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tools))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    sent.append({"messages": json.loads(json.dumps(messages, ensure_ascii=False)), "tools": bool(tools)})
    step = script.pop(0) if script else "收尾"
    if isinstance(step, list) and not tools:
        step = "做了一半：还差最后一步。回复“继续”我接着做。"
    async def gen():
        if isinstance(step, list):
            yield chunk(tools=[NS(index=i, id=f"c{len(sent)}_{i}", function=NS(name="fake_probe", arguments=json.dumps(a)))
                               for i, a in enumerate(step)])
        elif isinstance(step, tuple):
            for piece in step:
                yield chunk(piece)
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=100, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()

async def seed(text="把服务跑起来"):
    async with SessionLocal() as db:
        conv = Conversation(title="结束方式"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks(text)))
        await db.commit()
        return conv.id
async def say(cid, text):
    async with SessionLocal() as db:
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks(text))); await db.commit()
async def turn(cid):
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid))
async def stored(cid):
    async with SessionLocal() as db:
        rows = (await db.scalars(select(Message).where(Message.conversation_id == cid, Message.role == "assistant")
                                 .order_by(Message.created_at))).all()
        return [(m.status, m.to_wire()) for m in rows]
def run(steps, cid=None):
    script[:] = list(steps); sent.clear()
    cid = cid or asyncio.run(seed())
    reply = asyncio.run(turn(cid))
    return cid, reply

# ---- 规则 ----
assert loop.ENDINGS == ("done", "wrapped", "looped")
assert loop.Done([]).ended == "done"  # 子助手等老调用方不受影响
w = tj.history_note("wrapped", [])
assert "<turn_wrapped>" in w and "接着做" in w and "别从头重来" in w, w
l = tj.history_note("looped", [{"state": "done", "title": "x"}])
assert "<turn_looped>" in l and "换个做法" in l, l
assert tj.history_note("done", []) == ""
print("ok: rules")

# ---- 1. 正常 ----
cid, reply = run([[{"x": 1}], "跑起来了"])
assert reply.status == "done" and "status" not in reply.to_wire(), reply.to_wire()
print("ok: done")

# ---- 2. 预算用完 → wrapped，“继续”接着做 ----
settings.agent_max_steps = 3
cid, reply = run([[{"x": i}] for i in range(10)])
assert reply.status == "wrapped" and reply.to_wire()["status"] == "wrapped", reply.to_wire()
assert sent[-1]["messages"][-1]["content"] == loop.WRAP_UP and not sent[-1]["tools"]
assert "继续" in "".join(b.get("text", "") for b in reply.blocks)
assert [s for s, _ in asyncio.run(stored(cid))] == ["wrapped"]
settings.agent_max_steps = 40
asyncio.run(say(cid, "继续"))
_, again = run([[{"x": 7}], "全部做完了"], cid)
first = sent[0]
asst = [m for m in first["messages"] if m["role"] == "assistant" and isinstance(m.get("content"), str) and "<turn_wrapped>" in m["content"]]
assert asst, [m.get("content") for m in first["messages"]]
assert first["tools"] and first["messages"][-1]["content"] == "继续"
assert again.status == "done"
assert [s for s, _ in asyncio.run(stored(cid))] == ["wrapped", "done"]
print("ok: wrapped → 继续 → history note → done")

# ---- 3. 工具调用打转 → looped ----
cid, reply = run([[{"x": 1}]] * 10)
assert reply.status == "looped", reply.status
assert "".join(b.get("text", "") for b in reply.blocks).endswith(loop_guard.STOP_NOTE)
asyncio.run(say(cid, "继续"))
_, again = run(["换了个办法，好了"], cid)
assert any("<turn_looped>" in (m.get("content") or "") for m in sent[0]["messages"] if m["role"] == "assistant")
assert again.status == "done"
print("ok: tool loop → looped → history note")

# ---- 4. 文字复读 → looped；预算末步复读也算 looped ----
chant = tuple(["我再检查一下。"] * 60)
_, reply = run([chant, chant])
assert reply.status == "looped"
settings.agent_max_steps = 2
_, reply = run([[{"x": 1}], chant])
assert reply.status == "looped", reply.status
print("ok: chant → looped (beats wrapped)")

# ---- 5. 一步预算：第一步就是最后一步，不交代 → done ----
settings.agent_max_steps = 1
_, reply = run([[{"x": 1}]])
assert reply.status == "done" and len(sent) == 1 and not sent[0]["tools"]
settings.agent_max_steps = 40
print("ok: single-step budget is done")
print("ALL OK")
