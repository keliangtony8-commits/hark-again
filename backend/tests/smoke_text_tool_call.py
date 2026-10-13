# 冒烟：v2.54 E2E 第十轮 B26 工具调用写成了文字（app/agent/text_tool_call.py 唯一规则 + loop 撤回提醒一次）。无迁移。
# 运行：python tests/smoke_text_tool_call.py
import os, sys, asyncio, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
import subprocess
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)
from app.agent import text_tool_call as ttc
N = {"display_file", "run_command", "request_env"}
L1 = '<display_file>\n  <args>\n    <paths>["/workspace/简历_已改.docx"]</paths>\n  </args>\n</display_file>'
assert ttc.found(L1, N) == "display_file"
assert ttc.found("改好了。\n" + L1, N) == "display_file"
assert ttc.found('<tool_call>{"name": "run_command", "arguments": {"command": "ls"}}</tool_call>', N) == "run_command"
assert ttc.found('<tool_call>{"name": "zzz", "arguments": {}}</tool_call>', N) == "工具"
assert ttc.found('<function=request_env><parameter=name>X_KEY</parameter></function>', N) == "request_env"
assert ttc.found("我用 display_file 把文件交给你了。", N) is None
assert ttc.found("<display_file> 这个词", N) is None  # 没参数
assert ttc.found("```xml\n" + L1 + "\n```", N) is None  # 代码块里的示例
assert ttc.found("<b>粗体</b> <div>{\"a\":1}</div>", N) is None  # 普通 HTML
assert ttc.found("", N) is None and ttc.found(None, N) is None
assert "function call" in ttc.nudge("display_file") and " display_file " in ttc.nudge("display_file")

from app import llm, storage
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message
load_builtin()
async def seed():
    async with SessionLocal() as db:
        conv = Conversation(title="t"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("把 a.txt 发我")))
        await db.commit(); return conv.id
cid = asyncio.run(seed())
(storage.project_dir("me") / "a.txt").write_text("hello")
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
            yield chunk(tool=[NS(index=i, id=f"c{len(script)}-{i}", function=NS(name=n, arguments=json.dumps(a)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))
script.extend(['<display_file>\n<args>\n<paths>["a.txt"]</paths>\n</args>\n</display_file>',
               [("display_file", {"paths": ["/workspace/a.txt"]})], "发给你了。"])
reply = asyncio.run(turn())
assert len(seen) == 3 and "写成了回复里的文字" in seen[1][-1]["content"], seen[1][-1]
texts = "".join(b.get("text", "") for b in reply.blocks if b.get("type") == "text")
assert "<display_file>" not in texts and "发给你了" in texts, reply.blocks
assert any(b.get("type") == "file" for b in reply.blocks), reply.blocks
# 第二次还写成文字：不再拦（一轮一次），照常交付
script.extend(['<display_file><args><paths>["a.txt"]</paths></args></display_file>', '<display_file><args><paths>["a.txt"]</paths></args></display_file>'])
asyncio.run(seed())
seen.clear(); reply = asyncio.run(turn())
assert len(seen) == 2, len(seen)
print("smoke_text_tool_call OK")
