# 冒烟：v1.96 每个后台任务占了多少磁盘（backend app/job_disk.py；jobs.settle 结算时数一次存进 jobs.disk，
# jobs.block / wire / describe 带上，GET /api/jobs/{id} 的 disk（运行中现数、有缓存），job_status 工具里那句“磁盘：……”）。
# 1) scan 纯函数：只算 mtime 落在时段内的普通文件，按顶层条目分组（目录带 /），跳过 .jobs/.spill/.turns/.git，
#    .home 算（装的软件），不跟随符号链接，until 上界，超过上限标 partial；
# 2) measure / wire / text：日志按 .jobs/<id>/ 整个目录算，最大 TOP_MAX 组，坏数据 → None，brief 阈值、重叠与 partial 措辞；
# 3) 结算：一个运行中的任务写了 2 MB 文件 + 日志，写下 exit → refresh 结算 → jobs.disk 有账、block/wire/describe 带上，
#    同时段另一个任务 → overlap=1；之后删掉文件，账不变（当时的账）；老任务（disk 为空）→ null；
# 4) REST：GET /api/jobs/{id} 运行中现数、CACHE_S 内用缓存；结束了给存下的账；
# 5) 模拟模型调 job_status（运行中）→ 工具结果里有“磁盘：运行期间工作区里新写或改过”；6) 迁移 0045 有 jobs.disk。
# 运行：python tests/smoke_job_disk.py
import os, sys, asyncio, subprocess, tempfile, json, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, JOB_MAX_RUNNING="6",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import job_disk, jobs, llm
from app.storage import project_dir
M = 1 << 20

def put(p: Path, size: int, mtime: float | None = None):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    if mtime is not None:
        os.utime(p, (mtime, mtime))

# ---- 1. scan ----
w = Path(tmp) / "scanws"
now = time.time()
put(w / "old.txt", 500, now - 3600)
put(w / "node_modules/a/b/c.js", 3000)
put(w / "node_modules/x.js", 1000)
put(w / "out.csv", 2000)
put(w / ".home/.local/lib/p.py", 700)
for skip in (".jobs/j1/log", ".spill/s", ".turns/t", ".git/objects/o"):
    put(w / skip, 9999)
(w / "link").symlink_to(w / "node_modules")
g, n, partial = job_disk.scan(w, now - 60, None)
assert g == {"node_modules/": 4000, "out.csv": 2000, ".home/": 700}, g
assert n == 4 and not partial
g, n, _ = job_disk.scan(w, now - 7200, now - 1800)  # 上界：只有那个旧文件
assert g == {"old.txt": 500} and n == 1, g
g, n, partial = job_disk.scan(w, now - 60, None, limit=2)
assert partial
assert job_disk.scan(w / "nope", 0, None) == ({}, 0, False)
print("1 scan ok")

# ---- 2. measure / wire / text ----
jr = Path(tmp) / "jr"
put(jr / "log", 1500); put(jr / "log.1", 500); put(jr / "exit", 2)
start = datetime.now(timezone.utc) - timedelta(seconds=60)
d = job_disk.measure(w, jr, start, None, overlap=0)
assert d["log"] == 2002 and d["written"] == 6700 and d["files"] == 4, d
assert [t["path"] for t in d["top"]] == ["node_modules/", "out.csv", ".home/"] and not d["partial"], d
assert job_disk.wire(json.dumps(d)) == d and job_disk.wire(d) == d
for bad in (None, "", "{", "[]", {"log": 1}, {**d, "log": -1}, {**d, "files": "x"}):
    assert job_disk.wire(bad) is None, bad
assert job_disk.wire({**d, "top": [{"path": "a", "size": 3}, "junk", {"size": 1}]})["top"] == [{"path": "a", "size": 3}]
t = job_disk.text(d)
assert t.startswith("运行期间工作区里新写或改过 4 个文件，共 6.5 KB（最大：node_modules/ 3.9 KB、out.csv 2 KB、装的软件（.home） 700 B）") and t.endswith("；日志 2 KB"), t
assert job_disk.text(d, brief=True) == ""  # 都小于 1 MB：结论里不提
big = {**d, "written": 5 * M, "overlap": 2, "partial": True}
bt = job_disk.text(big, brief=True)
assert "共 5 MB" in bt and "只数了一部分" in bt and "同时段还有 2 个任务在跑，可能包含它们写的" in bt, bt
assert job_disk.text({**d, "files": 0, "written": 0, "top": []}) == "运行期间工作区里没有新写文件；日志 2 KB"
assert job_disk.text(None) == ""
print("2 measure ok")

# ---- 3. 结算 ----
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.auth import require_user
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Job, Message, Project
from app.routes import jobs as rj

async def seed():
    async with SessionLocal() as db:
        p = Project(name="数据", emoji="🧪"); db.add(p); await db.flush()
        conv = Conversation(title="跑", project_id=p.id); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("处理数据")))
        old = datetime.now(timezone.utc) - timedelta(seconds=30)
        for jid, title in (("jdisk1", "抓图片"), ("jdisk2", "另一个"), ("jold", "老任务")):
            db.add(Job(id=jid, project_id=p.id, conversation_id=conv.id, title=title, command="python crawl.py",
                       timeout=600, created_at=old))
        await db.commit()
        return p.id, conv.id
pid, cid = asyncio.run(seed())
ws = project_dir(pid)
put(ws / "images/1.jpg", 2 * M)
put(ws / "notes.md", 10, time.time() - 7200)  # 任务开始前就有：不算
put(ws / ".jobs/jdisk1/log", 300 * 1024)
put(ws / ".jobs/jdisk2/log", 10)
async def get(jid):
    async with SessionLocal() as db:
        return await db.get(Job, jid)
async def settle(jid, code="0"):
    (ws / ".jobs" / jid / "exit").write_text(code)
    async with SessionLocal() as db:
        await jobs.refresh(db, await db.get(Job, jid))
asyncio.run(settle("jdisk1"))
j = asyncio.run(get("jdisk1"))
assert j.state == "done" and j.disk, (j.state, j.disk)
dd = job_disk.wire(j.disk)
assert dd["files"] == 1 and dd["written"] == 2 * M and dd["top"] == [{"path": "images/", "size": 2 * M}], dd
assert dd["log"] >= 300 * 1024 and dd["overlap"] == 2, dd  # jdisk2、jold 都还在跑
assert jobs.block(j)["disk"] == dd and jobs.wire(j)["disk"] == dd
desc = jobs.describe(j)
assert "；运行期间工作区里新写或改过 1 个文件，共 2 MB（最大：images/ 2 MB）" in desc, desc
(ws / "images/1.jpg").unlink()
assert job_disk.wire(asyncio.run(get("jdisk1")).disk) == dd  # 当时的账，不跟着变
print("3 settle ok")

# ---- 4. REST ----
app = FastAPI(); app.include_router(rj.router)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
assert c.get("/api/jobs/jdisk1").json()["disk"] == dd
put(ws / "data/a.bin", M)
r = c.get("/api/jobs/jdisk2").json()
assert r["state"] == "running" and r["disk"]["files"] == 1 and r["disk"]["top"][0]["path"] == "data/", r["disk"]
assert r["disk"]["overlap"] == 2, r["disk"]  # jold 在跑 + jdisk1 已结束但时段重叠
put(ws / "data/b.bin", M)
assert c.get("/api/jobs/jdisk2").json()["disk"]["files"] == 1  # 缓存
job_disk.forget("jdisk2")
assert c.get("/api/jobs/jdisk2").json()["disk"]["files"] == 2
assert jobs.wire(asyncio.run(get("jdisk2")))["disk"] is None  # 运行中 wire 不带（只在 GET /{id} 现数）
async def wipe_old():
    async with SessionLocal() as db:
        x = await db.get(Job, "jold"); x.state = "done"; x.finished_at = datetime.now(timezone.utc); await db.commit()
asyncio.run(wipe_old())
o = c.get("/api/jobs/jold").json()
assert o["disk"] is None and "disk" not in jobs.block(asyncio.run(get("jold")))
print("4 rest ok")

# ---- 5. job_status ----
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
            yield chunk(tool=[NS(index=0, id=f"c{len(script)}", function=NS(name=step[0], arguments=json.dumps(step[1])))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid))
def last_tool():
    return [m for m in seen[-1] if m["role"] == "tool"][-1]["content"]
job_disk.forget()
script[:] = [("job_status", {"job_id": "jdisk2"}), "好。"]
asyncio.run(turn())
t = last_tool()
assert "磁盘：运行期间工作区里新写或改过 2 个文件，共 2 MB（最大：data/ 2 MB）" in t, t
script[:] = [("job_status", {"job_id": "jdisk1", "tail": True}), "好。"]
asyncio.run(turn())
t = last_tool()
assert "共 2 MB（最大：images/ 2 MB）" in t and "磁盘：" not in t, t  # 结束了：describe 里那句，不重复
print("5 tool ok")

# ---- 6. 迁移 ----
import sqlite3
cols = [row[1] for row in sqlite3.connect(f"{tmp}/t.db").execute("PRAGMA table_info(jobs)")]
assert "disk" in cols, cols
r = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0044"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr
assert "disk" not in [row[1] for row in sqlite3.connect(f"{tmp}/t.db").execute("PRAGMA table_info(jobs)")]
print("6 migration ok")
print("ALL OK")
