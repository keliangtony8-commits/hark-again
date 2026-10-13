# 冒烟：v2.43 E2E B16 “嘴上做完了、手上没做”（app/agent/claimed_action.py）。无迁移。
# 1) 规则：宣称删掉/记住/设好/发送/保存而本轮没有对应工具成功 → 命中；有对应工具 / 否定 / 疑问 / 将来 / 以前的事 → 不命中；
# 2) 一轮模拟模型（真机 h5b 原样）：第一步 0 工具回“删除了那条长期记忆” → 撤回 + 内部提示 → 模型调 forget → 记忆真没了，
#    交付的回复里没有那句假话；
# 1b) v2.45 B18：交付类工具（display_file 等）算“发给你了”；提示写明是系统检查、别回应它。
# 3) 第二次照样宣称：只拦一次，照常交付（总共 2 次调用）；普通回答不多花调用。
# 运行：python tests/smoke_claimed_action.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', NEXT_SPEAKER_CHECK="off")
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

# 1) 规则
from app.agent.claimed_action import claims, nudge, KINDS
CASES = [
    ("删除了那条长期记忆。", set(), "记忆"),                       # h5b 原话
    ("好的，已经帮你删掉了那条记忆，下次不会再提。", set(), "记忆"),
    ("好的，已经删掉了。", {"search_memory"}, "操作"),               # 只查过：不算
    ("好的，已经删掉了。", {"forget"}, None),
    ("我记住了！以后不放香菜。", set(), "记忆"),
    ("我记住了！以后不放香菜。", {"remember"}, None),
    ("记住了，以后不放香菜。", {"run_command"}, "记忆"),             # 命令改不了记忆
    ("提醒已经设好了，明天 9 点叫你。", set(), "提醒或定时任务"),
    ("提醒已经设好了，明天 9 点叫你。", {"schedule_task"}, None),
    ("已经取消了这个提醒。", set(), "提醒或定时任务"),
    ("邮件已经发送成功。", set(), "发送或提交"),
    ("邮件已经发送成功。", {"api_request"}, None),
    ("文件已经保存到 notes.md。", {"read_file"}, "文件"),
    ("文件已经保存到 notes.md。", {"write_file"}, None),
    ("我已经把 report.pdf 生成好了。", set(), "文件"),
    ("I've deleted that file.", set(), "文件"),
    ("已经删掉了。", {"delegate"}, None),                            # 子助手可能做了
    ("已经取消了这个任务。", {"run_command"}, None),
    ("这是今天的天气：晴，25 度。", set(), None),
    ("要不要我帮你删掉这条记忆？", set(), None),
    ("我没法删除这条记忆。", set(), None),
    ("上次已经删掉了。", set(), None),
    ("如果你想，我可以帮你删掉。", set(), None),
    ("删除失败了，文件被占用。", set(), None),
    ("I can't delete it.", set(), None),
    ("我来删掉它。", set(), None),
    ("好的，4 位，已记下电话。", {"ask_user"}, None),  # v2.44：表单“记住”勾选写了记忆
    ("记好了。", {"save_skill"}, None),
    ("记好了。", set(), "记忆"),
    ("已经删掉了。", {"ask_user"}, "操作"),
    ("刚才被打断了，a 装好了，我看看 b。", set(), None),  # 说的是上一轮
    ("刚才被打断了。已经删掉了那条记忆。", set(), "记忆"),  # 只放过讲过去的那一句
    ("已保存并发送：\n\n- `en.txt`：The early bird catches the worm.", {"write_file", "display_file"}, None),  # v2.45 B18 i1 原话
    ("截图已经发给你了。", {"browser_screenshot"}, None),
    ("已经发给你了。", {"write_file"}, "发送或提交"),  # 只写了文件、没交付：照样拦
]
bad = [(t, a, got and got[0].name, w) for t, a, w in CASES if ((got := claims(t, a)) and got[0].name) != w and (got or w)]
assert not bad, bad
k, phrase = claims("删除了那条长期记忆。", set())
n = nudge(k, phrase)
assert "删除了那条长期记忆" in n and "forget" in n and "如实" in n, n
assert "不是用户说的" in n and "你误会了" in n and "照样再说一遍" in n, n  # v2.45 B18：模型把提示当成用户在挑刺
print("rules ok")

# 2) 一轮模拟模型
from sqlalchemy import select
from app import llm
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Memory, Message
load_builtin()

seen, script = [], []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
ids = iter(range(10_000))
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append([dict(m) for m in messages])
    step = script.pop(0)
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"c{next(ids)}", function=NS(name=n, arguments=json.dumps(a)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create

async def seed(ask, memory=None):
    async with SessionLocal() as db:
        if memory:
            db.add(Memory(content=memory, category="food"))
        conv = Conversation(title="t"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks(ask)))
        await db.commit(); return conv.id
async def turn(cid):
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))
async def memories():
    async with SessionLocal() as db:
        return [m.content for m in (await db.scalars(select(Memory))).all()]
def text_of(reply):
    return "".join(b.get("text", "") for b in reply.blocks if b.get("type") == "text")

cid = asyncio.run(seed("把我不吃香菜那条记忆删了", memory="不吃香菜"))
script.extend(["删除了那条长期记忆。", [("forget", {"keyword": "香菜"})], "好了，“不吃香菜”这条已经删掉了。"])
n0 = len(seen)
reply = asyncio.run(turn(cid))
assert len(seen) - n0 == 3, len(seen) - n0
hint = seen[n0 + 1][-1]
assert hint["role"] == "user" and "并没有成功调用" in hint["content"] and "删除了那条长期记忆" in hint["content"], hint
assert seen[n0 + 1][-2] == {"role": "assistant", "content": "删除了那条长期记忆。"}
assert asyncio.run(memories()) == [], asyncio.run(memories())
body = text_of(reply)
assert "删除了那条长期记忆" not in body and "已经删掉了" in body, reply.blocks
assert [s["tool"] for s in reply.steps] == ["forget"], reply.steps
print("h5b → nudge → forget ok")

# 3) 还是嘴硬：只拦一次；普通回答零额外调用
cid = asyncio.run(seed("记住我不吃辣"))
script.extend(["记住了！", "记住了！"])
n0 = len(seen)
reply = asyncio.run(turn(cid))
assert len(seen) - n0 == 2 and "记住了" in text_of(reply), (len(seen) - n0, reply.blocks)
cid = asyncio.run(seed("今天天气怎么样"))
script.extend(["今天晴，25 度。"])
n0 = len(seen)
asyncio.run(turn(cid))
assert len(seen) - n0 == 1
assert not script
print("smoke_claimed_action OK")
