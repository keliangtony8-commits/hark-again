# 冒烟：定时任务 / 面板碰壁（app/task_wall.py，模拟模型，不打真接口）+ manage_home read / runs / refresh 等结果。
# 规则：parse 规整大小写、坏格式中文提示；label / fixable / open_page；不在运行里报壁被拒。
# 面板第一次成功 → 内容；第二次运行里 report_wall needs_login → 运行 error=“需要登录 …：经过”、run.wall、任务 wall_label/
# wall_fixable/wall_open=vault，面板保留上一次内容（不刷成“登录不了”），失败卡标题“需要你处理”；brief 带“上一次碰壁”；
# 第三次正常 → 壁清掉、卡收起；报告任务 blocked:captcha → 不可修、照常交付报告；连续碰壁 3 次 → 自动暂停；
# manage_home read 带状态与内容、runs 带“碰壁”、refresh 在后台 worker 跑完后带回新内容 / 碰壁原因；迁移 0050 往返。
# 运行：python tests/smoke_task_wall.py
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
from app import task_wall, worker
from app.agent.tools import ToolContext, load_builtin, REGISTRY
from app.auth import require_user
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import HomeCard, ScheduledTask
from app.routes import tasks as rt
from app.routes.resources import routers

load_builtin()
from app.agent.builtin.tasks import schedule_task
import app.agent.builtin.home as home_tool

# —— 纯规则 ——
assert task_wall.parse(" Needs_Login:JW.Example.EDU ") == ("needs_login", "jw.example.edu")
for bad in ("", "needs_login", "login:x.com", "needs_login:", "blocked:有 空格", "paywall:" + "a" * 65):
    try:
        task_wall.parse(bad); raise SystemExit(f"should reject {bad!r}")
    except ValueError as e:
        assert "needs_login" in str(e)
assert task_wall.label("needs_connector:github") == "需要重新连接 github"
assert task_wall.fixable("paywall:nyt.com") and not task_wall.fixable("blocked:captcha") and not task_wall.fixable(None)
assert task_wall.open_page("needs_login:x.com") == "vault" and task_wall.open_page("needs_connector:github") == "connectors"
assert task_wall.open_page("source_gone:x.com") is None and task_wall.label("weird") == "weird"

seen, script = [], {"v": None}

class Reply:
    def __init__(self, text): self.blocks = text_to_blocks(text)

async def fake_run_turn(db, conv, emit=None, task_id=None, brief=None, **kw):
    seen.append(brief)
    step = script["v"]
    return await step(db, task_id) if callable(step) else Reply(step)
worker.run_turn = fake_run_turn

app = FastAPI()
for r in [rt.router, *routers]:
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
task = lambda tid: c.get(f"/api/tasks/{tid}").json()
runs = lambda tid: c.get(f"/api/tasks/{tid}/runs").json()
cards = lambda tid, kind: [x for x in c.get("/api/cards").json() if x["task_id"] == tid and x["kind"] == kind and not x["dismissed"]]

async def seed(name, output):
    async with SessionLocal() as db:
        t = ScheduledTask(name=name, prompt="查教务系统成绩", cron="0 8 * * *", output=output,
                          created_at=datetime.now(timezone.utc) - timedelta(days=2))
        db.add(t); await db.flush()
        if output == "panel":
            db.add(HomeCard(kind="panel", title=name, task_id=t.id, blocks=[]))
        await db.commit()
        return t.id

def run(tid, step):
    script["v"] = step
    asyncio.run(worker.run_task(tid))

def walls(wall, text, reply):
    async def step(db, task_id):
        out = (await schedule_task(ToolContext(db=db, task_id=task_id), action="report_wall", wall=wall, text=text)).content
        assert "已记下碰壁" in out, out
        return Reply(reply)
    return step

pid = asyncio.run(seed("成绩面板", "panel"))

# 不在运行里：拒绝（聊天里 / 别的任务）
async def outside():
    async with SessionLocal() as db:
        a = (await schedule_task(ToolContext(db=db), action="report_wall", id=pid, wall="needs_login:x.com")).content
        b = (await schedule_task(ToolContext(db=db, task_id=pid), action="report_wall", wall="needs_login:x.com")).content
        return a, b
a, b = asyncio.run(outside())
assert "自己的运行" in a and "现在它没有在跑" in b, (a, b)

# 1) 成功 → 面板有内容
run(pid, "高数 92 · 线代 88")
panel = cards(pid, "panel")[0]
assert "高数 92" in panel["blocks"][0]["text"]
assert task(pid)["wall_label"] is None and "report_wall" in seen[-1] and "上一次碰壁" not in seen[-1]

# 2) 碰壁：要登录
async def bad_format(db, task_id):
    out = (await schedule_task(ToolContext(db=db, task_id=task_id), action="report_wall", wall="login")).content
    assert "needs_login" in out, out
    return await walls("needs_login:JW.example.edu", "登录页要学号密码，保险箱里没有", "我登录不了教务系统")(db, task_id)
run(pid, bad_format)
r = runs(pid)[0]
assert r["status"] == "error" and r["wall"] == "needs_login:jw.example.edu" and r["wall_label"] == "需要登录 jw.example.edu", r
assert r["error"] == "需要登录 jw.example.edu：登录页要学号密码，保险箱里没有", r
t = task(pid)
assert t["wall"] == "needs_login:jw.example.edu" and t["wall_fixable"] is True and t["wall_open"] == "vault", t
assert "高数 92" in cards(pid, "panel")[0]["blocks"][0]["text"]  # 保留上一次内容
alert = [x for x in c.get("/api/cards").json() if x["kind"] == "action" and x["task_id"] == pid and not x["dismissed"]]
assert len(alert) == 1 and "需要你处理" in alert[0]["title"] and "立即运行" in alert[0]["blocks"][0]["text"], alert

# manage_home read / runs
async def mh(**kw):
    async with SessionLocal() as db:
        return (await REGISTRY["manage_home"].run(ToolContext(db=db), **kw)).content
listing = asyncio.run(mh(action="list"))
assert "碰壁：需要登录 jw.example.edu" in listing, listing
out = asyncio.run(mh(action="read", id=panel["id"]))
assert "高数 92" in out and "碰壁（要用户处理）" in out and "失败（连续 1 次）" in out and "查教务系统成绩" in out, out
out = asyncio.run(mh(action="runs", id=panel["id"]))
assert out.count("\n") == 1 and "碰壁：需要登录" in out and "成功" in out, out

# 3) 再跑：brief 带上一次碰壁；这次好了 → 清壁、收卡
run(pid, "高数 95 · 线代 88")
assert "上一次碰壁：需要登录 jw.example.edu" in seen[-1], seen[-1]
t = task(pid)
assert t["wall"] is None and t["wall_label"] is None and t["fail_streak"] == 0, t
assert "高数 95" in cards(pid, "panel")[0]["blocks"][0]["text"]
assert not [x for x in c.get("/api/cards").json() if x["kind"] == "action" and x["task_id"] == pid and not x["dismissed"]]

# 4) 报告任务暂时被挡：不可修，照常交付报告
rid = asyncio.run(seed("成绩早报", "report"))
run(rid, walls("blocked:captcha", "出了验证码", "上次的成绩：高数 95（这次被验证码挡住，没刷新）"))
t = task(rid)
assert t["wall_label"] == "暂时被挡住（captcha），之后会再试" and t["wall_fixable"] is False and t["wall_open"] is None, t
assert len(cards(rid, "report")) == 1 and "验证码" in cards(rid, "report")[0]["blocks"][0]["text"]
alert = [x for x in c.get("/api/cards").json() if x["kind"] == "action" and x["task_id"] == rid and not x["dismissed"]]
assert len(alert) == 1 and "没跑成功" in alert[0]["title"], alert

# 5) 连续碰壁 3 次 → 自动暂停
for _ in range(2):
    run(rid, walls("blocked:captcha", "又是验证码", "没刷新"))
t = task(rid)
assert t["active"] is False and t["paused_reason"] == "failures" and t["fail_streak"] == 3, t

# 6) refresh 等结果：后台 worker 领走跑完（成功 / 碰壁）
home_tool.REFRESH_WAIT, home_tool.REFRESH_POLL = 10, 0.05
async def refresh_with_worker(step):
    script["v"] = step
    async def fake_worker():
        for _ in range(100):
            async with SessionLocal() as db:
                if (await db.get(ScheduledTask, pid)).run_requested:
                    break
            await asyncio.sleep(0.02)
        await worker.run_task(pid)
    out, _ = await asyncio.gather(mh(action="refresh", id=panel["id"]), fake_worker())
    return out
out = asyncio.run(refresh_with_worker("高数 99 · 线代 90"))
assert "刷新好了" in out and "高数 99" in out, out
out = asyncio.run(refresh_with_worker(walls("needs_connector:github", "授权过期", "x")))
assert "这次刷新碰壁：需要重新连接 github：授权过期" in out and "高数 99" in cards(pid, "panel")[0]["blocks"][0]["text"], out
assert task(pid)["wall_open"] == "connectors"

# 迁移往返
subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0049"], cwd=root, check=True, capture_output=True)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)
print("smoke_task_wall OK")
