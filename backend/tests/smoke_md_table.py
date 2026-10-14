# 冒烟：v2.71 回复里 Markdown 表格列数对不齐 → 就地补齐（app/agent/md_table.py，经 reply_fix.py 串联）。无迁移。
# 1) 规则：数据行多格 → 合并进最后一列（中文“、”/英文“, ”）；每行都多同样列数 → 表头补空列；少格补空；
#    分隔行列数修正保留对齐；对齐的表格、代码块里的、转义竖线不动；只改坏行。
# 2) 一轮模拟模型（真机 r5 原样）：落库回复表格对齐、只调一次模型；对的表格不撤回。
# 运行：python tests/smoke_md_table.py
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


from app.agent.md_table import fix
R5 = ("**相册文件夹里有 2 组内容完全一样的重复照片：**\n\n| 组 | 文件 |\n|---|---|\n"
      "| 1 | `夜景.jpg` | `夜景 副本.jpg` |\n| 2 | `海边.jpg` | `海边(1).jpg` | `IMG_9001.jpg` |\n\n共 **5 个文件**涉及重复。")
out, ch = fix(R5)
assert "| 1 | `夜景.jpg`、`夜景 副本.jpg` |" in out, out
assert "| 2 | `海边.jpg`、`海边(1).jpg`、`IMG_9001.jpg` |" in out, out
assert "| 组 | 文件 |\n|---|---|" in out and len(ch) == 2 and out.endswith("共 **5 个文件**涉及重复。")
out, ch = fix("| 名称 | 大小 |\n| --- | :-: |\n| a.txt | 3 KB | 昨天 |\n| b.txt | 5 KB | 今天 |")
assert out.split("\n")[0] == "| 名称 | 大小 |  |" and out.split("\n")[1] == "| --- | :-: | --- |", out
assert "| a.txt | 3 KB | 昨天 |" in out
out, ch = fix("| a | b | c |\n|---|---|---|\n| 1 | 2 |\n| 4 | 5 | 6 |")
assert "| 1 | 2 |  |" in out and "| 4 | 5 | 6 |" in out and len(ch) == 1, out
out, _ = fix("| Group | Files |\n|---|---|\n| 1 | a.jpg | b.jpg |\n| 2 | c.jpg |")
assert "| 1 | a.jpg, b.jpg |" in out, out
out, _ = fix("| a | b | c |\n|:--|--:|\n| 1 | 2 | 3 |")
assert out.split("\n")[1] == "| :-- | --: | --- |", out
for ok in ["| a | b |\n|---|---|\n| 1 | 2 |",
           "```\n| a | b |\n|---|---|\n| 1 | 2 | 3 |\n```",
           "| 命令 | 说明 |\n|---|---|\n| `a \\| b` | 管道 |",
           "a | b | c\n1 | 2",
           "价格 3-5 元，选 A|B 都行", ""]:
    o, c = fix(ok)
    assert o == ok and not c, (ok, o)
print("md_table rules ok")

# 2) 一轮模拟模型
from app import llm
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message
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
            yield chunk(tool=[NS(index=i, id=f"c{next(ids)}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create

async def seed(ask):
    async with SessionLocal() as db:
        conv = Conversation(title="t"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks(ask)))
        await db.commit(); return conv.id
async def turn(cid):
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))
def text_of(reply):
    return "".join(b.get("text", "") for b in reply.blocks if b.get("type") == "text")

async def turn_ev(cid, events):
    async with SessionLocal() as db:
        async def emit(ev):
            events.append(ev)
        return await run_turn(db, await db.get(Conversation, cid), emit=emit)
async def stored(cid):
    async with SessionLocal() as db:
        from sqlalchemy import select
        rows = (await db.execute(select(Message).where(Message.conversation_id == cid, Message.role == "assistant"))).scalars().all()
        return "".join(b.get("text", "") for b in rows[-1].blocks if b.get("type") == "text")

cid = asyncio.run(seed("相册里有没有重复照片？先别删"))
script.extend([R5])
n0, events = len(seen), []
reply = asyncio.run(turn_ev(cid, events))
assert len(seen) - n0 == 1, len(seen) - n0
body = asyncio.run(stored(cid))
assert "`海边.jpg`、`海边(1).jpg`、`IMG_9001.jpg`" in body, body
assert "block.update" in [e.get("type") for e in events]
print("r5 table fixed in place ok")

cid = asyncio.run(seed("列一下"))
script.extend(["| a | b |\n|---|---|\n| 1 | 2 |"])
events = []; n0 = len(seen)
reply = asyncio.run(turn_ev(cid, events))
assert len(seen) - n0 == 1 and "block.update" not in [e.get("type") for e in events]
assert not script
print("smoke_md_table OK")
