# 冒烟：v2.69 E2E B36 “用户要文件回来、改好了却没交付”（app/agent/owed_delivery.py）。无迁移。
# 1) 规则：要文件（发我 / 发给我 / 发回来 / send it back）+ 说的是文件或有附件 + 这一轮动过文件 + 没交付 → 命中；
#    交付过 / 只读了文件总结 / 说先别发 / 建了定时任务 / 如实说失败 / 没要文件 → 不命中；
# 2) 一轮模拟模型（真机 r8 原样）：write_file 后回“已修复…如果你要我也可以发你” → 撤回 + 内部提示 →
#    display_file → 交付的回复里没有那句“如果你要”；
# 3) 第二次照样不交：只拦一次（总共 3 次调用）；普通问答零额外调用。
# 运行：python tests/smoke_owed_delivery.py
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
from app.agent.owed_delivery import owed, nudge
R8Q = "这个txt我手机上打开全是乱码，帮我弄成正常的再发我，顺便告诉我考试是什么时候在哪。"
R8A = "已修复，这条通知是 GBK 编码的 txt。如果你要，我也可以另存成 UTF-8 版本发你。"
CASES = [
    (R8Q, R8A, {"save_attachment", "run_command"}, True),              # 真机 r8
    (R8Q, R8A, {"save_attachment", "run_command", "display_file"}, False),
    ("把这张图转成黑白的发我。", "转好了。", {"save_attachment", "run_command"}, True),
    ("把 订单.json 转成 Excel 表格发我", "已生成 订单.xlsx。", {"read_file", "run_command"}, True),
    ("把 订单.json 转成 Excel 表格发我", "已生成 订单.xlsx。", {"read_file", "run_command", "display_file"}, False),
    ("这个文件讲了啥，总结一下发我", "主要讲了三点……", {"save_attachment", "read_file"}, False),  # 只读：聊天里说就行
    ("改好这个表格，先别发我，我看看再说", "改好了。", {"save_attachment", "run_command"}, False),
    ("每天早上把天气做成表格发我", "定好了。", {"run_command", "schedule_task"}, False),
    (R8Q, "解码失败了，文件好像损坏了。", {"save_attachment", "run_command"}, False),       # 如实说做不到
    ("帮我把 bmi.py 改一下加个判断", "改好了。", {"read_file", "edit_file"}, False),           # 没要文件回来
    ("帮我算下这个数发我", "答案是 42。", {"run_command"}, False),                          # 没说文件
    ("Fix this csv and send it back", "Done, fixed.", {"save_attachment", "run_command"}, True),
    ("把报告发给老王的邮箱", "已经发了。", {"run_command", "api_request"}, False),           # 不是发给我
    ("", "好了。", {"run_command"}, False),
]
bad = [(q, a, acted, w) for q, a, acted, w in CASES if bool(owed(q, a, acted)) != w]
assert not bad, bad
n = nudge(owed(R8Q, R8A, {"save_attachment", "run_command"}))
assert "display_file" in n and "再发我" in n and "照样再说一遍" in n and "用户看不到" in n and "如实" in n, n
print("rules ok")

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

ASK = "notes.txt 里的内容帮我改成正常的再发我"
cid = asyncio.run(seed(ASK))
script.extend([[("write_file", {"path": "通知_utf8.txt", "content": "期中考试 11 月 3 日 9 点 A201"})],
               R8A, [("display_file", {"paths": ["通知_utf8.txt"]})], "发你了：通知_utf8.txt，手机直接能打开。"])
n0 = len(seen)
reply = asyncio.run(turn(cid))
assert len(seen) - n0 == 4, len(seen) - n0
hint = seen[n0 + 2][-1]
assert hint["role"] == "user" and "display_file" in hint["content"] and "再发我" in hint["content"], hint
assert seen[n0 + 2][-2] == {"role": "assistant", "content": R8A}, seen[n0 + 2][-2]
body = text_of(reply)
assert "如果你要" not in body and "发你了" in body, reply.blocks
assert [s["tool"] for s in reply.steps] == ["write_file", "display_file"], reply.steps
assert any(b.get("type") in ("file", "files") for b in reply.blocks), [b.get("type") for b in reply.blocks]
print("r8 → nudge → display_file ok")

# 3) 还是不交：只拦一次；普通回答零额外调用
cid = asyncio.run(seed(ASK))
script.extend([[("write_file", {"path": "b.txt", "content": "x"})], R8A, R8A])
n0 = len(seen)
reply = asyncio.run(turn(cid))
assert len(seen) - n0 == 3 and "如果你要" in text_of(reply), (len(seen) - n0, reply.blocks)
cid = asyncio.run(seed("今天天气怎么样"))
script.extend(["今天晴，25 度。"])
n0 = len(seen)
asyncio.run(turn(cid))
assert len(seen) - n0 == 1
assert not script
print("smoke_owed_delivery OK")
