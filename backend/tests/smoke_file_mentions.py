# 冒烟：消息里的 @路径（app/file_mentions.py，移植自 Gemini CLI atCommandProcessor）。模拟模型，只看发给模型的消息：
# 规则（parse：邮箱/代码/引号/转义/全角标点/行号；resolve：原样 → 去行号 → 中英交界截短 → **/*名字* 取最新；
# 越界/隐藏/目录不认）→ WS：项目对话 “看看@plan” 附上 notes/plan.md、内容进模型；和选择器选的去重；
# 主聊天解析“我的文件”；!命令 不解析；编辑消息新写的 @ 补上、原附件保留；没有的文件只留文字。
# 运行：python tests/smoke_file_mentions.py
import os, sys, asyncio, subprocess, tempfile, json, time
from pathlib import Path
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, MODEL_ROUTER="off",
  AUTO_TITLE="false", NEXT_SPEAKER_CHECK="off", USER_SHELL="false",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from app import file_mentions as fm, llm, storage
from app.agent import loop
from app.auth import issue_token, require_user
from app.db import SessionLocal
from app.models import Message, Project
from app.routes import conversations as rc, files as rf, ws as rws

# —— 规则：parse ——
P = fm.parse
assert P("看看@notes/plan.md，然后呢") == ["notes/plan.md"]
assert P("邮件 a@b.com 和 x.y@z.cn") == []
assert P("end @a.txt.") == ["a.txt"] and P("(@x.py)") == ["x.py"] and P("@") == [] and P(None) == [] and P("") == []
assert P('读 @"my file.txt" 和 @a\\ b.md') == ["my file.txt", "a b.md"]
assert P("`@x/y` 不算\n```\n@decorator\n```\n@ok.md") == ["ok.md"]
assert P("@a.py:10-20 和 @b.ts#L3 @a.py:10-20") == ["a.py:10-20", "b.ts#L3"]
assert P("@a.md、@b.md；@c.md") == ["a.md", "b.md", "c.md"]
assert len(P(" ".join(f"@f{i}" for i in range(30)))) == fm.MENTIONS_MAX
assert fm.strip_line_suffix("a.py:10") == "a.py" and fm.strip_line_suffix("a.py#L1-L5") == "a.py"
assert fm.strip_line_suffix("a.py:3:4-5:6") == "a.py" and fm.strip_line_suffix("a.py") is None
assert fm._candidates("main.py然后:3")[:3] == ["main.py然后:3", "main.py然后", "main.py"]

# —— 规则：resolve ——
w = Path(tmp) / "w"; (w / "notes").mkdir(parents=True); (w / "src" / "deep").mkdir(parents=True)
(w / "notes" / "plan.md").write_text("# 计划", encoding="utf-8")
(w / "src" / "main.py").write_text("print(1)")
(w / "src" / "deep" / "util.py").write_text("x")
(w / "报告.md").write_text("中文名")
(w / ".git").mkdir(); (w / ".git" / "config").write_text("secret")
(w / "old_notes.txt").write_text("old"); (w / "new_notes.txt").write_text("new")
t = time.time(); os.utime(w / "old_notes.txt", (t - 100, t - 100)); os.utime(w / "new_notes.txt", (t, t))
(Path(tmp) / "outside.txt").write_text("别人的")
R = lambda tok: fm.resolve(w, tok)
assert R("notes/plan.md") == "notes/plan.md" and R("/notes/plan.md") == "notes/plan.md"
assert R("notes/plan.md:12") == "notes/plan.md" and R("src/main.py#L1-L3") == "src/main.py"
assert R("plan") == "notes/plan.md" and R("PLAN.MD") == "notes/plan.md"          # 模糊：文件名包含，忽略大小写
assert R("deep/util") == "src/deep/util.py" and R("main.py然后改") == "src/main.py"
assert R("报告.md") == "报告.md" and R("报告") == "报告.md"
assert R("src/deep") is None and R("deep") is None and R("notes") == "new_notes.txt"  # 目录不附（名字撞上文件才算文件）
assert R("notes.txt") == "new_notes.txt"                                           # 多个命中取最新
assert R("../outside.txt") is None and R("outside") is None and R(".git/config") is None and R("config") is None
assert R("*.md") is None and R("~/.bashrc") is None and R("nothing-here") is None
assert fm.paths("看 @plan 和 @notes/plan.md 还有 @nope", w) == ["notes/plan.md"]
assert fm.paths("@plan", Path(tmp) / "missing") == []

# —— WS ——
sent: list[list[dict]] = []
async def fake_stream_turn(messages, tools=None, model=None, effort=None):
    sent.append([dict(m) for m in messages])
    yield "好"
    yield llm.Turn(text="好")
loop.stream_turn = fake_stream_turn
async def fake_complete(messages, model=None, kind="summary", **kw):
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
(d / "photo.png").write_bytes(b"\x89PNG fake")
me = storage.project_dir("me")
(me / "简历.md").write_text("我的简历内容", encoding="utf-8")

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
        rows = (await db.scalars(select(Message).where(Message.conversation_id == cid, Message.role == "user")
                                 .order_by(Message.created_at))).all()
        return [m.blocks for m in rows]

def refs(blocks):
    return [b["id"] for b in blocks if b["type"] == "file"]

with c.websocket_connect(f"/ws?token={token}") as ws:
    # 1) 项目对话：@plan 模糊命中，内容进模型；文字原样保留
    e = turn(ws, {"type": "user.message", "text": "看看@plan，帮我改改", "project_id": pid})
    cid = e["conversation_id"]
    b = asyncio.run(user_blocks(cid))[0]
    assert b[0]["text"] == "看看@plan，帮我改改" and refs(b) == ["notes/plan.md"], b
    assert b[1]["source"] == "project" and b[1]["project_id"] == pid
    text = last_user(sent[-1])
    assert "[用户引用的项目文件 notes/plan.md]\n# 复习计划\n数学每天两小时" in text, text

    # 2) 和选择器选的去重；没有的文件、邮箱只留文字
    turn(ws, {"type": "user.message", "conversation_id": cid, "text": "@notes/plan.md:2 和 @photo.png 还有 @nope.md 发 a@b.com",
              "project_files": ["photo.png"]})
    assert refs(asyncio.run(user_blocks(cid))[-1]) == ["photo.png", "notes/plan.md"]

    # 3) 编辑：新写的 @ 补上，原附件保留不重复
    turn(ws, {"type": "message.regenerate", "conversation_id": cid, "text": "那 @photo 和 @plan 呢"})
    assert refs(asyncio.run(user_blocks(cid))[-1]) == ["photo.png", "notes/plan.md"]
    turn(ws, {"type": "user.message", "conversation_id": cid, "text": "就一句话"})
    turn(ws, {"type": "message.regenerate", "conversation_id": cid, "text": "改成看 @plan"})
    last = asyncio.run(user_blocks(cid))[-1]
    assert refs(last) == ["notes/plan.md"] and last[0]["text"] == "改成看 @plan"
    assert "[用户引用的项目文件 notes/plan.md]" in last_user(sent[-1])

    # 4) 主聊天 = 我的文件；项目里的文件不认
    e = turn(ws, {"type": "user.message", "text": "按@简历 写封信，也看看 @plan"})
    b = asyncio.run(user_blocks(e["conversation_id"]))[0]
    assert refs(b) == ["简历.md"] and b[1]["project_id"] == "me"
    assert "我的简历内容" in last_user(sent[-1])

    # 5) 乱带 project_id（不存在 / 越界）：不扫描、不附
    e = turn(ws, {"type": "user.message", "text": "看 @plan", "project_id": "../" + pid})
    assert refs(asyncio.run(user_blocks(e["conversation_id"]))[0]) == []

    # 6) 一条消息最多 10 个文件：选择器选满了，@ 的不再加
    for i in range(12):
        (d / f"f{i}.md").write_text(str(i))
    turn(ws, {"type": "user.message", "conversation_id": cid, "text": "@plan",
              "project_files": [f"f{i}.md" for i in range(10)]})
    assert refs(asyncio.run(user_blocks(cid))[-1]) == [f"f{i}.md" for i in range(10)]

# 7) !命令 不解析（开关开着时）
from app.config import settings
settings.user_shell = True
from app import user_shell
assert user_shell.parse("!cat @plan") == "cat @plan"
async def mentions_for_shell():
    async with SessionLocal() as db:
        return await rws._project_files(db, pid, [], 10, "!cat @plan"), await rws._project_files(db, pid, [], 10, "cat @plan")
a, b2 = asyncio.run(mentions_for_shell())
assert a == [] and refs(b2) == ["notes/plan.md"]
print("smoke_file_mentions OK")
