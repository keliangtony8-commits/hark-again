# 冒烟：v2.38 E2E B12 —— 模型在猜参数时，第一次就把真正的参数给它。模拟模型。
# 1) Streak.signature_once：同一工具一轮只给一次；
# 2) check 记下 unknown；
# 3) doc_render.output_mixup：path=todo.pdf 且有 todo.md → 点名 todo.md；没源文件 → 先写 .md；.md 路径 → 空；
# 4) 一轮：普通工具给了不认识的参数 → 照常执行 + 结果附签名；同一轮第二次再猜 → 不重复附；
# 5) 一轮（按需工具 render_document，真实 E2E f10 原样）：{path: todo.pdf, content: …} → 一条结果里同时有
#    “直接 path=todo.md”和完整签名（output 一行），模型下一步就能写对，不用 describe、不另写副本。
# 运行：python tests/smoke_guessed_args.py
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

from app import llm, doc_render as D, workspaces
from app.agent import tool_args as ta
from app.agent.runner import run_turn
from app.agent.tools import ToolResult, tool, load_builtin, REGISTRY
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message
from app.storage import project_dir

SCHEMA = {"type": "object", "properties": {
    "path": {"type": "string", "description": "相对工作区的路径"},
    "content": {"type": "string", "description": "完整内容"}}, "required": ["path", "content"]}
ran: list = []

@tool("fake_note", "正在写", "测试用", SCHEMA)
async def fake_note(ctx, path: str, content: str) -> ToolResult:
    ran.append(path)
    return ToolResult(f"写好了 {path}")

# ---- 1/2. rules ----
s = ta.Streak()
first = s.signature_once("fake_note", SCHEMA)
assert first.startswith("\n\nfake_note 的参数：") and "- path（string，必填）" in first, first
assert s.signature_once("fake_note", SCHEMA) == "" and s.signature_once("other", SCHEMA) != ""
c = ta.check(SCHEMA, {"path": "a", "content": "b", "body": "x"}, {"path", "content"})
assert c.unknown == ["body"] and not c.error and "忽略了不认识的参数：body" in c.notes[0], c
c = ta.check(SCHEMA, {"path": "a", "content": "b"}, {"path", "content"})
assert c.unknown == [] and not c.notes
print("ok: rules")

# ---- 3. output_mixup ----
R = project_dir(workspaces.PERSONAL)
R.mkdir(parents=True, exist_ok=True)
(R / "todo.md").write_text("# 待办\n- 买牛奶\n", encoding="utf-8")
m = D.output_mixup(R, R / "todo.pdf")
assert "path 是要排版的源文件" in m and "直接 path=todo.md" in m and 'output="todo.pdf"' in m and "不要另写一份副本" in m, m
m2 = D.output_mixup(R, R / "plan.png")
assert "先把内容写进一个 .md 文件" in m2, m2
assert D.output_mixup(R, R / "nope.md") == ""
try:
    D._source(R, "todo.pdf")
    raise AssertionError("should fail")
except D.RenderError as e:
    assert str(e).startswith("没有 todo.pdf 这个文件。path 是要排版的源文件"), e
print("ok: output mixup")

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
        if isinstance(step, list):
            yield chunk(tools=[NS(index=i, id=f"g{len(sent)}_{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                               for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=100, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()
assert REGISTRY["render_document"].deferred

async def seed(text):
    async with SessionLocal() as db:
        conv = Conversation(title="猜参数"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks(text)))
        await db.commit()
        return conv.id
async def turn(cid):
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid))
def run(steps, text="写个文件"):
    script[:] = list(steps); sent.clear(); ran.clear()
    cid = asyncio.run(seed(text))
    return asyncio.run(turn(cid))
def results(msgs):
    return [m["content"] for m in msgs if m["role"] == "tool"]

# ---- 4. ordinary tool, unknown param ----
reply = run([[("fake_note", {"path": "a.txt", "content": "hi", "body": "x"})],
             [("fake_note", {"path": "b.txt", "content": "hi", "text": "y"})], "写好了"])
rs = results(sent[-1])
assert ran == ["a.txt", "b.txt"] and reply.status == "done", (ran, reply.status)
assert rs[0].startswith("写好了 a.txt") and "忽略了不认识的参数：body" in rs[0] and "fake_note 的参数：" in rs[0], rs[0]
assert "忽略了不认识的参数：text" in rs[1] and "fake_note 的参数：" not in rs[1], rs[1]
print("ok: unknown param → signature once")

# ---- 5. render_document, the real f10 call ----
reply = run([[("render_document", {"content": "# 待办\n- 买牛奶", "path": "todo.pdf"})], "我改一下"], "把 todo.md 转成 PDF")
rs = results(sent[-1])
assert len(rs) == 1, rs
r0 = rs[0]
assert "没有 todo.pdf 这个文件" in r0 and "直接 path=todo.md" in r0, r0
assert "忽略了不认识的参数：content" in r0 and "render_document 的参数：" in r0 and "- output（string，可选）" in r0, r0
assert reply.steps[0]["state"] == "error"
assert not (R / "todo_render.md").exists()
print("ok: render_document mixup answered in one result")
print("ALL OK")
