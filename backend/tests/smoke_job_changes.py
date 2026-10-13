# 冒烟：v2.18 CORE 32 后台任务改了哪些文件 → 任务卡上的改动区 + 撤销（app/job_changes.py，影子库钉住在 command_changes）。
# 1) 钉住：pin/restore/unpin；钉着的旧版本对象不被之后的 _sync 清掉；过期钉删掉；
# 2) jobs.start（模拟沙盒）启动前钉基线 → 任务改 / 新建 / 删 / chmod → 写 exit → refresh 结算 → jobs.changes、
#    block / wire / describe 带上、钉拔掉；同时段另一个任务 → overlap；这期间对话回合自己记过撤销的路径让出去（shared）；
# 3) REST 撤销：之后又被改过 → 409 conflicts（一个都不动）→ 改回 → 撤销成功、文件回到任务开始前、聊天里的任务卡标 undone；
#    再撤 → 410；运行中 → 410；
# 4) 常驻服务不盯、启动失败拔钉、转后台 adopt 也钉；没改文件 → 没有改动区；
# 5) 模拟模型 job_status → “它改了 … （用户可在任务卡上撤销）”；历史里任务卡带这句；6) 迁移 0052 来回。
# 运行：python tests/smoke_job_changes.py
import os, sys, asyncio, subprocess, tempfile, json, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, JOB_MAX_RUNNING="6",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', AUTO_TITLE="false")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

import httpx
from app import command_changes as C, job_changes as JC, jobs, llm, sandbox_client, turn_changes as T
from app.blocks import JobBlock, blocks_to_text, text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Job, Message, Project
from app.storage import project_dir

launched: list = []
fail_launch = False
async def fake_start(ws, job_id, **kw):
    if fail_launch:
        raise httpx.ConnectError("down")
    launched.append(job_id)
sandbox_client.start_job = fake_start
mode = lambda p: os.stat(p).st_mode & 0o777

async def seed():
    async with SessionLocal() as db:
        p = Project(name="数据", emoji="🧪"); db.add(p); await db.flush()
        conv = Conversation(title="跑", project_id=p.id); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("处理数据")))
        await db.commit()
        return p.id, conv.id
pid, cid = asyncio.run(seed())
ws = project_dir(pid); ws.mkdir(parents=True, exist_ok=True)
pins = ws / ".turns/shadow/pins"

# ---- 1. 钉住 ----
(ws / "a.txt").write_text("one\n")
t = T.Tracker(); C.before(pid, t)
assert C.pin(pid, "x1", t) and (pins / "x1.json").is_file()
sha_one = t.seen["a.txt"][2]
time.sleep(0.01); (ws / "a.txt").write_text("two\n")
C.before(pid, T.Tracker())  # 另一轮扫描：旧版本没人引用了，但钉着
assert (ws / ".turns/shadow/obj" / sha_one).is_file()
back = C.restore(pid, "x1")
assert back.scanned and back.seen["a.txt"][2] == sha_one
assert C.after(pid, back) == ["a.txt"]
card = T.finish(back, pid)
assert card["files"][0]["added"] == 1 and card["files"][0]["removed"] == 1
C.unpin(pid, "x1"); assert not (pins / "x1.json").exists() and C.restore(pid, "x1") is None
T.undo(pid, card["token"]); assert (ws / "a.txt").read_text() == "one\n"
# 过期钉：下一次扫描删掉
t = T.Tracker(); C.before(pid, t); C.pin(pid, "old", t)
os.utime(pins / "old.json", (time.time() - C.PIN_MAX_S - 10,) * 2)
C.before(pid, T.Tracker())
assert not (pins / "old.json").exists()
assert C.pin(pid, "nope", T.Tracker()) is False  # 没扫过的不钉
assert C._pin_name("../../x y") == "xy"
print("1 pin ok")

# ---- 2. 结算 ----
for f in ("keep.txt", "edit.txt", "gone.txt"):
    (ws / f).write_text(f"{f}\n")
(ws / "run.sh").write_text("echo\n"); os.chmod(ws / "run.sh", 0o644)
(ws / "turn.txt").write_text("t0\n")

async def start(**kw):
    async with SessionLocal() as db:
        return (await jobs.start(db, project_id=pid, command=kw.pop("command", "python job.py"), conversation_id=cid, **kw)).id
async def get(jid):
    async with SessionLocal() as db:
        return await db.get(Job, jid)
async def settle(jid, code="0"):
    (ws / ".jobs" / jid / "exit").write_text(code)
    async with SessionLocal() as db:
        await jobs.refresh(db, await db.get(Job, jid))

j1 = asyncio.run(start())
assert (pins / f"job-{j1}.json").is_file() and launched == [j1]
async def card_msg(jid):  # 聊天里一条带任务卡的回复（patch_blocks 会改它）
    async with SessionLocal() as db:
        m = Message(conversation_id=cid, role="assistant", blocks=[jobs.block(await db.get(Job, jid))])
        db.add(m); await db.commit(); return m.id
mid = asyncio.run(card_msg(j1))
time.sleep(0.02)
(ws / "edit.txt").write_text("edit.txt\nmore\n")
(ws / "new.csv").write_text("a,b\n1,2\n")
(ws / "gone.txt").unlink()
os.chmod(ws / "run.sh", 0o755)
# 这期间对话里的一轮自己改了 turn.txt（它的改动卡记着）→ 任务卡让给它
tt = T.Tracker(); tt.before(ws, ws / "turn.txt"); (ws / "turn.txt").write_text("t1\n")
turn_card = T.finish(tt, pid); assert turn_card["token"]
j2 = asyncio.run(start(command="sleep 100"))  # 同时段另一个任务
asyncio.run(settle(j1))
j = asyncio.run(get(j1))
assert j.state == "done" and j.changes, j.changes
d = JC.wire(j)
files = {f["path"]: f for f in d["files"]}
assert set(files) == {"edit.txt", "new.csv", "gone.txt", "run.sh"}, files
assert files["edit.txt"]["added"] == 1 and files["new.csv"]["created"] and files["gone.txt"]["deleted"]
assert files["run.sh"]["mode"] == "加了可执行" and not any(f.get("command") for f in d["files"])
assert d["token"] and d["shared"] == 1 and d["overlap"] is True, d
assert not (pins / f"job-{j1}.json").exists()
assert jobs.block(j)["changes"] == d and jobs.wire(j)["changes"] == d
JobBlock(**jobs.block(j))
desc = jobs.describe(j)
assert "；它改了 edit.txt（+1 −0）" in desc and "等 4 个文件" in desc and "可能也算进来了" in desc and "可在任务卡上撤销" in desc, desc
async def msg_blocks(m):
    async with SessionLocal() as db:
        return (await db.get(Message, m)).blocks
assert msg_blocks and asyncio.run(msg_blocks(mid))[0]["changes"]["token"] == d["token"]  # 卡片已改成终态
print("2 settle ok")

# ---- 3. REST 撤销 ----
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth import require_user
from app.routes import jobs as rj
app = FastAPI(); app.include_router(rj.router)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
r = c.post(f"/api/jobs/{j2}/changes/undo"); assert r.status_code == 410 and "还在运行" in r.json()["detail"], r.text
(ws / "new.csv").write_text("changed later\n")
r = c.post(f"/api/jobs/{j1}/changes/undo")
assert r.status_code == 409 and r.json()["detail"]["conflicts"] == ["new.csv"], r.text
assert (ws / "edit.txt").read_text() == "edit.txt\nmore\n"  # 一个都不动
(ws / "new.csv").write_text("a,b\n1,2\n")
r = c.post(f"/api/jobs/{j1}/changes/undo")
assert r.status_code == 200 and r.json()["changes"]["undone"] is True, r.text
assert (ws / "edit.txt").read_text() == "edit.txt\n" and not (ws / "new.csv").exists()
assert (ws / "gone.txt").read_text() == "gone.txt\n" and mode(ws / "run.sh") == 0o644
assert (ws / "turn.txt").read_text() == "t1\n"  # 归那一轮的，没动
assert asyncio.run(msg_blocks(mid))[0]["changes"]["undone"] is True
assert "用户已在任务卡上撤销" in jobs.describe(asyncio.run(get(j1)))
r = c.post(f"/api/jobs/{j1}/changes/undo"); assert r.status_code == 410 and "撤销过" in r.json()["detail"], r.text
assert c.post("/api/jobs/nope/changes/undo").status_code == 404
print("3 undo ok")

# ---- 4. 常驻 / 启动失败 / adopt / 没改 ----
asyncio.run(settle(j2))
d2 = JC.wire(asyncio.run(get(j2)))  # 它跑的期间用户撤了 j1：期间改的都算进来，卡上提醒同时段有别的任务
assert d2["overlap"] is True and "edit.txt" in [f["path"] for f in d2["files"]], d2
j3 = asyncio.run(start(command="true"))
asyncio.run(settle(j3))
assert JC.wire(asyncio.run(get(j3))) is None and "changes" not in jobs.block(asyncio.run(get(j3)))  # 没改文件 → 没有改动区
r = c.post(f"/api/jobs/{j3}/changes/undo"); assert r.status_code == 410 and "没有改动" in r.json()["detail"]
k = asyncio.run(start(command="python serve.py", keep_alive=True))
assert not (pins / f"job-{k}.json").exists()
fail_launch = True
try:
    asyncio.run(start(command="echo x"))
    raise AssertionError("should fail")
except jobs.JobError:
    pass
fail_launch = False
assert [p.name for p in pins.glob("job-*.json")] == [], list(pins.iterdir())
async def adopt():
    async with SessionLocal() as db:
        jid, _ = jobs.promote_slot()
        (ws / ".jobs" / jid).mkdir(parents=True)
        return (await jobs.adopt(db, job_id=jid, project_id=pid, command="make", seconds=5, conversation_id=cid)).id
ja = asyncio.run(adopt())
assert (pins / f"job-{ja}.json").is_file()
time.sleep(0.02); (ws / "build.out").write_text("ok\n")
asyncio.run(settle(ja))
da = JC.wire(asyncio.run(get(ja)))
assert [f["path"] for f in da["files"]] == ["build.out"] and "overlap" in da, da  # k 常驻还在跑
assert JC.text(None) == "" and JC.text({"files": []}) == ""
print("4 edges ok")

# ---- 5. 模型看到的 ----
script: list = []
seen: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append([dict(m) for m in messages])
    step = script.pop(0)
    async def gen():
        if isinstance(step, tuple):
            yield chunk(tool=[NS(index=0, id=f"c{len(seen)}", function=NS(name=step[0], arguments=json.dumps(step[1])))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
load_builtin()
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid))
script[:] = [("job_status", {"job_id": ja}), "好。"]
asyncio.run(turn())
tool = [m for m in seen[-1] if m["role"] == "tool"][-1]["content"]
assert "它改了 build.out（新建 +1 −0）" in tool and "可在任务卡上撤销" in tool, tool
hist = blocks_to_text([jobs.block(asyncio.run(get(ja)))])
assert "它改了 build.out" in hist, hist
print("5 model ok")

# ---- 6. 迁移 ----
import sqlite3
cols = lambda: [row[1] for row in sqlite3.connect(f"{tmp}/t.db").execute("PRAGMA table_info(jobs)")]
assert "changes" in cols()
r = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0051"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0 and "changes" not in cols(), r.stderr
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0 and "changes" in cols(), r.stderr
print("6 migration ok")
print("ALL OK")
