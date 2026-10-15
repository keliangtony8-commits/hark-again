# 冒烟：v0.93 建议卡直达 App 某一页（offer_on_home open，app/card_targets.py，迁移 0022 target 列加宽）。无模型调用。
# - open=connectors 且不写 prompt → 卡只有去处（没有“去做”），工具说明“用户自己去那页处理”；
# - open=task:<id> → target=tasks + task_id；不存在的任务 / 项目 / 不认识的名字 → 拒绝（中文原因），不建卡；
# - open=project:<id> + prompt → target=project:<id>（> 32 字也存得下）；点“去做”开的对话在这个项目里；项目删了再点 → 放回主聊天；
# - 既没 prompt 也没 open → 拒绝；同标题重新提议没给 open → 清掉；manage_home list 标“直达 …”；接口 target > 64 → 422。
# 运行：python tests/smoke_offer_target.py
import os, sys, asyncio, subprocess, tempfile
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.auth import require_user
from app.db import SessionLocal
from app.models import Conversation, Project, ScheduledTask
from app.routes import home
from app.routes.resources import routers

load_builtin()
schema = REGISTRY["offer_on_home"].parameters
assert "open" in schema["properties"] and schema["required"] == ["title"], schema
app = FastAPI()
for r in [*routers, home.router]:
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)

async def call(name, **kw):
    async with SessionLocal() as db:
        return (await REGISTRY[name].run(ToolContext(db=db), **kw)).content
cards = lambda: {x["title"]: x for x in c.get("/api/cards").json() if x["kind"] == "action" and not x["dismissed"]}

async def seed():
    async with SessionLocal() as db:
        p = Project(name="毕业论文"); t = ScheduledTask(name="早报", prompt="今天的新闻", cron="0 8 * * *")
        db.add_all([p, t]); await db.commit(); return p.id, t.id
pid, tid = asyncio.run(seed())

# 1) 只有去处
out = asyncio.run(call("offer_on_home", title="GitHub 连接失效了", reason="昨晚起读不到仓库。", open="connectors"))
assert "没有“去做”按钮" in out and "直达：connectors" in out, out
k = cards()["GitHub 连接失效了"]
assert k["target"] == "connectors" and k["action_prompt"] is None and k["origin"] == "agent", k
assert c.post(f"/api/cards/{k['id']}/start").status_code == 404  # 没有指令就没有“开始做”

# 2) 任务详情
out = asyncio.run(call("offer_on_home", title="早报改个时间", prompt="把早报改到 7 点", open=f"task:{tid}"))
k = cards()["早报改个时间"]
assert k["target"] == "tasks" and k["task_id"] == tid and k["action_prompt"], k
assert f"直达：task:{tid}" in out

# 3) 拒绝
for bad, why in [("task:nope", "没有 id=nope 的定时任务"), ("project:nope", "没有 id=nope 的项目"), ("settings", "不认识的去处"), ("memory:x", "不认识的去处"), ("vault", "不认识的去处")]:  # v2.96 保险箱并进连接的账号
    out = asyncio.run(call("offer_on_home", title="坏去处", prompt="x", open=bad))
    assert why in out and "open 只能是" in out, (bad, out)
assert "坏去处" not in cards()
out = asyncio.run(call("offer_on_home", title="什么都没有"))
assert "要写 prompt" in out and "什么都没有" not in cards(), out

# 4) 项目：对话开在项目里
out = asyncio.run(call("offer_on_home", title="论文第三章", prompt="帮我列第三章提纲", label="列提纲", open=f"project:{pid}"))
k = cards()["论文第三章"]
assert k["target"] == f"project:{pid}" and len(k["target"]) > 32, k
r = c.post(f"/api/cards/{k['id']}/start").json()
assert r["started"] is True
async def conv(cid):
    async with SessionLocal() as db:
        return (await db.get(Conversation, cid)).project_id
assert asyncio.run(conv(r["conversation_id"])) == pid
listing = asyncio.run(call("manage_home", action="list"))
assert f"直达 project:{pid}" in listing and "直达 connectors" in listing and f"直达 task:{tid}" in listing, listing
assert "「GitHub 连接失效了」 · 你提议的 · 直达" in listing, listing  # 没有按钮字

# 5) 项目删了 → 重新提议后点，对话放回主聊天
async def drop():
    async with SessionLocal() as db:
        await db.delete(await db.get(Project, pid)); await db.commit()
asyncio.run(drop())
async def offer_raw():
    from app import home_offers
    async with SessionLocal() as db:
        card, _, _ = await home_offers.offer(db, "论文第三章", "", "帮我列第三章提纲", target=f"project:{pid}")
        return card.id
kid = asyncio.run(offer_raw())
r = c.post(f"/api/cards/{kid}/start").json()
assert r["started"] and asyncio.run(conv(r["conversation_id"])) is None

# 6) 同标题重新提议没给 open → 清掉
asyncio.run(call("offer_on_home", title="早报改个时间", prompt="把早报改到 7 点"))
k = cards()["早报改个时间"]
assert k["target"] is None and k["task_id"] is None, k

# 7) 接口
assert c.post("/api/cards", json={"kind": "action", "title": "t", "target": "x" * 65}).status_code == 422
assert c.post("/api/cards", json={"kind": "action", "title": "t", "target": f"project:{'a' * 32}"}).status_code in (200, 201)
print("smoke_offer_target OK")
