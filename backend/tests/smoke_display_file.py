# 冒烟：v1.22 display_file——把工作区里的成果交给用户（app/deliver.py 唯一实现）。
# 覆盖：工具在主聊天/项目都有；二进制图片/PDF 交付 = 快照进 uploads（source=upload，之后改/删原文件不影响卡片，
# /api/uploads/<id> 能下载到交付那刻的字节）；目录自动打包 zip（跳过 .git/.jobs/node_modules）；隐藏目录里的完整日志能交付；
# 越界、不存在、空文件、整个工作区 → 不出卡，模型看到原因；超过快照上限的普通文件退回工作区文件卡（source=project），
# 隐藏目录里的超大文件拒绝；重复路径只交一次；write_file 不再出卡；交付后的回复里模型看到“[文件：名字]”。模拟模型，无迁移。
# 运行：python tests/smoke_display_file.py
import os, sys, asyncio, subprocess, tempfile, json, zipfile, io
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', DELIVER_MAX_MB="1")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import llm, storage, workspaces, deliver
from app.agent.runner import run_turn
from app.agent.tools import REGISTRY, load_builtin
from app.auth import require_user, require_query_token
from app.blocks import text_to_blocks, blocks_to_text
from app.db import SessionLocal
from app.models import Conversation, Message, Project
from app.routes import files as rf

script: list = []
seen: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append({"messages": messages, "tools": [t["function"]["name"] for t in tools or []]})
    step = script.pop(0)
    async def gen():
        if isinstance(step, tuple):
            yield chunk(tool=[NS(index=0, id=f"c{len(script)}", function=NS(name=step[0], arguments=json.dumps(step[1], ensure_ascii=False)))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()
app = FastAPI(); app.include_router(rf.router)
app.dependency_overrides[require_user] = lambda: "u"
app.dependency_overrides[require_query_token] = lambda: "u"
c = TestClient(app)
run = asyncio.run
ME = workspaces.PERSONAL
assert REGISTRY["display_file"].scope == "always"

# ---- 准备工作区：图片、PDF、目录、隐藏日志、空文件、超大文件 ----
me = storage.project_dir(ME)
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 4
(me / "out").mkdir()
(me / "out" / "chart.png").write_bytes(PNG)
(me / "report.pdf").write_bytes(b"%PDF-1.4\n" + b"\x00\x01" * 500)
site = me / "site"; (site / "css").mkdir(parents=True); (site / "node_modules" / "x").mkdir(parents=True); (site / ".git").mkdir()
(site / "index.html").write_text("<h1>hi</h1>"); (site / "css" / "a.css").write_text("h1{}")
(site / "node_modules" / "x" / "big.js").write_text("x" * 1000); (site / ".git" / "HEAD").write_text("ref")
(me / ".jobs" / "j1").mkdir(parents=True); (me / ".jobs" / "j1" / "log").write_text("line\n" * 100)
(me / "empty.csv").write_text("")
(me / "huge.bin").write_bytes(os.urandom(1024 * 1024 + 10))
(me / ".spill").mkdir(); (me / ".spill" / "huge.txt").write_bytes(b"y" * (1024 * 1024 + 10))

async def seed():
    async with SessionLocal() as db:
        p = Project(name="报告", emoji="📊"); db.add(p); await db.flush()
        main = Conversation(title="主聊天"); proj = Conversation(title="项目里", project_id=p.id)
        db.add_all([main, proj]); await db.flush()
        for cv in (main, proj):
            db.add(Message(conversation_id=cv.id, role="user", blocks=text_to_blocks("把图表和报告给我")))
        await db.commit()
        return p.id, main.id, proj.id
pid, mid, prid = run(seed())
async def turn(conv_id):
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, conv_id))
def tool_result_text():
    return next(m["content"] for m in reversed(seen[-1]["messages"]) if m.get("role") == "tool")

# ---- 1. 主聊天：图片 + PDF + 目录 + 重复路径 + 一个错路径，按顺序出卡 ----
script.extend([("display_file", {"paths": ["out/chart.png", "report.pdf", "site", "out/chart.png", "../etc/passwd"]}), "都在这了。"])
reply = run(turn(mid))
assert "display_file" in seen[0]["tools"]
files = [b for b in reply.blocks if b["type"] == "file"]
assert [f["name"] for f in files] == ["chart.png", "report.pdf", "site.zip"], files
assert all(f["source"] == "upload" for f in files), files
assert files[0]["mime"] == "image/png" and files[1]["mime"] == "application/pdf" and files[2]["mime"] == "application/zip"
note = tool_result_text()
assert "不在工作区里" in note and "已打包成 site.zip" in note, note
# 快照：改掉/删掉原文件，下载到的仍是交付那刻的字节
(me / "out" / "chart.png").write_bytes(b"changed")
(me / "report.pdf").unlink()
r = c.get(f"/api/uploads/{files[0]['id']}")
assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
assert c.get(f"/api/uploads/{files[1]['id']}").content.startswith(b"%PDF")
names = sorted(zipfile.ZipFile(io.BytesIO(c.get(f"/api/uploads/{files[2]['id']}").content)).namelist())
assert names == ["css/a.css", "index.html"], names  # 跳过 node_modules / .git
assert not [p for p in storage.UPLOADS.iterdir() if p.name.startswith(".zip-")]  # 临时 zip 清掉了
assert "[文件：chart.png]" in blocks_to_text(reply.blocks)

# ---- 2. 项目对话：交付到项目工作区里的文件；隐藏目录的完整日志可交付 ----
pd = storage.project_dir(pid); (pd / "data.csv").write_text("a,b\n1,2\n")
script.extend([("display_file", {"paths": ["data.csv"]}), "好了。"])
reply = run(turn(prid))
f = next(b for b in reply.blocks if b["type"] == "file")
assert f["name"] == "data.csv" and f["source"] == "upload" and c.get(f"/api/uploads/{f['id']}").text == "a,b\n1,2\n"
# 主聊天里交付不到项目的文件（工作区隔离）
d_err = None
try: deliver.deliver(ME, "data.csv")
except deliver.DeliverError as e: d_err = str(e)
assert d_err and "不存在" in d_err
assert deliver.deliver(ME, ".jobs/j1/log").block["name"] == "log"

# ---- 3. 边界：空文件、整个工作区、超大普通文件（退回工作区卡）、隐藏目录超大文件（拒绝） ----
for bad, why in (("empty.csv", "空文件"), ("", "整个工作区"), (".", "整个工作区"), ("nope.txt", "不存在"), (".spill/huge.txt", "隐藏目录")):
    try: deliver.deliver(ME, bad); raise AssertionError(bad)
    except deliver.DeliverError as e: assert why in str(e), (bad, e)
big = deliver.deliver(ME, "huge.bin")
assert big.block["source"] == "project" and big.block["project_id"] == ME and big.block["id"] == "huge.bin", big
assert "超过快照上限" in big.note
assert c.get("/api/projects/me/files/huge.bin").status_code == 200
# 目录打包超限 → 拒绝
(me / "bigdir").mkdir(); (me / "bigdir" / "r.bin").write_bytes(os.urandom(1024 * 1024 + 100))
try: deliver.deliver(ME, "bigdir"); raise AssertionError("bigdir")
except deliver.DeliverError as e: assert "交付上限" in str(e), e
assert not [p for p in storage.UPLOADS.iterdir() if p.name.startswith(".zip-")]

# ---- 4. 全部失败：没有卡，模型看到每条原因 ----
script.extend([("display_file", {"paths": ["empty.csv"]}), "文件是空的，我重新生成。"])
reply = run(turn(mid))
assert not any(b["type"] == "file" for b in reply.blocks)
assert "没有交付 empty.csv" in tool_result_text()

# ---- 5. write_file 不再出卡 ----
script.extend([("write_file", {"path": "notes.md", "content": "# x"}), "写好了。"])
reply = run(turn(mid))
assert not any(b["type"] == "file" for b in reply.blocks)
print("smoke_display_file OK")
