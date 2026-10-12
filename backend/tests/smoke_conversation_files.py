# 冒烟：v1.33 本对话全部文件（app/conversation_files.py 唯一规则 + GET /api/conversations/{id}/files[.zip]）。
# 覆盖：真实回合（模拟模型）里 write_file 完成的步骤 → “助手写的”；display_file → “交给你的”（上传快照）；
# 用户附件 / 引用工作区文件 → “你发的”；浏览器卡 files → “网页下载的” / “传到网页的”；同一文件多次只留最新来源；
# 最新在前；工作区文件大小读磁盘当前值；删掉的 → gone（列出但不进 zip）；没批准/出错的 write_file 不列；
# 项目对话按项目工作区找；截断的长路径不列；zip 扁平、重名加 (2)、临时目录清掉；没有文件 → 409；
# 超过打包上限 → 409；不存在的对话 404。模拟模型，无迁移（没有新表/列）。
# 运行：python tests/smoke_conversation_files.py
import os, sys, asyncio, subprocess, tempfile, json, zipfile, io, time
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import llm, storage, workspaces, conversation_files as cf
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.auth import require_user, require_query_token
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message, Project
from app.routes import files as rf

script: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
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
me = storage.project_dir(ME)

async def seed():
    async with SessionLocal() as db:
        p = Project(name="论文", emoji="📄"); db.add(p); await db.flush()
        main = Conversation(title="整理/资料:1"); proj = Conversation(title="项目里", project_id=p.id); empty = Conversation(title="空")
        db.add_all([main, proj, empty]); await db.flush()
        await db.commit()
        return p.id, main.id, proj.id, empty.id
pid, mid, prid, eid = run(seed())

async def add(conv_id, role, blocks, steps=None):
    async with SessionLocal() as db:
        db.add(Message(conversation_id=conv_id, role=role, blocks=blocks, steps=steps or []))
        await db.commit()
    time.sleep(0.01)  # created_at 有先后
async def turn(conv_id):
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, conv_id))

# ---- 1. 用户发附件 + 引用工作区文件 ----
up = storage.save_upload("需求.pdf", b"%PDF-1.4 x")
(me / "notes").mkdir(); (me / "notes" / "a.md").write_text("# a")
run(add(mid, "user", text_to_blocks("看看这些") + [
    {"type": "file", "source": "upload", **up},
    {"type": "file", "source": "project", "id": "notes/a.md", "name": "a.md", "mime": "text/markdown", "size": 3, "project_id": ME},
]))
# ---- 2. 真实回合：write_file 写一个、display_file 交一个 ----
script.extend([("write_file", {"path": "out/summary.md", "content": "# 总结\n" * 10}),
               ("display_file", {"paths": ["out/summary.md"]}), "写好了，也交给你了。"])
reply = run(turn(mid))
delivered = next(b for b in reply.blocks if b["type"] == "file")
# ---- 3. 浏览器下载 + 传到网页（同一回复里还“又写了一次 notes/a.md”）----
(me / "downloads").mkdir(); (me / "downloads" / "发票.pdf").write_bytes(b"%PDF" + b"0" * 100)
run(add(mid, "assistant", [{"type": "browser", "session": "x-com", "workspace": ME, "files": [
    {"kind": "download", "name": "发票.pdf", "path": "downloads/发票.pdf"},
    {"kind": "upload", "name": "a.md", "path": "notes/a.md"}]}],
    steps=[{"id": "s1", "tool": "write_file", "title": "写文件", "detail": "rejected.txt", "state": "denied"},
           {"id": "s2", "tool": "write_file", "title": "写文件", "detail": "broke.txt", "state": "error"},
           {"id": "s3", "tool": "write_file", "title": "写文件", "detail": "very/long/path…", "state": "done"}]))

items = c.get(f"/api/conversations/{mid}/files").json()
names = [(f["name"], f["origin"]) for f in items["files"]]
assert names == [("a.md", "to_web"), ("发票.pdf", "downloaded"), ("summary.md", "delivered"),
                 ("summary.md", "written"), ("需求.pdf", "sent")], names
by = {(f["name"], f["origin"]): f for f in items["files"]}
assert by[("summary.md", "delivered")]["source"] == "upload" and by[("summary.md", "delivered")]["id"] == delivered["id"]
w = by[("summary.md", "written")]
assert w["source"] == "project" and w["project_id"] == ME and w["id"] == "out/summary.md" and not w["gone"]
assert w["size"] == len("# 总结\n".encode() * 10), w
assert by[("需求.pdf", "sent")]["project_id"] is None and by[("需求.pdf", "sent")]["mime"] == "application/pdf"
assert all(f["at"] and f["message_id"] for f in items["files"])
assert items["count"] == 5 and items["available"] == 5

# 工作区文件变了 → 大小跟着变；删掉 → gone，仍列出
(me / "out" / "summary.md").write_text("短")
(me / "downloads" / "发票.pdf").unlink()
items = c.get(f"/api/conversations/{mid}/files").json()
by = {(f["name"], f["origin"]): f for f in items["files"]}
assert by[("summary.md", "written")]["size"] == len("短".encode())
assert by[("发票.pdf", "downloaded")]["gone"] and items["available"] == 4 and items["count"] == 5

# ---- 4. 打包：扁平、重名加 (2)、删掉的不进、临时目录清掉 ----
r = c.get(f"/api/conversations/{mid}/files.zip")
assert r.status_code == 200 and r.headers["content-type"] == "application/zip", r.text
assert "attachment" in r.headers["content-disposition"]
z = zipfile.ZipFile(io.BytesIO(r.content))
assert sorted(z.namelist()) == ["a.md", "summary (2).md", "summary.md", "需求.pdf"], z.namelist()
assert z.read("需求.pdf") == b"%PDF-1.4 x"
assert not [p for p in storage.UPLOADS.iterdir() if p.name.startswith(".zip-")]
assert cf._free("x.tar", {"x.tar"}) == "x (2).tar" and cf._free("Makefile", {"Makefile"}) == "Makefile (2)"

# ---- 5. 项目对话：按项目工作区找；主聊天的个人文件在项目里显示 gone ----
pd = storage.project_dir(pid); (pd / "data.csv").write_text("a,b\n")
script.extend([("write_file", {"path": "data2.csv", "content": "1,2\n"}), "好了。"])
run(turn(prid))
run(add(prid, "assistant", [], steps=[{"id": "s9", "tool": "write_file", "detail": "out/summary.md", "state": "done"}]))
pf = c.get(f"/api/conversations/{prid}/files").json()["files"]
assert [(f["name"], f["project_id"], f["gone"]) for f in pf] == [("summary.md", pid, True), ("data2.csv", pid, False)], pf

# ---- 6. 空对话 / 不存在 / 超过上限 ----
assert c.get(f"/api/conversations/{eid}/files").json() == {"count": 0, "available": 0, "size": 0, "zip_max": 200 * 1024 * 1024, "files": []}
r = c.get(f"/api/conversations/{eid}/files.zip"); assert r.status_code == 409 and "没有还在的文件" in r.json()["detail"]
assert c.get("/api/conversations/nope/files").status_code == 404
assert c.get("/api/conversations/nope/files.zip").status_code == 404
cf.ZIP_MAX_MB = 0
r = c.get(f"/api/conversations/{mid}/files.zip"); assert r.status_code == 409 and "超过打包上限" in r.json()["detail"], r.text
print("ok smoke_conversation_files")
