# 冒烟：技能启用/停用（POST /api/catalog/skills/{id}/enable|disable）。无模型调用、无迁移（开关存 data/skills/_disabled.json）。
# 默认全启用；停用后仍在列表里（enabled=False、位置不变）但不进系统提示的技能目录、use_skill 拒绝；
# 开关按 id 记：自定义/恢复默认不丢；启用后恢复；未知 id 404；删除用户技能顺手清开关，新建同 id 不继承；
# _disabled.json 损坏当作全启用；重复停用幂等。
# 运行：python tests/smoke_skill_toggle.py
import os, sys, asyncio, subprocess, tempfile
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp)
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import memory_store, skills_store
from app.auth import require_user
from app.db import SessionLocal
from app.routes import catalog
from app.agent import context
from app.agent.builtin import skills as tool_skills
from app.agent.tools import ToolContext

async def no_mems(db, q): return []
memory_store.relevant = no_mems

app = FastAPI(); app.include_router(catalog.router)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
P = "/api/catalog/skills"
ctx = ToolContext(db=None)

def prompt() -> str:
    async def go():
        async with SessionLocal() as db:
            return await context.build_system_prompt(db, None, "")
    return asyncio.run(go())

def use(sid): return asyncio.run(tool_skills.use_skill(ctx, id=sid)).content

base = c.get(P).json()
ids = [s["id"] for s in base]
assert all(s["enabled"] for s in base), base
assert "- writing：" in prompt()

# 停用内置
off = c.post(f"{P}/writing/disable").json()
assert off["enabled"] is False and off["builtin"], off
assert c.post(f"{P}/writing/disable").json()["enabled"] is False  # 幂等
lst = c.get(P).json()
assert [s["id"] for s in lst] == ids, "停用的还在原位"
assert "- writing：" not in prompt() and "- web-research：" in prompt()
assert "停用" in use("writing") and "停用" not in use("web-research")

# 自定义 / 恢复默认 都不丢开关
assert c.post(f"{P}/writing/customize").json()["enabled"] is False
assert c.post(f"{P}/writing/reset").json()["enabled"] is False

# 启用
on = c.post(f"{P}/writing/enable").json()
assert on["enabled"] is True and "- writing：" in prompt() and use("writing").startswith("# ")
assert c.get(P).json() == base

# 未知 id
for a in ("enable", "disable"):
    assert c.post(f"{P}/ghost/{a}").status_code == 404

# 用户技能：删除清开关，新建同 id 不继承
mine = c.post(P, json={"name": "Mine", "description": "d", "body": "b"}).json()
assert mine["enabled"] and c.post(f"{P}/mine/disable").json()["enabled"] is False
assert "- mine：" not in prompt()
c.delete(f"{P}/mine")
again = c.post(P, json={"name": "Mine", "description": "d", "body": "b"}).json()
assert again["id"] == "mine" and again["enabled"], again

# 损坏的开关文件 = 全启用
(skills_store.SKILLS / skills_store.DISABLED).write_text("{oops", encoding="utf-8")
assert all(s["enabled"] for s in c.get(P).json())
print("smoke_skill_toggle OK")
