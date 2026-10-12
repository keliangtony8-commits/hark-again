# 冒烟：输入框里的 `/init`（app/init_command.py，移植 Codex /init 提示词 + 嫁接 Gemini “模型外先查已有”）。模拟模型：
# 规则（parse：大小写、补充要求、/initial 不算、截断；of：首块文字；record / render）→
# WS 真实一轮：用户消息存 “/init”，模型收到 Codex 提示词（+ 补充要求），write_file 写出 AGENTS.md；
# 下一轮：AGENTS.md 进系统提示（workspace_instructions），历史里旧的 /init 只剩一句记录、不再给全文；
# 已有非空 AGENTS.md → 不调模型直接回一句；空文件当没有；项目对话按项目工作区查；回答途中发 /init 不插队。
# 运行：python tests/smoke_init_command.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, MODEL_ROUTER="off",
  AUTO_TITLE="false", NEXT_SPEAKER_CHECK="off", CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast",
  VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from app import init_command as ic, llm, steering, storage, workspaces
from app.agent.tools import load_builtin
from app.auth import issue_token, require_user
from app.db import SessionLocal
from app.models import Message, Project
from app.routes import conversations as rc, ws as rws

# —— 规则 ——
assert ic.parse("/init") == "" and ic.parse("  /INIT  ") == "" and ic.parse("/Init\n重点写测试") == "重点写测试"
assert ic.parse("/initial") is None and ic.parse("请 /init") is None and ic.parse("") is None and ic.parse(None) is None
assert len(ic.parse("/init " + "x" * 900)) == ic.NOTE_MAX
assert ic.of([{"type": "text", "text": "/init"}, {"type": "file", "id": "a"}]) == ""
assert ic.of([{"type": "file", "id": "a"}]) is None and ic.of([]) is None
assert ic.render("").startswith("Generate a file named AGENTS.md") and ic.NOTE_HEAD not in ic.render("")
assert ic.render("写中文").endswith(f"{ic.NOTE_HEAD}\n写中文")
assert ic.record("") == "[用户之前用 /init 让你为工作区生成 AGENTS.md]" and "补充：写中文" in ic.record("写中文")

# —— 模拟模型（走真实内核 + 真实 write_file）——
sent: list[list[dict]] = []
script: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    sent.append([dict(m) for m in messages])
    step = script.pop(0) if script else "好"
    async def gen():
        if isinstance(step, tuple):
            yield chunk(tool=[NS(index=0, id=f"c{len(sent)}", function=NS(name=step[0], arguments=json.dumps(step[1], ensure_ascii=False)))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
async def fake_complete(messages, model=None, kind="summary", **kw):
    return "摘要"
llm.complete = fake_complete
load_builtin()

app = FastAPI()
for rt in (rws.router, rc.router):
    app.include_router(rt)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
token = issue_token()
me = storage.project_dir(workspaces.PERSONAL)

def turn(ws, event):
    ws.send_json(event)
    first = None
    while True:
        e = ws.receive_json()
        first = first or e
        if e["type"] == "approval.request":
            ws.send_json({"type": "approval.response", "id": e["id"], "approved": True})
        if e["type"] in ("message.done", "error"):
            assert e["type"] == "message.done", e
            return first, e

def users(msgs):
    return [m["content"] for m in msgs if m["role"] == "user" and isinstance(m["content"], str)]

def system(msgs):
    return "\n".join(m["content"] for m in msgs if m["role"] == "system" and isinstance(m["content"], str))

async def rows(cid):
    async with SessionLocal() as db:
        return (await db.scalars(select(Message).where(Message.conversation_id == cid).order_by(Message.created_at))).all()

GUIDE = "# Repository Guidelines\n\n## Build\n- `make test` 跑全部测试\n"
(me / "README.md").write_text("# demo\n")
with c.websocket_connect(f"/ws?token={token}") as ws:
    # 1) /init → 模型收到 Codex 提示词 + 补充要求，写出 AGENTS.md；存库的仍是 “/init …”
    script.extend([("write_file", {"path": "AGENTS.md", "content": GUIDE}), "写好了 AGENTS.md。"])
    n0 = len(sent)
    first, done = turn(ws, {"type": "user.message", "text": "/init 重点写测试命令"})
    cid = first["conversation_id"]
    cur = users(sent[n0])[-1]
    assert cur.startswith("Generate a file named AGENTS.md") and cur.endswith(f"{ic.NOTE_HEAD}\n重点写测试命令"), cur
    assert (me / "AGENTS.md").read_text() == GUIDE
    msgs = asyncio.run(rows(cid))
    assert msgs[0].blocks[0]["text"] == "/init 重点写测试命令" and done["message"]["role"] == "assistant"

    # 2) 下一轮：AGENTS.md 进系统提示；旧的 /init 只留一句记录
    n1 = len(sent)
    turn(ws, {"type": "user.message", "conversation_id": cid, "text": "跑一下测试"})
    hist = users(sent[n1])
    assert "make test" in system(sent[n1]) or any("make test" in h for h in hist), system(sent[n1])[:500]
    assert ic.record("重点写测试命令") in hist and not any(h.startswith("Generate a file") for h in hist), hist

    # 3) 已有 → 不调模型，回一句
    n2 = len(sent)
    _, done = turn(ws, {"type": "user.message", "conversation_id": cid, "text": "/init"})
    assert len(sent) == n2 and done["message"]["blocks"][0]["text"] == ic.DECLINE
    assert (me / "AGENTS.md").read_text() == GUIDE
    # 重新生成同样不调模型
    _, done = turn(ws, {"type": "message.regenerate", "conversation_id": cid})
    assert len(sent) == n2 and done["message"]["blocks"][0]["text"] == ic.DECLINE

    # 4) 空文件当没有：照常交给模型
    (me / "AGENTS.md").write_text("  \n")
    assert not ic.existing(workspaces.PERSONAL)
    turn(ws, {"type": "user.message", "conversation_id": cid, "text": "/init"})
    assert len(sent) == n2 + 1 and users(sent[-1])[-1] == ic.render("")

# 5) 项目对话按项目工作区查；目录 / 符号链接都算“已有”
async def project():
    async with SessionLocal() as db:
        p = Project(name="P", emoji="📁"); db.add(p); await db.commit(); return p.id
pid = asyncio.run(project())
pd = storage.project_dir(pid)
assert not ic.existing(pid)
(pd / "AGENTS.md").mkdir(); assert ic.existing(pid); (pd / "AGENTS.md").rmdir()
os.symlink("/etc/hostname", pd / "AGENTS.md"); assert ic.existing(pid); os.unlink(pd / "AGENTS.md")
(pd / "AGENTS.md").write_text("规矩"); assert ic.existing(pid)

# 6) 回答途中发 /init：不插进正在跑的回答（排成下一轮）
assert steering.reason("/init", command=ic.parse("/init") is not None) == "rich"
print("smoke_init_command OK")
