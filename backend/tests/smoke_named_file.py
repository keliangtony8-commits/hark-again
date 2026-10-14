# 冒烟：v2.73 E2E B40 “点名存成 X.csv、回复说生成好了、工作区里却没有”（app/agent/named_file.py）。无迁移。
# 1) 规则：wanted 抽文件名（存成 / 保存为 / 导出到 / 写进 / save as…；别存 / 删掉的不算）；missing 看磁盘
#    （根目录或子目录同名都算有）；如实说失败 / 建了定时任务 / 只是反问 → 不追究；
# 2) 一轮模拟模型（真机 v7 原样）：只 read_file 就说“已经生成好了 通讯录_整理.csv” → 撤回 + 内部提示 → write_file → 交付；
# 3) 第二次照样不写：只拦一次；文件确实写了 / 普通问答零额外调用。
# 运行：python tests/smoke_named_file.py
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
from pathlib import Path
from app.agent.named_file import wanted, missing, nudge
V7Q = "通讯录.csv 里的手机号格式乱七八糟，帮我统一成 138-1234-5678 这种格式，存成 通讯录_整理.csv；不是有效手机号的单独告诉我。"
W = [
    (V7Q, ["通讯录_整理.csv"]),
    ("给我列个买菜清单，存成 购物清单.txt。", ["购物清单.txt"]),
    ("结果保存为“报告 终版.docx”", []),  # 引号里有空格：不认（名字不含空白），宁漏不错
    ("把结果导出到 out/summary.xlsx 发我", ["out/summary.xlsx"]),
    ("写进 /workspace/notes.md 里", ["notes.md"]),
    ("另存为report.pdf就行", ["report.pdf"]),
    ("先别存成 a.txt，给我看看", []),
    ("把存成 old.txt 的那份删掉", []),
    ("把 订单.json 转成 Excel 表格", []),
    ("根据 data.csv 生成图表", []),
    ("Clean it up and save it as clean.csv", ["clean.csv"]),
    ("create todo.md with my tasks", ["todo.md"]),
    ("这个 a.txt 讲了什么", []),
]
bad = [(q, wanted(q), w) for q, w in W if wanted(q) != w]
assert not bad, bad
ws = Path(tmp) / "ws"; (ws / "sub").mkdir(parents=True)
(ws / "have.csv").write_text("x"); (ws / "sub" / "deep.txt").write_text("x")
CLAIM = "整理后的内容已经生成好了。整理后文件 `通讯录_整理.csv`"
M = [
    (V7Q, CLAIM, {"read_file"}, ["通讯录_整理.csv"]),
    ("存成 have.csv", "好了", {"run_command"}, []),
    ("存成 deep.txt", "好了", {"run_command"}, []),          # 子目录里有同名文件
    ("存成 sub/deep.txt", "好了", set(), []),
    ("存成 other/deep.txt", "好了", set(), ["other/deep.txt"]),
    (V7Q, "写文件失败了：磁盘满。", {"run_command"}, []),       # 如实
    ("每天早上存成 weather.csv", "定好了", {"schedule_task"}, []),
    (V7Q, "号码里 +86 开头的要保留国家码吗？", {"read_file"}, []),  # 反问
    ("帮我算一下", "42", set(), []),
]
bad = [(q, a, missing(q, a, ws, acted), w) for q, a, acted, w in M if missing(q, a, ws, acted) != w]
assert not bad, bad
assert missing(V7Q, CLAIM, None, set()) == [] and missing(V7Q, CLAIM, ws / "nope", set()) == []
n = nudge(["通讯录_整理.csv"])
assert "「通讯录_整理.csv」" in n and "write_file" in n and "如实" in n and "用户看不到" in n, n
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

V7A = "整理后的内容已经生成好了，包含有效号码的格式化结果。\n\n**整理后文件**\n`通讯录_整理.csv`\n\n| 姓名 | 手机 |\n| --- | --- |\n| 王明 | 138-1234-5678 |"
from app.config import settings
from app import storage
cid = asyncio.run(seed(V7Q))
async def ws_of(cid):
    async with SessionLocal() as db:
        conv = await db.get(Conversation, cid)
        from app.workspaces import of
        return of(conv.project_id)
root = storage.project_file_root(asyncio.run(ws_of(cid)))
root.mkdir(parents=True, exist_ok=True)
(root / "通讯录.csv").write_text("姓名,手机\n王明,13812345678\n", encoding="utf-8")
script.extend([[("read_file", {"path": "通讯录.csv"})], V7A,
               [("write_file", {"path": "通讯录_整理.csv", "content": "姓名,手机\n王明,138-1234-5678\n"})],
               "存好了：通讯录_整理.csv。"])
n0 = len(seen)
reply = asyncio.run(turn(cid))
assert len(seen) - n0 == 4, (len(seen) - n0, [s["tool"] for s in reply.steps], text_of(reply))
hint = seen[n0 + 2][-1]
assert hint["role"] == "user" and "通讯录_整理.csv" in hint["content"] and "write_file" in hint["content"], hint
assert seen[n0 + 2][-2] == {"role": "assistant", "content": V7A}, seen[n0 + 2][-2]
assert "存好了" in text_of(reply) and "已经生成好了" not in text_of(reply), reply.blocks
assert [s["tool"] for s in reply.steps] == ["read_file", "write_file"], reply.steps
assert (root / "通讯录_整理.csv").is_file()
print("v7 → nudge → write_file ok")

# 3) 只拦一次；写了的、普通问答零额外调用
Q2 = "把结果存成 never.csv"
cid = asyncio.run(seed(Q2))
script.extend(["已经生成好了 never.csv。", "已经生成好了 never.csv。"])
n0 = len(seen)
reply = asyncio.run(turn(cid))
assert len(seen) - n0 == 2, len(seen) - n0
cid = asyncio.run(seed("把结果存成 real.csv"))
script.extend([[("write_file", {"path": "real.csv", "content": "a"})], "存好了 real.csv。"])
n0 = len(seen)
asyncio.run(turn(cid))
assert len(seen) - n0 == 2, len(seen) - n0
cid = asyncio.run(seed("今天天气怎么样"))
script.extend(["今天晴，25 度。"])
n0 = len(seen)
asyncio.run(turn(cid))
assert len(seen) - n0 == 1
assert not script
print("smoke_named_file OK")
