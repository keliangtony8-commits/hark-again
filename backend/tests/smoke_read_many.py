# 冒烟：v2.33 CORE 36 一次读多个文件——app/read_many.py 唯一规则 + read_many_files 工具。
# 1) 规则：路径 + glob 展开、去重保序、目录/不存在/越界/隐藏/图片/文档/二进制跳过并说原因、FILES_MAX、预算平分 + 续读提示；
# 2) 工具：参数校验、file_seen 记读过（之后 write_file 能覆盖）、计划模式和子助手可用；
# 3) 一轮（模拟模型）：一次读三个文件回答，时间线 detail “3 个文件”。
# 运行：python tests/smoke_read_many.py
import os, sys, asyncio, subprocess, tempfile, json, tracemalloc
from pathlib import Path
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import file_seen, plan_mode, read_many as RM, workspaces
from app.agent import subagent
from app.agent.runner import run_turn
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message
from app.storage import project_dir

WS = workspaces.PERSONAL
r0 = project_dir(WS)
(r0 / "conf").mkdir(parents=True, exist_ok=True)
(r0 / "README.md").write_text("# 记账脚本\n跑 python main.py\n")
(r0 / "main.py").write_text("import json\nprint(json.load(open('conf/a.json')))\n")
(r0 / "conf/a.json").write_text('{"rate": 7.1}')
(r0 / "conf/b.json").write_text('{"rate": 7.2}')
(r0 / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 40)
(r0 / "doc.pdf").write_bytes(b"%PDF-1.4\n" + b"0" * 40)
(r0 / "blob.bin").write_bytes(b"\x00\x01\x02" * 50)
(r0 / ".jobs/j9").mkdir(parents=True, exist_ok=True)
(r0 / ".jobs/j9/log").write_text("done\n")
(r0 / "node_modules/x").mkdir(parents=True, exist_ok=True)
(r0 / "node_modules/x/c.json").write_text("{}")

# ---- 1. 规则 ----
files, skipped = RM.expand(WS, ["README.md", "conf/*.json", "./README.md", "conf", "nope.txt", "../etc/passwd", "*.json"])
assert [r for r, _ in files] == ["README.md", "conf/a.json", "conf/b.json"], files  # 去重保序；*.json 不进 node_modules
why = dict(skipped)
assert "是目录" in why["conf"] and why["nope.txt"] == "不存在" and why["../etc/passwd"] == "不在工作区里", skipped
b = RM.read(WS, ["README.md", "main.py", "conf/a.json"])
assert b.failed is None and b.detail == "3 个文件" and len(b.read) == 3
assert b.text.startswith("读了 3 个文件：\n\n--- README.md ---\n# 记账脚本") and "--- conf/a.json ---\n{\"rate\": 7.1}" in b.text
b = RM.read(WS, ["pic.png", "doc.pdf", "blob.bin", "main.py", "zz*.md"])
assert "是图片" in b.text and "是文档" in b.text and "不是文本文件" in b.text and "zz*.md：没有匹配的文件" in b.text
assert b.detail == "1 个文件，4 个没读" and b.failed is None
assert RM.read(WS, [".jobs/j9/log"]).text.endswith("done\n")  # 明确点名隐藏目录里的日志照读
b = RM.read(WS, ["nope.txt"])
assert b.failed == "没读到文件" and "一个文件都没读到" in b.text
assert RM.read(WS, []).failed == "参数不对" and RM.read(WS, "README.md").failed == "参数不对"
for i in range(25):
    (r0 / f"many/f{i:02d}.txt").parent.mkdir(exist_ok=True)
    (r0 / f"many/f{i:02d}.txt").write_text(f"文件 {i}\n")
b = RM.read(WS, ["many/*.txt"])
assert len(b.read) == RM.FILES_MAX and b.text.count("一次最多读") == 5 and "…还有" not in b.text, b.detail
big = "x" * 30000
(r0 / "big1.txt").write_text(big); (r0 / "big2.txt").write_text(big)
b = RM.read(WS, ["big1.txt", "big2.txt", "README.md"])
assert len(b.text) < 16000, len(b.text)  # 低于 tool_result_max，不被二次截断
assert b.text.count("下一段用 offset=") == 2 and "# 记账脚本" in b.text, b.text[-500:]
for i in range(12):
    (r0 / f"huge/h{i:02d}.txt").parent.mkdir(exist_ok=True)
    (r0 / f"huge/h{i:02d}.txt").write_text(big)
b = RM.read(WS, ["huge/*.txt"])
assert len(b.read) == 11 and "预算用完" in b.text and len(b.text) < 16000, (len(b.read), len(b.text))

# ---- 2. 工具 ----
load_builtin()
t = REGISTRY["read_many_files"]
assert t.parallel and not getattr(t, "deferred", False)
assert "read_many_files" in plan_mode.READ_TOOLS and "read_many_files" in subagent.CHILD_TOOLS
ctx = ToolContext(db=None, conversation_id="c-m")
res = asyncio.run(t.run(ctx, paths=["main.py", "README.md"]))
assert res.detail == "2 个文件" and not res.failed
owner = file_seen.owner_of("c-m", None)
file_seen.check_write(owner, r0 / "main.py", "main.py")  # 读过 → 允许覆盖，不抛
res = asyncio.run(t.run(ctx, paths=None))
assert res.failed == "参数不对"

# ---- 4. 一轮（模拟模型）----
from app import llm
seen, script = [], []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append([dict(m) for m in messages])
    step = script.pop(0)
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"c{len(script)}-{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
async def seed():
    async with SessionLocal() as db:
        conv = Conversation(title="脚本"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("看看这个记账脚本用的汇率是多少")))
        await db.commit()
        return conv.id
cid = asyncio.run(seed())
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))
script.extend([[("read_many_files", {"paths": ["README.md", "main.py", "conf/a.json"]})], "汇率是 7.1。"])
reply = asyncio.run(turn())
tool_msg = next(m for m in seen[1] if m["role"] == "tool")
assert "--- conf/a.json ---" in tool_msg["content"] and "--- main.py ---" in tool_msg["content"], tool_msg["content"]
assert [(x["tool"], x["state"], x.get("detail")) for x in reply.steps] == [("read_many_files", "done", "3 个文件")], reply.steps
print("smoke_read_many ok")
