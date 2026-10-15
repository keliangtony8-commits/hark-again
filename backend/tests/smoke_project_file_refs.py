# 冒烟：项目对话里引用项目文件（v1.13）。模拟模型，只看发给模型的消息：
# user.message 的 project_files 只认这个对话所在项目里真实存在的文件（越界/不存在/.git/重复丢掉，和上传合计 ≤10）；
# 消息里存 source=project 的文件块；文本内容每轮按磁盘内联（改了文件下一轮看到新的；超长截断并提示 read_file），
# 图片/其他文件只给名字 + 提示用文件工具；文件删了说“已不在工作区里”；主聊天带项目的文件不认（主聊天认的是“我的文件”，见 smoke_personal_workspace）；重答保留引用。
# 运行：python tests/smoke_project_file_refs.py
import os, sys, asyncio, subprocess, tempfile, json
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import llm, storage
from app.agent import context, loop
from app.auth import issue_token, require_user
from app.db import SessionLocal
from app.models import Message, Project
from app.routes import conversations as rc, files as rf, ws as rws

sent: list[list[dict]] = []
async def fake_stream_turn(messages, tools=None, model=None, effort=None):
    sent.append(messages)
    yield "好"
    yield llm.Turn(text="好")
loop.stream_turn = fake_stream_turn
async def fake_complete(messages, model=None, kind="summary"):
    return "摘要"
llm.complete = fake_complete

app = FastAPI()
for r in (rws.router, rc.router, rf.router):
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
token = issue_token()

async def mk_project():
    async with SessionLocal() as db:
        p = Project(name="考研"); db.add(p); await db.commit(); return p.id
pid = asyncio.run(mk_project())
d = storage.project_dir(pid)
(d / "notes").mkdir()
(d / "notes" / "plan.md").write_text("# 复习计划\n数学每天两小时", encoding="utf-8")
(d / "long.txt").write_text("长" * (context.ATTACH_CHARS + 10), encoding="utf-8")
(d / "photo.png").write_bytes(b"\x89PNG fake")
(d / "data.bin").write_bytes(b"\0" * 12)
(d / ".git").mkdir(); (d / ".git" / "config").write_text("secret")
(storage.PROJECTS / "secret.txt").write_text("别人的")

def turn(ws, event):
    ws.send_json(event)
    first = None
    while True:
        e = ws.receive_json()
        first = first or e
        if e["type"] in ("message.done", "error"):
            assert e["type"] == "message.done", e
            return first

def last_user(msgs):
    return [m for m in msgs if m["role"] == "user"][-1]["content"]

async def user_blocks(cid):
    async with SessionLocal() as db:
        from sqlalchemy import select
        rows = (await db.scalars(select(Message).where(Message.conversation_id == cid, Message.role == "user")
                                 .order_by(Message.created_at))).all()
        return [m.blocks for m in rows]

doc = c.post("/api/uploads", files={"file": ("n.txt", "上传的笔记".encode(), "text/plain")}).json()

with c.websocket_connect(f"/ws?token={token}") as ws:
    # 1) 新的项目对话：引用 + 上传一起；坏路径全部丢掉；只有引用也能起名
    e = turn(ws, {"type": "user.message", "text": "看看这个计划", "project_id": pid, "attachments": [doc["id"]],
                  "project_files": ["notes/plan.md", "notes/plan.md", "../secret.txt", ".git/config", "nope.md",
                                    "notes", 42, "/notes/../photo.png", "data.bin", "long.txt"]})
    cid = e["conversation_id"]
    blocks = asyncio.run(user_blocks(cid))[0]
    files = [b for b in blocks if b["type"] == "file"]
    assert [(b["source"], b["id"]) for b in files] == [
        ("upload", doc["id"]), ("project", "notes/plan.md"), ("project", "photo.png"), ("project", "data.bin"),
        ("project", "long.txt")], files
    plan = files[1]
    assert plan["name"] == "plan.md" and plan["project_id"] == pid and plan["mime"] == "text/markdown" and plan["size"] > 0
    text = last_user(sent[-1])
    assert "看看这个计划" in text and "上传的笔记" in text
    assert "[用户引用的项目文件 notes/plan.md]\n# 复习计划\n数学每天两小时" in text, text
    assert "[用户引用的项目文件 photo.png（图片，9 B）——要看内容用 read_file]" in text
    assert "[用户引用的项目文件 data.bin（application/octet-stream，12 B）——要看内容用 read_file]" in text
    assert "（后面还有，需要时用 read_file 读全文）" in text and "长" * (context.ATTACH_CHARS + 1) not in text
    assert "secret" not in text and "别人的" not in text

    # 2) 文件改了：下一轮模型看到新内容；删了：说已不在
    (d / "notes" / "plan.md").write_text("# 复习计划\n改成每天三小时", encoding="utf-8")
    (d / "data.bin").unlink()
    turn(ws, {"type": "user.message", "text": "我改了", "conversation_id": cid})
    first_user = [m for m in sent[-1] if m["role"] == "user"][0]["content"]
    assert "改成每天三小时" in first_user and "两小时" not in first_user
    assert "[用户引用的项目文件 data.bin（已不在工作区里）]" in first_user

    # 3) 只有引用、没有文字也能发；对已有对话，项目以对话为准（事件里乱带 project_id 不管用）
    turn(ws, {"type": "user.message", "conversation_id": cid, "project_id": "other", "project_files": ["photo.png"]})
    assert [b["id"] for b in asyncio.run(user_blocks(cid))[-1]] == ["photo.png"]

    # 4) 重答（编辑文字）保留引用
    turn(ws, {"type": "message.regenerate", "conversation_id": cid, "text": "这张图呢"})
    last = asyncio.run(user_blocks(cid))[-1]
    assert [b.get("id") for b in last if b["type"] == "file"] == ["photo.png"] and last[0]["text"] == "这张图呢"

    # 5) 不在项目里的对话：引用全部不认；全是坏引用又没文字 = 不发
    n = len(sent)
    e = turn(ws, {"type": "user.message", "text": "普通对话", "project_files": ["notes/plan.md"]})
    assert all(b["type"] != "file" for b in asyncio.run(user_blocks(e["conversation_id"]))[0])
    ws.send_json({"type": "user.message", "project_id": pid, "project_files": ["../secret.txt"]})
    ws.send_json({"type": "user.message", "text": "ping", "project_id": "no-such-project", "project_files": ["notes/plan.md"]})
    e = None
    while True:
        e = ws.receive_json()
        if e["type"] == "message.done":
            break
    assert len(sent) == n + 2 and "ping" in last_user(sent[-1]) and "复习计划" not in last_user(sent[-1])

# 6) 上限：上传 + 引用合计 10
for i in range(12):
    (d / f"f{i}.txt").write_text(str(i))
with c.websocket_connect(f"/ws?token={token}") as ws:
    e = turn(ws, {"type": "user.message", "text": "很多", "project_id": pid, "attachments": [doc["id"]] * 3,
                  "project_files": [f"f{i}.txt" for i in range(12)]})
    assert len([b for b in asyncio.run(user_blocks(e["conversation_id"]))[-1] if b["type"] == "file"]) == 10  # v2.95 项目只有一段对话：看最新这条
assert storage.project_file(pid, "notes/plan.md") and storage.project_file(pid, "notes") is None
assert storage.project_file("", "x") is None and storage.project_file("missing", "x") is None
assert not (storage.PROJECTS / "missing").exists()
print("smoke_project_file_refs OK")
