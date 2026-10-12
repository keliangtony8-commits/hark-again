# 冒烟：把一条回复存成项目文件（v1.15，reply_files.py + POST /api/messages/{id}/save-to-project）。
# 项目对话里不传 project_id 就存到所在项目；主聊天里不传 = 存进“我的文件”（个人工作区 me，v1.21）；文件名取摘要标题 / 正文标题 / 第一行，非法字符去掉；
# 同名不覆盖（“名字 2.md”）；内容是 Markdown（真表格、带标题的链接，审批/记忆卡不进文件）；
# 用户消息、空回复、不存在的消息/项目给 400/404；存好的文件出现在项目文件列表里，也能被下一条消息引用。
# 运行：python tests/smoke_save_reply.py
import os, sys, asyncio, subprocess, tempfile, json
from datetime import datetime, timezone
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import reply_files, storage
from app.auth import require_user
from app.db import SessionLocal
from app.models import Conversation, Message, Project
from app.routes import files as rf

app = FastAPI()
app.include_router(rf.router)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)

# ---- 纯规则 ----
md = reply_files.markdown([
    {"type": "text", "text": "## 复习计划\n先看线代"},
    {"type": "table", "title": "每周", "columns": ["周", "内容"], "rows": [["1", "行列式|矩阵"]]},
    {"type": "links", "items": [{"url": "https://a.cn", "title": "真题"}]},
    {"type": "memory", "action": "saved", "items": [{"id": "m1", "content": "考研"}]},
    {"type": "approval", "id": "a", "title": "x", "detail": "y"},
])
assert "| 周 | 内容 |\n|---|---|\n| 1 | 行列式\\|矩阵 |" in md, md
assert "- [真题](https://a.cn)" in md and "考研" not in md and "审批" not in md, md
assert reply_files.markdown([{"type": "memory", "action": "saved", "items": [{"id": "m", "content": "x"}]}]) == ""
assert reply_files.file_name([{"type": "text", "text": "好的\n# 复习/计划: 第1周"}]) == "复习 计划 第1周"
assert reply_files.file_name([{"type": "text", "text": "- **先**说结论。"}]) == "先说结论"
assert reply_files.file_name([{"type": "summary", "title": "杭州两日游", "markdown": "x"}, {"type": "text", "text": "# 别的"}]) == "杭州两日游"
assert len(reply_files.file_name([{"type": "text", "text": "很" * 100}])) == reply_files.NAME_MAX
at = datetime(2026, 10, 12, 1, 5, tzinfo=timezone.utc)
assert reply_files.file_name([{"type": "images", "items": [{"url": "https://i.cn/a.png"}]}], at) == "回复 10-12 0905"

# ---- 种数据 ----
async def seed():
    async with SessionLocal() as db:
        p = Project(name="考研", emoji="📚"); other = Project(name="旅行", emoji="🧳")
        db.add_all([p, other]); await db.flush()
        pc = Conversation(title="项目里", project_id=p.id); mc = Conversation(title="主聊天")
        db.add_all([pc, mc]); await db.flush()
        ms = [
            Message(conversation_id=pc.id, role="assistant", blocks=[{"type": "summary", "title": "数一复习计划", "subtitle": "10 月", "markdown": "- 线代\n- 概率"}]),
            Message(conversation_id=pc.id, role="user", blocks=[{"type": "text", "text": "谢谢"}]),
            Message(conversation_id=mc.id, role="assistant", blocks=[{"type": "text", "text": "# 行李清单\n- 护照"}]),
            Message(conversation_id=mc.id, role="assistant", blocks=[{"type": "memory", "action": "saved", "items": [{"id": "m", "content": "x"}]}]),
        ]
        db.add_all(ms); await db.commit()
        return p.id, other.id, [m.id for m in ms]
pid, oid, (m_proj, m_user, m_main, m_empty) = asyncio.run(seed())

# 项目对话：不传 project_id → 存到所在项目
r = c.post(f"/api/messages/{m_proj}/save-to-project", json={})
assert r.status_code == 200, r.text
d = r.json()
assert d["project_id"] == pid and d["project_name"] == "考研" and d["path"] == "数一复习计划.md" and d["mime"].startswith("text/"), d
text = (storage.project_dir(pid) / "数一复习计划.md").read_text()
assert text.startswith("# 数一复习计划\n\n*10 月*\n\n- 线代"), text
# 再存一次不覆盖
assert c.post(f"/api/messages/{m_proj}/save-to-project", json={}).json()["path"] == "数一复习计划 2.md"
files = [f["path"] for f in c.get(f"/api/projects/{pid}/files").json()]
assert sorted(files) == ["数一复习计划 2.md", "数一复习计划.md"], files
# 也能当项目文件引用（v1.13 的唯一检查）
assert storage.project_file(pid, "数一复习计划.md") is not None

# 主聊天：不指定 = 我的文件（个人工作区）；也能显式传 "me"
r = c.post(f"/api/messages/{m_main}/save-to-project", json={})
assert r.status_code == 200 and r.json()["project_id"] == "me" and r.json()["project_name"] == "我的文件", r.text
assert [f["path"] for f in c.get("/api/projects/me/files").json()] == ["行李清单.md"]
assert c.post(f"/api/messages/{m_main}/save-to-project", json={"project_id": "me"}).json()["path"] == "行李清单 2.md"
r = c.post(f"/api/messages/{m_main}/save-to-project", json={"project_id": oid})
assert r.status_code == 200 and r.json()["path"] == "行李清单.md" and r.json()["project_name"] == "旅行", r.text
# 项目对话里的回复也能存到别的项目
assert c.post(f"/api/messages/{m_proj}/save-to-project", json={"project_id": oid}).json()["project_id"] == oid

# 错误
assert c.post(f"/api/messages/{m_user}/save-to-project", json={}).status_code == 400
assert c.post(f"/api/messages/{m_empty}/save-to-project", json={"project_id": oid}).status_code == 400
assert c.post("/api/messages/nope/save-to-project", json={}).status_code == 404
assert c.post(f"/api/messages/{m_main}/save-to-project", json={"project_id": "nope"}).status_code == 404
print("OK smoke_save_reply")
