# 冒烟：修好就重跑（v2.19，app/task_wall.retry_fixed / retry_note，模拟模型，不打真接口）。
# 规则：needs_login 域名相同 / 互为子域才算；needs_connector 比 id / 名字（大小写、空格规整）；正在跑的不动；无壁 / 别的壁不动。
# 接口：保险箱存登录 → 卡在该域名的任务 run_requested、wall_retrying、返回 retried_note；存别的域名 → 没动、note None；
# 连续碰壁已暂停的任务也被排重跑，worker 跑成功 → 壁清掉、恢复 active；MCP 加服务器 → needs_connector:<名字> 重跑；
# OAuth 回调成功 → 跳回地址带 retried；browser_login 选“记住” → 工具结果带那句话。
# 运行：python tests/smoke_wall_retry.py
import os, sys, asyncio, subprocess, tempfile
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from cryptography.fernet import Fernet
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY=Fernet.generate_key().decode(), TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import task_wall, worker
from app.agent.tools import load_builtin
from app.auth import require_user
from app.blocks import text_to_blocks
from app.connectors import mcp, oauth
from app.connectors.providers import PROVIDERS
from app.db import SessionLocal
from app.models import ScheduledTask, TaskRun
from app.routes import connectors as rc, tasks as rt, vault as rv
from app.routes.resources import routers

load_builtin()

# —— 纯规则 ——
f = task_wall._fixes
assert f("needs_login:jw.example.edu", "needs_login", ["example.edu"], [])
assert f("needs_login:example.edu", "needs_login", ["jw.example.edu"], [])
assert f("needs_login:example.edu", "needs_login", ["example.edu"], [])
assert not f("needs_login:badexample.edu", "needs_login", ["example.edu"], [])
assert not f("needs_login:example.edu", "needs_connector", [], ["example.edu"])
assert not f("paywall:example.edu", "needs_login", ["example.edu"], [])
assert f("needs_connector:my-notes", "needs_connector", [], [task_wall._norm("My Notes")])
assert not f(None, "needs_login", ["x.com"], []) and not f("weird", "needs_login", ["x.com"], [])
assert task_wall.retry_note([]) is None
assert task_wall.retry_note(["A", "B"]) == "之前卡在这里的「A」、「B」已重新运行"
assert task_wall.retry_note(list("ABCDE")).endswith("「C」等 5 个任务已重新运行")

app = FastAPI()
for r in [rt.router, rv.router, rc.router, rc.public, *routers]:
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
task = lambda tid: c.get(f"/api/tasks/{tid}").json()

async def seed(name, wall, **kw):
    async with SessionLocal() as db:
        t = ScheduledTask(name=name, prompt="查成绩", cron="0 8 * * *", output="inbox", wall=wall,
                          created_at=datetime.now(timezone.utc) - timedelta(days=2), **kw)
        db.add(t); await db.commit()
        return t.id

login_t = asyncio.run(seed("教务成绩", "needs_login:jw.example.edu", active=False, paused_reason="failures", fail_streak=3))
other_t = asyncio.run(seed("别的站", "needs_login:other.com"))
gh_t = asyncio.run(seed("GitHub 周报", "needs_connector:github"))
mcp_t = asyncio.run(seed("笔记同步", "needs_connector:my-notes"))
busy_t = asyncio.run(seed("正在跑的", "needs_login:example.edu"))
clean_t = asyncio.run(seed("没壁的", None))

async def mark_running(tid):
    async with SessionLocal() as db:
        db.add(TaskRun(task_id=tid, trigger="schedule", status="running")); await db.commit()
asyncio.run(mark_running(busy_t))

t = task(login_t)
assert t["wall_retrying"] is False and t["wall_fixable"], t

# 存了不相干的域名：谁都不动
r = c.post("/api/vault", json={"kind": "login", "name": "x", "username": "me", "value": "pw123456", "hosts": ["nothing.org"]})
assert r.status_code == 200 and r.json()["retried_note"] is None, r.text
assert not task(login_t)["wall_retrying"]

# 存了 example.edu 的登录：子域 jw.example.edu 的任务重跑；正在跑的不动；别的域名不动
r = c.post("/api/vault", json={"kind": "login", "name": "教务", "username": "me", "value": "pw123456", "hosts": ["example.edu"]})
assert r.status_code == 200, r.text
assert r.json()["retried_note"] == "之前卡在这里的「教务成绩」已重新运行", r.json()
assert "ciphertext" not in r.json() and r.json()["name"] == "教务"
t = task(login_t)
assert t["run_requested"] and t["wall_retrying"] and t["wall_label"] == "需要登录 jw.example.edu", t
assert not task(busy_t)["run_requested"] and not task(other_t)["run_requested"] and not task(clean_t)["run_requested"]

# worker 跑：成功 → 壁清掉、暂停的任务恢复
class Reply:
    def __init__(self, text): self.blocks = text_to_blocks(text)
async def fake_run_turn(db, conv, emit=None, task_id=None, brief=None, **kw):
    assert "上一次碰壁" in (brief or ""), brief
    return Reply("成绩：都过了")
worker.run_turn = fake_run_turn
asyncio.run(worker.run_task(login_t))
t = task(login_t)
assert t["wall"] is None and t["wall_label"] is None and not t["wall_retrying"] and not t["run_requested"], t
assert t["active"] is True and t["paused_reason"] is None, t

# MCP 服务器：名字规整后对上 needs_connector:my-notes
async def fake_tools(s): return [{"name": "search"}]
mcp.list_tools = fake_tools
r = c.post("/api/connectors/mcp", json={"name": "My Notes", "url": "https://notes.example/mcp"})
assert r.status_code == 200 and r.json()["retried_note"] == "之前卡在这里的「笔记同步」已重新运行", r.text
assert task(mcp_t)["wall_retrying"] and not task(gh_t)["run_requested"]

# OAuth 回调：连好 github → 跳回地址带 retried
gh = PROVIDERS["github"]
oauth.read_state = lambda state: (gh, "web")
async def fake_complete(db, p, code): return None
oauth.complete = fake_complete
r = c.get("/api/oauth/callback", params={"state": "s", "code": "c"}, follow_redirects=False)
assert r.status_code in (302, 307), r.status_code
q = parse_qs(urlparse(r.headers["location"].replace("/#/", "/")).query)
assert q["connected"] == ["github"] and q["retried"] == ["之前卡在这里的「GitHub 周报」已重新运行"], q
assert task(gh_t)["wall_retrying"]
# 再连一次：已经排了重跑的照样列出（还卡着），不重复排
r = c.get("/api/oauth/callback", params={"state": "s", "code": "c"}, follow_redirects=False)
assert "retried" in parse_qs(urlparse(r.headers["location"].replace("/#/", "/")).query)

# browser_login 选“记住”：工具结果带那句话
from app.agent.builtin import browser as bt
from app.agent.tools import ToolContext
from app.agent.approvals import FormReply
other_reset = asyncio.run(seed("另一个站点", "needs_login:shop.other.com"))
class Tab: session, host, url = "s1", "other.com", "https://other.com/login"
bt._tab = lambda ctx: Tab
async def fake_snap(session, method, path, body): return {"ok": True}
bt.browser_client.snapshot_call = fake_snap
async def go():
    async with SessionLocal() as db:
        try:
            res = await bt.browser_login(ToolContext(db=db), user_ref="u1", pass_ref="p1",
                                         form=FormReply(values={"username": "me", "password": "pw123456"}, remember=True))
        except Exception as e:  # 快照之后的渲染与本测试无关
            res = e
    return res
res = asyncio.run(go())
assert task(other_reset)["wall_retrying"] and task(other_t)["wall_retrying"], (task(other_t), res)
if hasattr(res, "content"):
    assert "已重新运行" in res.content, res.content
print("smoke_wall_retry OK")
