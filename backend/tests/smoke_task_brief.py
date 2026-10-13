# 冒烟：定时任务的“做法 + 观察 + 最近几次 + 没事别出声 + 跳过下一次”（app/task_brief.py，模拟模型，不打真接口）。
# 第一次运行：brief 写“还没有做法”，工具 set_runbook / note（id 省略 = 自己）写进任务；第二次 brief 带做法、观察、上次结果；
# 回复 [[SILENT]] → 不进收件箱、运行记录 silent_reason、对话保留；正文中间的记号不算；面板任务不静默；失败不静默；
# 超长 → 中文原因不写入；PATCH 清空 / 超长 422；skip_next → next_run_at 推后一天、skipped_at、再跳一次、unskip；
# 改 cron 清掉跳过；一次性 / 暂停不能跳；工具 runs / run_now / list；迁移 0049 往返。
# 运行：python tests/smoke_task_brief.py
import os, sys, asyncio, subprocess, tempfile
from datetime import datetime, timedelta, timezone
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import schedule, task_brief, worker
from app.agent.tools import ToolContext, load_builtin, REGISTRY
from app.auth import require_user
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import ScheduledTask
from app.routes import tasks as rt
from app.routes.resources import routers

load_builtin()
from app.agent.builtin.tasks import schedule_task as tool

seen = []        # 每次运行拿到的 brief
script = {"v": None}

class Reply:
    def __init__(self, text): self.blocks = text_to_blocks(text)

async def fake_run_turn(db, conv, emit=None, task_id=None, brief=None, **kw):  # 模拟模型：可在运行里调工具
    seen.append(brief)
    step = script["v"]
    if callable(step):
        return await step(db, task_id, emit)
    return Reply(step)
worker.run_turn = fake_run_turn

app = FastAPI()
for r in [rt.router, *routers]:
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)

def task(tid):
    return next(x for x in c.get("/api/tasks").json() if x["id"] == tid)

def reports(tid):
    return [x for x in c.get("/api/cards").json() if x["task_id"] == tid and x["kind"] == "report" and not x["dismissed"]]

def runs(tid):
    return c.get(f"/api/tasks/{tid}/runs").json()

async def seed(name, output="report", cron="0 8 * * *"):
    async with SessionLocal() as db:
        t = ScheduledTask(name=name, prompt="看看机票价格", cron=cron, output=output,
                          created_at=datetime.now(timezone.utc) - timedelta(days=2))
        db.add(t); await db.commit()
        return t.id

async def call(task_id, **args):
    async with SessionLocal() as db:
        return (await tool(ToolContext(db=db, task_id=task_id), **args)).content

def run(tid, step):
    script["v"] = step
    asyncio.run(worker.run_task(tid))

tid = asyncio.run(seed("机票盯价"))

# 1) 第一次运行：没有做法 → brief 让它写；运行里写做法 + 观察（id 省略）
async def first(db, task_id, emit):
    from app.agent.builtin.tasks import schedule_task
    r1 = (await schedule_task(ToolContext(db=db, task_id=task_id), action="set_runbook", text="  1. 打开 example.com/fares\n2. 记最低价  ")).content
    r2 = (await schedule_task(ToolContext(db=db, task_id=task_id), action="note", text="网站周末很慢")).content
    assert "已记下" in r1 and "做法" in r1 and "观察" in r2, (r1, r2)
    return Reply("最低价 ¥820，比上周低 ¥60")
run(tid, first)
b = seen[-1]
assert "还没有做法" in b and "set_runbook" in b and "[[SILENT]]" in b and "最近几次" not in b, b
assert "以指令为准" in b and "机票盯价" in b
t = task(tid)
assert t["runbook"] == "1. 打开 example.com/fares\n2. 记最低价" and t["note"] == "网站周末很慢", t
assert len(reports(tid)) == 1 and runs(tid)[0]["silent_reason"] is None

# 2) 第二次：brief 带做法、观察、上次结果；回复静默 → 不发卡、记原因、对话保留
run(tid, "[[SILENT]]：价格没变，还是 ¥820")
b = seen[-1]
assert "example.com/fares" in b and "网站周末很慢" in b and "成功，已告诉用户" in b and "还没有做法" not in b, b
r = runs(tid)[0]
assert r["status"] == "ok" and r["silent_reason"] == "价格没变，还是 ¥820" and r["conversation_id"], r
[card] = reports(tid)
assert "820" in card["blocks"][0]["text"] and "SILENT" not in card["blocks"][0]["text"], "旧报告不被静默运行收起"
assert task(tid)["last_status"] == "ok"

# 3) 下一次 brief 里能看到“没打扰用户：原因”；空原因 → 默认；正文中间的记号不算静默
run(tid, "[[SILENT]]")
assert "没打扰用户：价格没变" in seen[-1], seen[-1]
assert runs(tid)[0]["silent_reason"] == task_brief.SILENT_DEFAULT
run(tid, "降价了！注意：上次回的是 [[SILENT]]")
assert runs(tid)[0]["silent_reason"] is None and "降价了" in reports(tid)[0]["blocks"][0]["text"]

# 4) 失败不算静默；面板任务不静默、brief 不提静默
async def boom(db, task_id, emit):
    await emit({"type": "error", "message": "模型 401"}); return None
run(tid, boom)
assert runs(tid)[0]["status"] == "error" and runs(tid)[0]["silent_reason"] is None
pid = asyncio.run(seed("汇率面板", output="panel", cron="0 * * * *"))
run(pid, "[[SILENT]] 没变")
assert "[[SILENT]]" not in seen[-1] and runs(pid)[0]["silent_reason"] is None

# 5) 超长 → 原因、不写入；PATCH 清空、超长 422、空白 → null
out = asyncio.run(call(tid, action="note", text="x" * (task_brief.NOTE_MAX + 1)))
assert "超过上限" in out and task(tid)["note"] == "网站周末很慢", out
assert "需要 text" in asyncio.run(call(tid, action="note"))
assert c.patch(f"/api/tasks/{tid}", json={"runbook": "y" * (task_brief.RUNBOOK_MAX + 1)}).status_code == 422
assert c.patch(f"/api/tasks/{tid}", json={"note": "   "}).json()["note"] is None
assert asyncio.run(call(None, action="note", text="x")).startswith("没找到"), "聊天里（无 task_id）必须给 id"
assert "清空" in asyncio.run(call(None, action="set_runbook", id=tid, text=""))
assert task(tid)["runbook"] is None

# 6) 跳过下一次：next_run_at 推后一天，skipped_at = 原来那次；再跳 = 再推一天；撤销恢复
before = task(tid)["next_run_at"]
r = c.post(f"/api/tasks/{tid}/skip").json()
t = task(tid)
assert r["skipped_at"] == before.replace("Z", "+00:00") or r["skipped_at"][:16] == before[:16], (r, before)
nb, na = datetime.fromisoformat(before), datetime.fromisoformat(t["next_run_at"])
assert na - nb == timedelta(days=1) and t["skipped_at"], (before, t)
out = asyncio.run(call(None, action="skip_next", id=tid))
assert "已跳过" in out and datetime.fromisoformat(task(tid)["next_run_at"]) - nb == timedelta(days=2), out
assert "跳过" in asyncio.run(call(None, action="list"))
assert c.delete(f"/api/tasks/{tid}/skip").json()["skipped_at"] is None
assert task(tid)["next_run_at"][:16] == before[:16]
assert "没有待跳过" in asyncio.run(call(None, action="unskip", id=tid))
# 改计划清掉跳过
c.post(f"/api/tasks/{tid}/skip")
assert task(tid)["skipped_at"]
c.patch(f"/api/tasks/{tid}", json={"cron": "30 9 * * *"})
assert task(tid)["skipped_at"] is None
# 一次性 / 暂停不能跳
once = c.post("/api/tasks", json={"name": "提醒", "prompt": "提醒我：交作业", "run_at": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()}).json()
assert c.post(f"/api/tasks/{once['id']}/skip").status_code == 422
c.patch(f"/api/tasks/{tid}", json={"active": False})
assert "暂停" in asyncio.run(call(None, action="skip_next", id=tid))
c.patch(f"/api/tasks/{tid}", json={"active": True})
assert c.post("/api/tasks/nope/skip").status_code == 404

# 7) 工具 runs / run_now
out = asyncio.run(call(None, action="runs", id=tid))
assert "失败：模型 401" in out and "没打扰用户" in out and "成功，已告诉用户" in out, out
assert "已排队" in asyncio.run(call(None, action="run_now", id=tid)) and task(tid)["run_requested"]
assert "不能在运行里" in asyncio.run(call(tid, action="run_now", id=tid))
assert "已记下观察" not in asyncio.run(call(None, action="list"))  # 观察已清空

# 8) 迁移往返
subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0048"], cwd=root, check=True, capture_output=True)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)
print("smoke_task_brief OK")
