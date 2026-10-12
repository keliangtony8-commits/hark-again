# 冒烟：定时任务自己的模型 + 思考强度（scheduled_tasks.model / reasoning，迁移 0035；规则 app/task_store.py）。
# REST 新建带 / 不带；不认识的模型 / 档 → 422；PATCH "" 回默认、null 回默认、只改一项不动另一项；
# worker 每次运行开的对话带上任务的选择（模拟模型记下 conv.model / reasoning），实际发的档按 reasoning.resolve：
# 任务选的档这个模型没有 → 用模型默认；配置里删掉的模型 → llm.chat_model 回落默认；面板任务同样；迁移 down/up。
# 运行：python tests/smoke_task_model.py
import os, sys, asyncio, subprocess, tempfile, json
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai",
  CHAT_MODELS=json.dumps({"fast": "快速", "smart": "深度"}), DEFAULT_MODEL="fast",
  MODEL_REASONING=json.dumps({"smart": {"levels": ["low", "medium", "high"], "default": "medium"}}))
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import reasoning, worker
from app.auth import require_user
from app.blocks import text_to_blocks
from app.config import settings
from app.llm import chat_model
from app.routes import tasks as rt
from app.routes.resources import routers

seen: list[tuple] = []

class Reply:
    def __init__(self, text): self.blocks = text_to_blocks(text)

async def fake_run_turn(db, conv, emit=None, **kw):  # 模拟模型：记下这次对话用的选择，和 runner 一样解析
    model = chat_model(conv.model)
    seen.append((conv.model, conv.reasoning, model, reasoning.resolve(model, conv.reasoning)))
    return Reply("好了")
worker.run_turn = fake_run_turn

app = FastAPI()
for x in [rt.router, *routers]:
    app.include_router(x)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)

def create(**kw):
    return c.post("/api/tasks", json={"name": "简报", "prompt": "总结新闻", "cron": "0 8 * * *", **kw})

def run(tid):
    asyncio.run(worker.run_task(tid))
    return seen[-1]

# —— 新建 ——
plain = create().json()
assert plain["model"] is None and plain["reasoning"] is None, plain
assert run(plain["id"]) == (None, None, "fast", None)          # 默认模型没配思考档：不发
deep = create(model="smart", reasoning="high")
assert deep.status_code == 200, deep.text
deep = deep.json()
assert deep["model"] == "smart" and deep["reasoning"] == "high"
assert run(deep["id"]) == ("smart", "high", "smart", "high")
assert create(model="turbo").status_code == 422
assert create(reasoning="max").status_code == 422
assert create(model=3).status_code == 422
blank = create(model="", reasoning="").json()                   # "" = 默认，存 null
assert blank["model"] is None and blank["reasoning"] is None
print("ok: create")

# —— 改 ——
tid = deep["id"]
p = c.patch(f"/api/tasks/{tid}", json={"reasoning": "low"}).json()
assert p["model"] == "smart" and p["reasoning"] == "low"        # 只改一项，另一项不动
assert c.patch(f"/api/tasks/{tid}", json={"reasoning": "huge"}).status_code == 422
assert c.patch(f"/api/tasks/{tid}", json={"model": "nope"}).status_code == 422
assert c.get(f"/api/tasks/{tid}").json()["reasoning"] == "low"  # 拒了就没写
p = c.patch(f"/api/tasks/{tid}", json={"reasoning": ""}).json()
assert p["reasoning"] is None
assert run(tid) == ("smart", None, "smart", "medium")           # 回模型默认档
p = c.patch(f"/api/tasks/{tid}", json={"model": None, "reasoning": "minimal"}).json()
assert p["model"] is None and p["reasoning"] == "minimal"
assert run(tid) == (None, "minimal", "fast", None)              # 默认模型不能调：不发
p = c.patch(f"/api/tasks/{tid}", json={"model": "smart"}).json()
assert run(tid) == ("smart", "minimal", "smart", "medium")      # 这个模型没有 minimal：回它的默认
print("ok: patch")

# —— 配置变了：存着的模型被删掉 → 回落默认，任务照跑 ——
settings.chat_models = {"fast": "快速"}
assert run(tid)[2] == "fast"
settings.chat_models = {"fast": "快速", "smart": "深度"}

# —— 面板任务同一规则 ——
panel = create(model="smart", reasoning="high").json()
c.patch(f"/api/tasks/{panel['id']}", json={"name": "天气面板"})
from app.db import SessionLocal
from app.models import ScheduledTask
async def to_panel(i):
    async with SessionLocal() as db:
        t = await db.get(ScheduledTask, i); t.output = "panel"; await db.commit()
asyncio.run(to_panel(panel["id"]))
assert run(panel["id"])[:2] == ("smart", "high")
print("ok: worker")

# —— 迁移 down/up ——
for step in (["downgrade", "0034"], ["upgrade", "head"]):
    r = subprocess.run([sys.executable, "-m", "alembic", *step], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
print("ok: migration")
print("ALL OK")
