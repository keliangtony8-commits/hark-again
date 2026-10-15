# 冒烟：项目档案。模拟模型在项目对话里：第一轮 project_brief write 建档 → 一句话收尾；
# 第二轮 edit 改一处（系统提示里已经带着档案全文）；edit 找不到/不唯一时返回错误且不改；
# 普通对话不提供该工具；PATCH brief 盖“user”戳，内容不变不盖、改 rules 不盖、超长 422。
# 运行：python tests/smoke_project_brief.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from app import llm, project_brief, project_chat
from app.agent import runner
from app.agent.tools import ToolContext, load_builtin, schemas
from app.auth import require_user
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message, Project
from app.routes.resources import routers

script: list = []   # 每次模型调用弹出一项：dict = 调工具，str = 文字
seen: list = []     # 每次调用收到的系统提示和工具名

def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)

async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append((messages[0]["content"], [t["function"]["name"] for t in (tools or [])]))
    step = script.pop(0)
    async def gen():
        if isinstance(step, dict):
            yield chunk(tool=[NS(index=0, id=f"c{len(seen)}", function=NS(name="project_brief", arguments=json.dumps(step, ensure_ascii=False)))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()

BRIEF = "## 目标\n12 月考研，目标 985 计算机。\n## 做法\n- 每天晚上复盘错题"

async def turn(pid, text):
    async with SessionLocal() as db:
        conv = await project_chat.ensure(db, await db.get(Project, pid)); await db.commit()  # v2.95 项目 = 一段对话：两轮都在这段里
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks(text)))
        await db.commit()
        await runner.run_turn(db, conv)
        tool_out = (await db.scalars(select(Message).where(Message.conversation_id == conv.id, Message.role == "assistant"))).all()
        return tool_out

async def get(pid):
    async with SessionLocal() as db:
        return await db.get(Project, pid)

async def main():
    async with SessionLocal() as db:
        p = Project(name="考研"); db.add(p); await db.commit(); pid = p.id
        assert "project_brief" not in [s["function"]["name"] for s in schemas(ToolContext(db=db))]
        assert "project_brief" in [s["function"]["name"] for s in schemas(ToolContext(db=db, project_id=pid))]

    script[:] = [{"action": "write", "content": BRIEF}, "建好了。"]
    await turn(pid, "我在准备考研")
    assert "档案目前是空的" in seen[0][0] and "project_brief" in seen[0][1], seen[0]
    p = await get(pid)
    assert p.brief == BRIEF and p.brief_by == "assistant" and p.brief_updated_at, p.brief

    seen.clear()
    script[:] = [{"action": "edit", "find": "985 计算机", "replace": "211 软件工程"}, "改好了。"]
    await turn(pid, "目标换成 211 软件工程")
    assert "12 月考研，目标 985 计算机" in seen[0][0], seen[0][0]   # 改之前的档案在系统提示里
    assert (await get(pid)).brief.count("211 软件工程") == 1

    # edit 出错：不改库，错误回给模型
    async with SessionLocal() as db:
        p = await db.get(Project, pid)
        assert "没有这段原文" in project_brief.edit(p, "不存在的字", "x")
        assert "出现了 2 次" in project_brief.edit(p, "目标", "x")
        assert "太长" in project_brief.write(p, "x" * (project_brief.BRIEF_MAX + 1))
        assert p.brief.count("211") == 1
        long = Project(name="长", brief="y" * (project_brief.PROMPT_CHARS + 50))
        assert "被截断" in project_brief.prompt_section(long)

    app = FastAPI()
    for r in routers:
        app.include_router(r)
    app.dependency_overrides[require_user] = lambda: "u"
    c = TestClient(app)
    before = c.get(f"/api/projects/{pid}").json()
    assert before["brief_by"] == "assistant" and before["brief"].startswith("## 目标"), before
    r = c.patch(f"/api/projects/{pid}", json={"rules": "用中文"}).json()
    assert r["brief_by"] == "assistant" and r["brief_updated_at"] == before["brief_updated_at"], r
    r = c.patch(f"/api/projects/{pid}", json={"brief": before["brief"] + "\n"}).json()   # 只差空白 = 没改
    assert r["brief_by"] == "assistant", r
    r = c.patch(f"/api/projects/{pid}", json={"brief": "  ## 目标\n找实习  "}).json()
    assert r["brief"] == "## 目标\n找实习" and r["brief_by"] == "user" and r["brief_updated_at"] != before["brief_updated_at"], r
    assert c.patch(f"/api/projects/{pid}", json={"brief": "x" * (project_brief.BRIEF_MAX + 1)}).status_code == 422
    assert c.post("/api/projects", json={"name": "新"}).json()["brief"] == ""
    print("ok smoke_project_brief")

asyncio.run(main())
