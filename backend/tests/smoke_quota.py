# 冒烟：v1.31 工作区磁盘配额（app/quota.py 唯一规则；write_file / 上传 / 存成文件 / 后台任务启动都先查，
# 运行中的后台任务被护栏停掉，前台命令照跑但结果里告诉模型满了；电脑页带 disk_limit / disk_level）。
# 1) 规则：off / ok / tight / full、剩余、大小文字、缓存与 forget / remember；
# 2) 模拟模型的一轮：主聊天 write_file 放得下照写、放不下拒绝（文件不落盘、活动时间线记失败）；
# 3) run_command 前台：快满 / 满了时给模型的提醒；满了后台任务不启动；
# 4) 护栏：运行中的后台任务在工作区满了时被停，stop_reason 写明配额，卡片照常结论；
# 5) 接口：上传 507、存成文件 400、删文件后重数、电脑状态带配额、清理后重数；
# 6) workspace_disk_mb=0 = 不限：什么都不拦。
# 运行：python tests/smoke_quota.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', WORKSPACE_DISK_MB="1")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
sys.path.insert(0, os.path.dirname(__file__))
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import jobs, llm, quota, sandbox_client, storage, workspaces
from app.agent.runner import run_turn
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.auth import require_query_token, require_user
from app.blocks import text_to_blocks
from app.config import settings
from app.db import SessionLocal
from app.models import Conversation, Job, Message
from app.routes import files as rf
from fake_sandbox import streamed

MB = 1024 * 1024
ME = workspaces.PERSONAL
me = storage.project_dir(ME)
run = asyncio.run

# ---- 1. 规则 ----
assert quota.limit_bytes() == MB
assert quota.Quota(0, 0).level == "off" and quota.Quota(10, 0).free is None and quota.Quota(10 * MB, 0).fits(MB)
assert quota.Quota(100, 1000).level == "ok" and quota.Quota(850, 1000).level == "tight" and quota.Quota(1000, 1000).level == "full"
assert quota.Quota(900, 1000).free == 100 and quota.Quota(1200, 1000).free == 0
assert quota.Quota(900, 1000).fits(100) and not quota.Quota(900, 1000).fits(101)
assert quota.Quota(5, 1000).wire() == {"disk_limit": 1000, "disk_level": "ok"} and quota.Quota(5, 0).wire() == {"disk_limit": None, "disk_level": "off"}
assert quota.size_text(3 * 1024 * MB) == "3 GB" and quota.size_text(int(1.5 * MB)) == "1.5 MB" and quota.size_text(20 * 1024) == "20 KB" and quota.size_text(7) == "7 B"
(me / "a.bin").write_bytes(b"x" * 1000)
assert quota.state(ME, fresh=True).used == 1000
(me / "b.bin").write_bytes(b"x" * 1000)
assert quota.state(ME).used == 1000            # 缓存
quota.forget(ME)
assert quota.state(ME).used == 2000            # forget 后重数
assert quota.remember(ME, 5, False).used == 5 and quota.state(ME).used == 5
quota.forget()
assert quota.model_note(ME) == ""
quota.check(ME, 1000)                           # 放得下不抛
try:
    quota.check(ME, MB)
    raise AssertionError("应该放不下")
except quota.QuotaError as e:
    assert "放不下" in str(e) and "只剩" in str(e) and "1 MB" in str(e), e

# ---- 2. 模拟模型：write_file ----
script: list = []
seen: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append({"messages": messages})
    step = script.pop(0)
    async def gen():
        if isinstance(step, tuple):
            yield chunk(tool=[NS(index=0, id=f"c{len(script)}", function=NS(name=step[0], arguments=json.dumps(step[1], ensure_ascii=False)))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()
def tool_text():
    return next(m["content"] for m in reversed(seen[-1]["messages"]) if m.get("role") == "tool")

async def seed():
    async with SessionLocal() as db:
        cv = Conversation(title="主聊天"); db.add(cv); await db.flush()
        db.add(Message(conversation_id=cv.id, role="user", blocks=text_to_blocks("写个文件")))
        await db.commit()
        return cv.id
cid = run(seed())
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid))

script.extend([("write_file", {"path": "ok.txt", "content": "hello"}), "写好了。"])
reply = run(turn())
assert (me / "ok.txt").read_text() == "hello" and "已写入" in tool_text()
big = "y" * (MB - 2000)  # 加上已有的 2005 字节就超了
script.extend([("write_file", {"path": "big.txt", "content": big}), "满了。"])
reply = run(turn())
assert not (me / "big.txt").exists(), "放不下不该落盘"
t = tool_text()
assert "没有写入 big.txt" in t and "放不下" in t, t
step = next(s for s in reply.steps if s.get("detail") == "big.txt")
assert step["state"] == "error" and "磁盘满了" in step.get("note", ""), reply.steps

# ---- 3. run_command：提醒 + 满了不启动后台任务 ----
async def fake_run(project_id, command, timeout=60):
    if "dd" in command:
        (storage.project_dir(project_id) / "dump.bin").write_bytes(b"z" * int(0.9 * MB))
    return {"exit_code": 0, "output": "ok\n", "timed_out": False}
sandbox_client.stream = streamed(fake_run)
async def tool(name, ws=None, **args):
    async with SessionLocal() as db:
        return await REGISTRY[name].run(ToolContext(db=db, project_id=ws, conversation_id=cid), **args)
res = run(tool("run_command", command="ls"))
assert "磁盘" not in res.content, res.content
res = run(tool("run_command", command="dd if=/dev/zero of=dump.bin"))
assert "快满了" in res.content and "已用" in res.content, res.content       # 0.9 MB / 1 MB → tight（命令后重数）
assert "磁盘有上限" in REGISTRY["run_command"].description
(me / "dump2.bin").write_bytes(b"z" * int(0.2 * MB))
res = run(tool("run_command", command="du -sh *"))
assert "磁盘满了" in res.content and "du -sh" in res.content and "告诉用户" in res.content, res.content
started = []
async def fake_start(pid, jid):
    started.append(jid)
sandbox_client.start_job = fake_start
res = run(tool("run_command", command="python train.py", background=True))
assert "没有启动" in res.content and "磁盘满了" in res.content and not started, res.content
assert res.failed

# ---- 4. 护栏：跑着的后台任务在满了时被停 ----
(me / "dump.bin").unlink(); (me / "dump2.bin").unlink(); quota.forget(ME)
res = run(tool("run_command", command="python train.py", background=True))
assert started and "已在后台启动" in res.content, res.content
jid = started[-1]
cancelled = []
async def fake_cancel(pid, j):
    cancelled.append(j)
async def fake_alive(pid, j):
    return False
sandbox_client.cancel_job, sandbox_client.job_alive = fake_cancel, fake_alive
async def guard():
    async with SessionLocal() as db:
        job = await db.get(Job, jid)
        await jobs.refresh(db, job, check_alive=True)
        return job.state, job.stop_reason
assert run(guard()) == ("running", None)   # 没满：照跑
(me / "out.bin").write_bytes(b"w" * MB); quota.forget(ME)
state, reason = run(guard())
assert state == "cancelled" and cancelled == [jid], (state, cancelled)
assert reason and "超过上限 1 MB" in reason, reason
assert (me / ".jobs" / jid / "cancelled").read_text() == "guard"

# ---- 5. 接口 ----
app = FastAPI(); app.include_router(rf.router)
app.dependency_overrides[require_user] = lambda: "u"
app.dependency_overrides[require_query_token] = lambda: "u"
c = TestClient(app)
async def no_status(ws):
    raise httpx.ConnectError("down")
sandbox_client.status = no_status
r = c.post(f"/api/projects/{ME}/files", files={"file": ("new.txt", b"abc")})
assert r.status_code == 507 and "磁盘满了" in r.json()["detail"], r.text
assert not (me / "new.txt").exists()
st = c.get(f"/api/projects/{ME}/computer").json()
assert st["disk_limit"] == MB and st["disk_level"] == "full" and st["disk_used"] >= MB, st
async def seed_reply():
    async with SessionLocal() as db:
        m = Message(conversation_id=cid, role="assistant", blocks=text_to_blocks("一段要存的回复"))
        db.add(m); await db.commit()
        return m.id
mid = run(seed_reply())
r = c.post(f"/api/messages/{mid}/save-to-project", json={})
assert r.status_code == 400 and "磁盘满了" in r.json()["detail"], r.text
assert c.delete(f"/api/projects/{ME}/files/out.bin").status_code == 200
assert quota.state(ME).level == "ok"                # 删文件后立刻重数，不用等缓存过期
r = c.post(f"/api/projects/{ME}/files", files={"file": ("new.txt", b"abc")})
assert r.status_code == 200 and (me / "new.txt").read_bytes() == b"abc"
assert c.post(f"/api/messages/{mid}/save-to-project", json={}).status_code == 200
st = c.get(f"/api/projects/{ME}/computer").json()
assert st["disk_level"] == "ok", st
# 清理：任务日志被删后重数
(me / ".spill").mkdir(exist_ok=True); (me / ".spill" / "x.txt").write_bytes(b"s" * int(0.9 * MB)); quota.forget(ME)
assert quota.state(ME).level == "tight"
async def no_cleanup(ws):
    raise httpx.ConnectError("down")
sandbox_client.cleanup = no_cleanup
r = c.post(f"/api/projects/{ME}/computer/cleanup").json()
assert r["freed"] >= int(0.9 * MB) and r["status"]["disk_level"] == "ok" and quota.state(ME).level == "ok", r

# ---- 6. 不限 ----
settings.workspace_disk_mb = 0
(me / "huge.bin").write_bytes(b"h" * 2 * MB); quota.forget(ME)
assert quota.state(ME).level == "off" and quota.model_note(ME) == "" and quota.job_reason(ME) is None
quota.check(ME, 100 * MB)
assert c.get(f"/api/projects/{ME}/computer").json()["disk_limit"] is None
assert c.post(f"/api/projects/{ME}/files", files={"file": ("more.txt", b"m")}).status_code == 200
print("smoke_quota ok")
