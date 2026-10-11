# 冒烟：技能库“复制内置来改 / 恢复默认”（/api/catalog/skills）。无模型调用、无数据库表（技能是文件，无迁移）。
# 内置只读（PUT/DELETE 400）；customize → 同 id 自定义版顶替内置、位置不变、目录只出现一次、可 PUT；
# 重复 customize 不覆盖已改内容；reset → 回到内置原文；用户技能 DELETE 正常、不存在 404；
# 新建同名不覆盖已有、不顶替内置（id 加后缀）；智能体 save_skill 传 id 改内置 = 自动生成自定义版；路径穿越 404。
# 运行：python tests/smoke_skills.py
import os, sys, asyncio, tempfile
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import skills_store
from app.auth import require_user
from app.routes import catalog
from app.agent.builtin import skills as tool_skills
from app.agent.tools import ToolContext

app = FastAPI(); app.include_router(catalog.router)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
P = "/api/catalog/skills"

base = c.get(P).json()
ids = [s["id"] for s in base]
assert all(s["builtin"] and s["customized"] is False for s in base), base
assert "writing" in ids and "web-research" in ids
orig = next(s for s in base if s["id"] == "writing")

# 内置只读
assert c.put(f"{P}/writing", json={"name": "x", "description": "y"}).status_code == 400
assert c.delete(f"{P}/writing").status_code == 400
assert c.post(f"{P}/writing/reset").json() == orig  # 没自定义过 reset = 原样

# 复制一份来改
cu = c.post(f"{P}/writing/customize").json()
assert cu == {**orig, "builtin": False, "customized": True}, cu
lst = c.get(P).json()
assert [s["id"] for s in lst] == ids, "位置不变、只出现一次"
r = c.put(f"{P}/writing", json={"name": "写作（我的）", "description": "我的写作口味", "body": "1. 短句"}).json()
assert r["name"] == "写作（我的）" and r["customized"] and not r["builtin"], r
assert c.post(f"{P}/writing/customize").json()["body"] == "1. 短句", "重复 customize 不覆盖"
assert skills_store.get_skill("writing").body == "1. 短句"  # 模型读到的是自定义版
assert c.delete(f"{P}/writing").status_code == 400, "自定义版走 reset，不能 DELETE"

# 恢复默认
assert c.post(f"{P}/writing/reset").json() == orig
assert c.get(P).json() == base

# 用户技能：新建不覆盖、不顶替
a = c.post(P, json={"name": "Writing", "description": "d1", "body": "b1"}).json()
assert a["id"] == "writing-2" and not a["customized"], a
b = c.post(P, json={"name": "Writing", "description": "d2", "body": "b2"}).json()
assert b["id"] == "writing-3", b
assert skills_store.get_skill("writing").builtin
assert [s["id"] for s in c.get(P).json()][-2:] == ["writing-2", "writing-3"], "用户技能排在内置后"
assert c.delete(f"{P}/writing-2").json() == {"ok": True}
assert c.delete(f"{P}/writing-2").status_code == 404
assert c.put(f"{P}/nope", json={"name": "x", "description": "y"}).status_code == 404
for bad in ["nope/customize", "nope/reset", "..%2Fwriting/customize"]:
    assert c.post(f"{P}/{bad}").status_code == 404, bad
assert skills_store.customize.__doc__ and skills_store._builtin_path("../skills/writing") is None

# 智能体：传 id 改内置 → 自动复制成自定义版；新建同名不覆盖；未知 id 报错不写
ctx = ToolContext(db=None)
res = asyncio.run(tool_skills.save_skill(ctx, name="调研", description="我的调研法", body="先查中文源", id="web-research"))
assert "自定义版" in res.content, res.content
w = skills_store.get_skill("web-research")
assert w.customized and w.body == "先查中文源"
res = asyncio.run(tool_skills.save_skill(ctx, name="Writing", description="d", body="b"))
assert "writing-2" in res.content, res.content
res = asyncio.run(tool_skills.save_skill(ctx, name="x", description="d", body="b", id="ghost"))
assert "没有" in res.content and skills_store.get_skill("ghost") is None
print("smoke_skills OK")
