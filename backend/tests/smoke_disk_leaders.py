# 冒烟：v1.98 “我的电脑”页磁盘一节的“谁写得最多”（app/job_disk.leaders → computer.status 的 disk_jobs）。
# 1) 只看本工作区、最近 WINDOW_DAYS 天结束、有结算账的任务；运行中 / 没账 / 坏账 / 账为 0 / 窗口外 / 别的工作区都不列；
# 2) 按 written + log 从大到小，同大按 id，最多 LEADERS_MAX 个；3) 第二项 = .jobs/<id>/ 目录还在；
# 4) computer.status 带 disk_jobs（jobs.wire：disk 带结算账，finished_at 带时区；+ log_kept），沙盒连不上也照给；
# 5) 一键清理后 kept 变 False，但账还在（是“当时的账”）。纯读库，不遍历工作区；无表结构改动（无迁移）。
# 运行：python tests/smoke_disk_leaders.py
import os, sys, asyncio, subprocess, tempfile, json
from datetime import datetime, timedelta, timezone
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

import httpx
from app import computer, job_disk, sandbox_client
from app.db import SessionLocal
from app.models import Job
from app.storage import project_dir
M = 1 << 20
NOW = datetime.now(timezone.utc)

def acct(written, log, top=None, overlap=0, partial=False):
    return json.dumps({"log": log, "written": written, "files": 3 if written else 0, "overlap": overlap, "partial": partial,
                       "top": [{"path": p, "size": s} for p, s in (top or [])]})

SEED = [  # id, ws, state, finished 天前, disk
    ("j_big", "me", "done", 1, acct(300 * M, 2 * M, [("node_modules/", 280 * M), ("out.csv", 20 * M)], overlap=1)),
    ("j_mid", "me", "failed", 2, acct(40 * M, 1 * M, [("data/", 40 * M)], partial=True)),
    ("j_log", "me", "cancelled", 3, acct(0, 5 * M)),
    ("j_tie_a", "me", "done", 4, acct(1 * M, 0, [("a.bin", M)])),
    ("j_tie_b", "me", "done", 4, acct(1 * M, 0, [("b.bin", M)])),
    ("j_small", "me", "done", 5, acct(1000, 10)),
    ("j_zero", "me", "done", 1, acct(0, 0)),
    ("j_old", "me", "done", 9, acct(900 * M, 0, [("old/", 900 * M)])),
    ("j_none", "me", "done", 1, None),
    ("j_bad", "me", "done", 1, "{broken"),
    ("j_run", "me", "running", None, acct(800 * M, 0)),
    ("j_other", "p_other", "done", 1, acct(999 * M, 0)),
]

async def seed():
    async with SessionLocal() as db:
        for jid, ws, state, ago, disk in SEED:
            fin = None if ago is None else NOW - timedelta(days=ago)
            db.add(Job(id=jid, project_id=ws, title=f"任务 {jid}", command="true", timeout=60, state=state,
                       created_at=(fin or NOW) - timedelta(minutes=5), finished_at=fin, disk=disk))
        await db.commit()
asyncio.run(seed())
for jid in ("j_big", "j_log"):
    (project_dir("me") / ".jobs" / jid).mkdir(parents=True, exist_ok=True)
    (project_dir("me") / ".jobs" / jid / "log").write_text("x")

async def lead():
    async with SessionLocal() as db:
        return [(j.id, kept) for j, kept in await job_disk.leaders(db, "me")]
rows = asyncio.run(lead())
assert rows == [("j_big", True), ("j_mid", False), ("j_log", True), ("j_tie_a", False), ("j_tie_b", False)], rows
print("1-3 leaders ok")

async def nobox(ws):
    raise httpx.ConnectError("down")
sandbox_client.status = nobox
async def st():
    async with SessionLocal() as db:
        return await computer.status(db, "me")
s = asyncio.run(st())
dj = s["disk_jobs"]
assert [r["id"] for r in dj] == ["j_big", "j_mid", "j_log", "j_tie_a", "j_tie_b"] and s["sandbox"] == {"state": "unreachable"}
big = dj[0]
assert big["title"] == "任务 j_big" and big["state"] == "done" and big["log_kept"] is True, big
assert big["disk"]["written"] == 300 * M and big["disk"]["log"] == 2 * M and big["disk"]["overlap"] == 1, big["disk"]
assert big["disk"]["top"][0] == {"path": "node_modules/", "size": 280 * M}
assert dj[1]["disk"]["partial"] is True and dj[1]["log_kept"] is False and dj[1]["state"] == "failed"
assert big["finished_at"].endswith("+00:00"), big["finished_at"]
json.dumps(s)  # 能直接上线路
async def other():
    async with SessionLocal() as db:
        return await job_disk.leaders(db, "p_other")
assert [j.id for j, _ in asyncio.run(other())] == ["j_other"]
print("4 status ok")

async def clean():
    async with SessionLocal() as db:
        return await computer.cleanup(db, "me")
async def nocl(ws):
    raise httpx.ConnectError("down")
sandbox_client.cleanup = nocl
out = asyncio.run(clean())
after = out["status"]["disk_jobs"]
assert [r["id"] for r in after][:2] == ["j_big", "j_mid"] and not any(r["log_kept"] for r in after), after
assert after[0]["disk"]["written"] == 300 * M
print("5 cleanup ok")
print("ALL OK")
