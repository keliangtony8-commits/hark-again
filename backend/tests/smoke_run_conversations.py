# 冒烟（v2.75）：定时任务 / 面板 / 定时脚本的运行对话不进对话列表（app/run_conversations.py）。
# 报告任务的运行对话带 task_id、列表里没有、仍能按 id 打开和被搜索；用户接话（ws 新消息）后进列表；
# 任务还在跑时删它 → 409，跑完能删；运行记录被裁掉时还藏着的运行对话跟着删、接过话的留着；
# 删任务连带删藏着的运行对话；定时脚本的交付对话也藏起来；迁移 0062 回填老数据（没接过话的才藏）。
# 运行：python tests/smoke_run_conversations.py
import os, sys, asyncio, sqlite3, subprocess, tempfile
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)

# —— 迁移回填：先升到 0061 塞老数据，再升到 head ——
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "0061"], cwd=root, check=True, capture_output=True)
con = sqlite3.connect(db_path)
now = "2026-10-14 06:00:00"
for cid, title in [("old_report", "日报 · 10月13日"), ("old_talked", "日报 · 10月12日"), ("old_chat", "随便聊"),
                   ("old_card", "脚本 · 10月13日")]:
    con.execute("INSERT INTO conversations (id, title, title_source, pinned, mode, summary, created_at, updated_at) "
                "VALUES (?, ?, 'fixed', 0, 'default', '', ?, ?)", (cid, title, now, now))
for mid, cid, role in [("m1", "old_report", "user"), ("m2", "old_report", "assistant"), ("m3", "old_talked", "user"),
                       ("m4", "old_talked", "assistant"), ("m5", "old_talked", "user"), ("m6", "old_chat", "user")]:
    con.execute("INSERT INTO messages (id, conversation_id, role, blocks, status, steps, trace, search_text, created_at) "
                "VALUES (?, ?, ?, '[]', 'done', '[]', '[]', '', ?)", (mid, cid, role, now))
for rid, cid in [("r1", "old_report"), ("r2", "old_talked")]:
    con.execute("INSERT INTO task_runs (id, task_id, \"trigger\", status, conversation_id, started_at) "
                "VALUES (?, 'T_OLD', 'schedule', 'ok', ?, ?)", (rid, cid, now))
cols = {r[1]: r for r in con.execute("PRAGMA table_info(home_cards)")}
need = {n: (0 if r[2].upper().startswith(("BOOL", "INT")) else ("[]" if "JSON" in r[2].upper() else ""))
        for n, r in cols.items() if r[3] and r[4] is None and n not in ("id",)}
need.update(kind="report", title="脚本", conversation_id="old_card", task_id="T_SCRIPT", created_at=now, updated_at=now)
con.execute(f"INSERT INTO home_cards (id, {', '.join(need)}) VALUES ('hc1', {', '.join('?' * len(need))})", list(need.values()))
con.commit(); con.close()
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)
con = sqlite3.connect(db_path)
marks = dict(con.execute("SELECT id, task_id FROM conversations"))
con.close()
assert marks == {"old_report": "T_OLD", "old_talked": None, "old_chat": None, "old_card": "T_SCRIPT"}, marks

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from app import run_conversations, script_tasks, task_runs, worker
from app.auth import require_user
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, ScheduledTask, TaskRun
from app.routes import conversations as rc, tasks as rt, ws
from app.routes.resources import routers


class Reply:
    def __init__(self, text): self.blocks = text_to_blocks(text)


async def fake_run_turn(db, conv, emit=None, **kw):  # 模拟模型：运行中途看一眼列表（用户 13:58 的场景：跑着时挤进列表）
    seen["during"] = ids()
    return Reply("今天的报告：一切正常")
worker.run_turn = fake_run_turn
seen = {}

app = FastAPI()
for r in [rt.router, rc.router, *routers]:
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)


def ids(**q):
    r = c.get("/api/conversations", params=q)
    assert r.status_code == 200, r.text
    return [x["id"] for x in r.json()]


async def seed(name, output="report", **kw):
    async with SessionLocal() as db:
        t = ScheduledTask(name=name, prompt="做点事", cron="0 8 * * *", output=output, **kw)
        db.add(t); await db.commit()
        return t.id


async def conv_of(cid):
    async with SessionLocal() as db:
        return await db.get(Conversation, cid)


async def count_hidden(tid):
    async with SessionLocal() as db:
        return await db.scalar(select(func.count()).select_from(Conversation).where(Conversation.task_id == tid))


# 老数据：回填过的不在列表，接过话的和普通的在
assert set(ids()) == {"old_talked", "old_chat"}, ids()

# 普通对话照常列出
async def plain():
    async with SessionLocal() as db:
        cv = Conversation(title="我自己的对话"); db.add(cv); await db.commit(); return cv.id
mine = asyncio.run(plain())

# 1) 报告任务：运行中和运行后都不在列表；按 id 能打开；能被搜到
rep = asyncio.run(seed("每日新闻"))
asyncio.run(worker.run_task(rep))
[run1] = c.get(f"/api/tasks/{rep}/runs").json()
cid = run1["conversation_id"]
assert cid and cid not in seen["during"] and cid not in ids() and mine in ids(), (cid, seen, ids())
assert asyncio.run(conv_of(cid)).task_id == rep
assert c.get(f"/api/conversations/{cid}").status_code == 200
assert cid in [x["id"] for x in c.get("/api/conversations", params={"q": "每日新闻"}).json()]

# 2) 还在跑时删 → 409（worker 还要往里写，免得撞外键）；跑完能删
async def running(tid):
    async with SessionLocal() as db:
        db.add(TaskRun(task_id=tid, status="running")); await db.commit()
asyncio.run(running(rep))
r = c.delete(f"/api/conversations/{cid}")
assert r.status_code == 409 and "还在跑" in r.json()["detail"], r.text
async def finish_running(tid):
    async with SessionLocal() as db:
        for x in (await db.scalars(select(TaskRun).where(TaskRun.task_id == tid, TaskRun.status == "running"))).all():
            x.status = "ok"
        await db.commit()
asyncio.run(finish_running(rep))
assert c.delete(f"/api/conversations/{cid}").status_code == 200 and asyncio.run(conv_of(cid)) is None
assert c.delete(f"/api/conversations/{mine}").status_code == 200  # 普通对话不受影响

# 3) 用户在运行对话里接话 → 进列表（ws 新消息路径；只跑到交给 _answer 为止）
asyncio.run(worker.run_task(rep))
cid2 = c.get(f"/api/tasks/{rep}/runs").json()[0]["conversation_id"]
assert cid2 not in ids()
async def no_answer(*a, **k): return None
ws._answer = no_answer
events = []
async def emit(ev): events.append(ev)
asyncio.run(ws._handle_user_message(emit, {"conversation_id": cid2, "text": "第二条展开说说"}, asyncio.Event()))
assert events and events[0]["conversation_id"] == cid2
assert cid2 in ids() and asyncio.run(conv_of(cid2)).task_id is None

# 4) 裁运行记录：被裁的那几次还藏着的对话跟着删，接过话的留着
task_runs.KEEP = 2
for _ in range(3):
    asyncio.run(worker.run_task(rep))
kept = [x["conversation_id"] for x in c.get(f"/api/tasks/{rep}/runs").json()]
assert len(kept) == 2 and asyncio.run(count_hidden(rep)) == 2, (kept, asyncio.run(count_hidden(rep)))
assert asyncio.run(conv_of(cid2)) is not None  # 用户的对话不随裁剪消失

# 5) 删任务：藏着的运行对话全删，接过话的留着
assert c.delete(f"/api/tasks/{rep}").status_code in (200, 204)
assert asyncio.run(count_hidden(rep)) == 0 and asyncio.run(conv_of(cid2)) is not None

# 6) 面板任务：运行对话本来就删；跑着时也不进列表
pan = asyncio.run(seed("天气面板", output="panel"))
asyncio.run(worker.run_task(pan))
assert all(asyncio.run(conv_of(x)) is None or asyncio.run(conv_of(x)).task_id != pan for x in seen["during"])
assert asyncio.run(count_hidden(pan)) == 0

# 7) 定时脚本的交付对话（项目里）也藏起来
async def script():
    async with SessionLocal() as db:
        t = ScheduledTask(name="备份", prompt="tar czf b.tgz .", cron="0 3 * * *", output="report", kind="script", notify="always")
        db.add(t); await db.commit()
        conv = await script_tasks._deliver(db, t, None, "备份完成")
        await db.commit()
        return conv.id, t.id
scid, stid = asyncio.run(script())
assert scid not in ids() and asyncio.run(conv_of(scid)).task_id == stid

# 规则函数本身
assert run_conversations.hidden(Conversation(task_id="x")) and not run_conversations.hidden(Conversation())
assert not run_conversations.hidden(None)
print("smoke_run_conversations OK")
