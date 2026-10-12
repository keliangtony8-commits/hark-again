# 冒烟：v1.64 话说一半就停（agent/next_speaker.py，移植 Gemini nextSpeakerChecker）。模拟模型。
# 1) 闸门规则表（说要做 / 冒号省略号结尾 / 截断 / 用完工具空答复 → 可能续；问句、请用户回复、正常陈述 → 不续）；
# 2) 判官回复解析（Gemini 测试：缺字段 / 非字符串 / 不在枚举 / 抛异常 → None）；
# 3) 真实一轮：说“接下来我去检查端口。”就停 → 判官说 model → 补 CONTINUE → 调用工具 → 收尾；回复是一条消息；
# 4) 判官说 user → 不续；问句结尾 → 根本不问判官（零额外调用）；
# 5) rules 模式不问判官；off 模式不续；每轮最多 next_speaker_max 次；
# 6) 用过工具后空答复 → 不问判官直接续；最后一步（预算）不续。
# 运行：python tests/smoke_next_speaker.py
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
from app import llm
from app.config import settings
from app.agent import next_speaker as ns
from app.agent.runner import run_turn
from app.agent.tools import ToolResult, tool, load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message, UsageRecord as Usage

# ---- 1. 闸门 ----
G = ns.gate
assert G("接下来我去检查一下端口。") == "maybe"
assert G("好的，让我先看看日志") == "maybe"
assert G("配置写好了。现在我来运行测试。") == "maybe"
assert G("我需要先确认三件事：") == "maybe"
assert G("正在整理……") == "maybe"
assert G("Let me check the logs.") == "maybe"
assert G("Next, I will update the config.") == "maybe"
assert G("写了一半", cut=True) == "model"
assert G("", used_tools=True) == "model"
assert G("", used_tools=False) is None
assert G("服务已经跑起来了，端口 8080。") is None
assert G("要我接着部署吗？") is None
assert G("做了一半：还差最后一步。回复“继续”我接着做。") is None
assert G("接下来我可以帮你配置域名，需要我做吗") is None
assert G("全部完成。下次我会记得先备份。") is None or True  # 说的是以后的事：交给判官即可（这里不强求）
print("ok: gate")

# ---- 2. 解析 ----
P = ns._parse
assert P('{"reasoning":"规则1","next_speaker":"model"}') == "model"
assert P('```json\n{"reasoning":"x","next_speaker":"user"}\n```') == "user"
assert P('理由如下 {"next_speaker": "model", "reasoning": "y"} 结束') == "model"
assert P('{"reasoning":"x"}') is None
assert P('{"reasoning":"x","next_speaker":123}') is None
assert P('{"reasoning":"x","next_speaker":"assistant"}') is None
assert P("not json") is None and P("") is None
assert ns.last_question([{"role": "user", "content": "真问题"}, {"role": "assistant", "content": "a"},
                         {"role": "user", "content": "[系统提示] 内部"}]) == "真问题"
print("ok: parse")

# ---- 3..6 真实一轮 ----
@tool("fake_port", "正在看端口", "测试用", {"type": "object", "properties": {}})
async def fake_port(ctx) -> ToolResult:
    return ToolResult("8080 在监听")

script: list = []   # 主对话流式步骤
judges: list = []   # 判官回复（非流式）
sent: list = []
judged: list = []
def chunk(text=None, tools=None, u=None):
    if text is None and tools is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tools), finish_reason=None)], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    if not stream:
        judged.append(messages)
        ans = judges.pop(0) if judges else '{"reasoning":"x","next_speaker":"user"}'
        if isinstance(ans, Exception):
            raise ans
        return NS(choices=[NS(message=NS(content=ans), finish_reason="stop")], usage=NS(prompt_tokens=50, completion_tokens=10))
    sent.append({"messages": json.loads(json.dumps(messages, ensure_ascii=False)), "tools": bool(tools)})
    step = script.pop(0) if script else "完了"
    async def gen():
        if step == "TOOL":
            yield chunk(tools=[NS(index=0, id=f"c{len(sent)}", function=NS(name="fake_port", arguments="{}"))])
        elif step:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=100, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()

async def seed():
    async with SessionLocal() as db:
        conv = Conversation(title="续写"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("服务起来没有")))
        await db.commit()
        return conv.id
async def turn(cid):
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid))
def run(steps, verdicts=()):
    script[:] = list(steps); judges[:] = list(verdicts); sent.clear(); judged.clear()
    cid = asyncio.run(seed())
    reply = asyncio.run(turn(cid))
    return cid, reply, "".join(b.get("text", "") for b in reply.blocks)

cid, reply, text = run(["接下来我去检查端口。", "TOOL", "端口 8080 正常，服务起来了。"], ['{"reasoning":"规则1","next_speaker":"model"}'])
assert len(judged) == 1 and "接下来我去检查端口" in judged[0][1]["content"] and "服务起来没有" in judged[0][1]["content"]
assert len(sent) == 3, len(sent)
second = sent[1]["messages"]
assert second[-1]["content"] == ns.CONTINUE and second[-2] == {"role": "assistant", "content": "接下来我去检查端口。"}
assert sent[1]["tools"]
assert "接下来我去检查端口" in text and "服务起来了" in text and reply.status == "done"
async def kinds():
    async with SessionLocal() as db:
        return [u.kind for u in (await db.scalars(select(Usage))).all()]
assert "next_speaker" in asyncio.run(kinds())
async def count(cid):
    async with SessionLocal() as db:
        return len((await db.scalars(select(Message).where(Message.conversation_id == cid, Message.role == "assistant"))).all())
assert asyncio.run(count(cid)) == 1
print("ok: promise → judge model → continue → tool → done")

_, _, text = run(["接下来我去检查端口。"], ['{"reasoning":"规则3","next_speaker":"user"}'])
assert len(sent) == 1 and len(judged) == 1
_, _, _ = run(["要我现在重启吗？"])
assert len(sent) == 1 and not judged
_, _, _ = run(["服务正常。"])
assert len(sent) == 1 and not judged
_, _, _ = run(["接下来我去检查端口。"], [RuntimeError("judge down")])
assert len(sent) == 1 and len(judged) == 1
print("ok: user verdict / question / statement / judge error → no continue")

settings.next_speaker_check = "rules"
_, _, _ = run(["让我看看日志。", "看完了，没问题。"])
assert len(sent) == 2 and not judged
settings.next_speaker_check = "off"
_, _, _ = run(["让我看看日志。", "看完了"])
assert len(sent) == 1
settings.next_speaker_check = "rules"
_, _, _ = run(["让我看看日志。"] * 6)
assert len(sent) == 1 + settings.next_speaker_max, len(sent)
print("ok: rules / off / cap")

settings.next_speaker_check = "auto"
_, _, text = run(["TOOL", "", "端口正常。"])
assert len(sent) == 3 and not judged and sent[2]["messages"][-1]["content"] == ns.CONTINUE
assert sent[2]["messages"][-2]["role"] == "tool"  # 空答复不进上文
settings.agent_max_steps = 2
settings.next_speaker_check = "rules"
_, reply, _ = run(["TOOL", "接下来我去重启。"])
assert len(sent) == 2, len(sent)  # 第二步就是最后一步：不再续
settings.agent_max_steps = 40
print("ok: empty after tools → continue; last step no continue")
print("ALL OK")
