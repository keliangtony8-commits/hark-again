# 冒烟：“我对你的了解”（/api/memory-digest）。模拟模型：
# 没记忆 → 空、不过期、POST 不调模型；有记忆 GET 不调模型；POST 调一次（kind=digest、便宜模型、profile 在前）→
# 指纹一致不过期；改/删/加一条都变过期；模型失败 502 且旧概括保留；记忆清空后 POST 删掉旧概括；超长输入按预算截断。
# 运行：python tests/smoke_memory_digest.py
import os, sys, asyncio, subprocess, tempfile
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from app import llm, memory_digest
from app.config import settings
from app.db import SessionLocal
from app.models import Memory

calls = []
fail = {"on": False}

async def fake_complete(messages, model=None, kind="summary"):
    calls.append((model, kind, messages[1]["content"]))
    if fail["on"]:
        raise RuntimeError("网关挂了")
    return f"你是学生（第{len(calls)}版）"
llm.complete = fake_complete

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.auth import require_user
from app.routes import memory_digest as rd
app = FastAPI(); app.include_router(rd.router)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)

def add(*mems):
    async def go():
        async with SessionLocal() as db:
            db.add_all(mems); await db.commit()
    asyncio.run(go())

def run(fn):
    async def go():
        async with SessionLocal() as db:
            await fn(db)
    asyncio.run(go())

r = c.get("/api/memory-digest").json()
assert r == {"text": None, "generated_at": None, "count": 0, "memories": 0, "stale": False}, r
assert c.post("/api/memory-digest").json()["text"] is None and calls == []

add(Memory(id="m1", category="food", content="不吃辣"), Memory(id="m2", category="profile", content="大二学生"))
r = c.get("/api/memory-digest").json()
assert r["text"] is None and r["memories"] == 2 and not r["stale"] and calls == []

r = c.post("/api/memory-digest").json()
assert r["text"] == "你是学生（第1版）" and r["count"] == 2 and r["memories"] == 2 and not r["stale"] and r["generated_at"], r
model, kind, body = calls[0]
assert model == settings.summary_model and kind == "digest", calls[0]
assert body.index("[profile] 大二学生") < body.index("[food] 不吃辣"), body
assert c.get("/api/memory-digest").json()["stale"] is False and len(calls) == 1   # GET 不调模型

async def edit(db):
    m = await db.get(Memory, "m1"); m.content = "不吃辣，爱吃甜"; await db.commit()
run(edit)
assert c.get("/api/memory-digest").json()["stale"] is True
c.post("/api/memory-digest")
assert c.get("/api/memory-digest").json()["stale"] is False

add(Memory(id="m3", content="早上跑步"))
r = c.get("/api/memory-digest").json()
assert r["stale"] and r["memories"] == 3 and r["count"] == 2, r

fail["on"] = True
r = c.post("/api/memory-digest")
assert r.status_code == 502, r.text
r = c.get("/api/memory-digest").json()
assert r["text"] == "你是学生（第2版）" and r["stale"], r     # 失败不动旧概括
fail["on"] = False

async def drop(db):
    m = await db.get(Memory, "m3"); await db.delete(m); await db.commit()
run(drop)
assert c.get("/api/memory-digest").json()["stale"] is False   # 删回原样 → 指纹又对上

add(*[Memory(id=f"x{i}", content="很长的记忆" * 100) for i in range(40)])
n = len(calls)
c.post("/api/memory-digest")
assert len(calls) == n + 1 and len(calls[-1][2]) <= memory_digest.INPUT_CHARS, len(calls[-1][2])
assert calls[-1][2].startswith("[profile] 大二学生")

async def clear(db):
    for m in (await db.scalars(__import__("sqlalchemy").select(Memory))).all():
        await db.delete(m)
    await db.commit()
run(clear)
n = len(calls)
r = c.post("/api/memory-digest").json()
assert r["text"] is None and r["memories"] == 0 and len(calls) == n, r
assert c.get("/api/memory-digest").json()["text"] is None
print("memory digest smoke OK")
