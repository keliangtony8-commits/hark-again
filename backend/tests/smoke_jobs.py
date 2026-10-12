# 冒烟：v1.19 项目沙盒后台任务（app/jobs.py + run_command background=true + job_status/cancel_job + /api/jobs + worker 接着说）。
# 沙盒服务用本机 bash 顶替：start_job 真的执行 jobs.script() 写出的 run.sh（setsid 新会话），cancel 整组杀，alive 查 pid，
# 所以包装脚本本身（pid / log / exit / 取消标记 / 进度条 \r）是真跑的。模拟模型，迁移 0026。
# 覆盖：启动 → 卡片 → 完成后接口结掉、卡片改终态、followup pending → worker 在原对话接着说（通知不落库）；
# 失败退出码；用户取消（整组进程死、照常通知）/ 模型取消（不通知）；进程消失没留退出码 → lost；同时运行上限；
# .jobs 不出现在项目文件里；job_status 看过结论后不再通知；原对话一轮没答完先等、太久放弃；对话删了不接着说。
# 运行：python tests/smoke_jobs.py
import os, sys, asyncio, subprocess, tempfile, json, signal, time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, JOB_MAX_RUNNING="2",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from sqlalchemy import select
from app import jobs, llm, sandbox_client, storage
from app.agent.runner import run_turn
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.auth import require_user
from app.blocks import Block, blocks_to_text, text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Job, Message, Project
from app.routes import files as rf, jobs as rj

# ---- 本机顶替沙盒服务 ----
procs: dict[str, subprocess.Popen] = {}
async def start_job(pid, jid):
    procs[jid] = subprocess.Popen(["bash", f".jobs/{jid}/run.sh"], cwd=storage.project_dir(pid), start_new_session=True)
def _pid(pid, jid):
    try:
        return int((storage.project_dir(pid) / ".jobs" / jid / "pid").read_text())
    except (FileNotFoundError, ValueError):
        return None
async def cancel_job(pid, jid):
    if (p := _pid(pid, jid)) is not None:
        try:
            os.killpg(p, signal.SIGTERM)
        except ProcessLookupError:
            pass
    procs[jid].wait(10)  # run.sh 写完 exit 才算
async def job_alive(pid, jid):
    p = _pid(pid, jid)
    if p is None:
        return False
    try:
        os.kill(p, 0)
        return True
    except ProcessLookupError:
        return False
sandbox_client.start_job, sandbox_client.cancel_job, sandbox_client.job_alive = start_job, cancel_job, job_alive
jobs.LOST_GRACE = 0

# ---- 模拟模型 ----
script: list = []
seen: list[list] = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append(messages)
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

app = FastAPI()
app.include_router(rj.router); app.include_router(rf.router)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)

def run(coro):
    return asyncio.run(coro)

async def seed():
    async with SessionLocal() as db:
        p = Project(name="训练", emoji="🧪"); db.add(p); await db.flush()
        conv = Conversation(title="跑训练", project_id=p.id); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("把训练脚本放后台跑")))
        await db.commit()
        return p.id, conv.id
pid, cid = run(seed())

async def turn(conv_id=cid, notice=None):
    async with SessionLocal() as db:
        conv = await db.get(Conversation, conv_id)
        return await run_turn(db, conv, notice=notice)

async def job(jid):
    async with SessionLocal() as db:
        return await db.get(Job, jid)

def wait_exit(jid, secs=10):
    end = time.time() + secs
    while time.time() < end:
        if (storage.project_dir(pid) / ".jobs" / jid / "exit").exists():
            return
        time.sleep(0.1)
    raise AssertionError("job never exited")

# ---- 纯规则 ----
assert "timeout -k 5 30 bash -l" in jobs.script("jabc123", 30)
TypeAdapter(Block).validate_python({"type": "job", "id": "j1", "title": "t", "command": "c", "state": "failed", "exit_code": 3, "tail": "x"})
line = blocks_to_text([{"type": "job", "id": "j1", "title": "装依赖", "command": "pip", "state": "failed", "exit_code": 3, "tail": "No module"}])
assert "后台任务 j1「装依赖」——失败，退出码 3" in line and "No module" in line, line
assert jobs.duration_text(5) == "5 秒" and jobs.duration_text(125) == "2 分 5 秒" and jobs.duration_text(3720) == "1 小时 2 分"

# ---- 1. 模型启动后台任务 → 卡片 ----
CMD = "echo 开始; printf '10%%\\r50%%\\r100%%\\n'; sleep 1; echo 训练完成 acc=0.93"
script.extend([("run_command", {"command": CMD, "background": True, "title": "训练模型"}), "在后台训练了，大约 1 秒。"])
reply = run(turn())
jb = next(b for b in reply.blocks if b["type"] == "job")
assert jb["state"] == "running" and jb["title"] == "训练模型" and jb["started_at"].endswith("+00:00"), jb
tool_msg = next(m for m in seen[-1] if m["role"] == "tool")
assert "已在后台启动任务" in tool_msg["content"] and jb["id"] in tool_msg["content"], tool_msg
j1 = jb["id"]
r = c.get(f"/api/jobs/{j1}").json()
assert r["state"] in ("running", "done") and r["project_id"] == pid and r["conversation_id"] == cid, r

# ---- 2. 结束 → 接口结掉、卡片改终态、进度条只留最后一帧 ----
wait_exit(j1)
r = c.get(f"/api/jobs/{j1}").json()
assert r["state"] == "done" and r["exit_code"] == 0 and r["followup"] == "pending", r
assert "训练完成 acc=0.93" in r["tail"] and "100%" in r["tail"] and "50%" not in r["tail"], r["tail"]
assert r["finished_at"] and r["elapsed"] >= 1, r
async def stored_block(jid):
    async with SessionLocal() as db:
        for m in (await db.scalars(select(Message).where(Message.conversation_id == cid))).all():
            for b in m.blocks:
                if b.get("type") == "job" and b["id"] == jid:
                    return b
b = run(stored_block(j1))
assert b["state"] == "done" and "训练完成" in b["tail"] and b["finished_at"], b

# ---- 3. worker 接着说：通知给模型看、不落库；回复存成助手消息 ----
async def count_msgs(conv_id=cid):
    async with SessionLocal() as db:
        return [(m.role, blocks_to_text(m.blocks)) for m in (await db.scalars(
            select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at))).all()]
before = run(count_msgs())
script.append("训练跑完了：准确率 0.93。")
async def follow():
    async with SessionLocal() as db:
        return await jobs.follow_ups(db)
assert run(follow()) == 1
last_user = [m for m in seen[-1] if m["role"] == "user"][-1]["content"]
assert "系统通知" in last_user and "已完成" in last_user and "训练完成 acc=0.93" in last_user, last_user
after = run(count_msgs())
assert after[:len(before)] == before and after[-1] == ("assistant", "训练跑完了：准确率 0.93。"), after
assert all("系统通知" not in t for _, t in after)
assert run(job(j1)).followup == "done" and run(follow()) == 0  # 只接一次

# ---- 4. 失败的退出码 ----
async def start(cmd, conv_id=cid, **kw):
    async with SessionLocal() as db:
        return (await jobs.start(db, project_id=pid, command=cmd, conversation_id=conv_id, **kw)).id
j2 = run(start("echo 缺依赖 >&2; exit 3", title="装依赖"))
wait_exit(j2)
r = c.get(f"/api/jobs/{j2}").json()
assert r["state"] == "failed" and r["exit_code"] == 3 and "缺依赖" in r["tail"], r

# ---- 5. 同时运行上限 + 用户取消（整组进程都死）照常通知 ----
j3 = run(start("sleep 30 & sleep 30; wait"))
j4 = run(start("sleep 30"))
try:
    run(start("echo 第三个"))
    raise AssertionError("limit not enforced")
except jobs.JobError as e:
    assert "上限 2" in str(e), e
time.sleep(0.3)
pg = _pid(pid, j3)
r = c.post(f"/api/jobs/{j3}/cancel").json()
assert r["state"] == "cancelled" and r["followup"] == "pending", r
time.sleep(0.2)
try:
    os.killpg(pg, 0)
    raise AssertionError("process group survived cancel")
except ProcessLookupError:
    pass
assert c.post(f"/api/jobs/{j3}/cancel").json()["state"] == "cancelled"  # 再点一次：无事发生

# ---- 6. 模型自己取消：不通知 ----
async def tool(name, **args):
    async with SessionLocal() as db:
        return (await REGISTRY[name].run(ToolContext(db=db, project_id=pid, conversation_id=cid), **args)).content
out = run(tool("cancel_job", job_id=j4))
assert out.startswith("已取消") and run(job(j4)).followup == "none", (out, run(job(j4)).followup)
assert "已经结束" in run(tool("cancel_job", job_id=j4))
assert "只能取消本工作区" in run(tool("cancel_job", job_id="jnope"))

# ---- 7. 进程消失没留退出码 → worker 判 lost ----
j5 = run(start("sleep 30"))
time.sleep(0.3)
os.killpg(_pid(pid, j5), signal.SIGKILL); procs[j5].kill(); procs[j5].wait(5)  # 连 run.sh 一起没了（像容器重启）
async def tick():
    async with SessionLocal() as db:
        return await jobs.tick(db)
assert j5 in run(tick())
assert run(job(j5)).state == "lost"

# ---- 8. job_status：看过结论就不再通知；列表 ----
out = run(tool("job_status", job_id=j2))
assert "失败，退出码 3" in out and "缺依赖" in out, out
assert run(job(j2)).followup == "seen"
listing = run(tool("job_status"))
assert listing.count("\n") >= 4 and "「装依赖」" in listing and "已取消" in listing, listing
async def follow_count():
    async with SessionLocal() as db:
        return len((await db.scalars(select(Job).where(Job.followup == "pending"))).all())
assert run(follow_count()) == 2  # j3（用户取消）、j5（丢失）

# ---- 9. 原对话一轮没答完：先等；太久就放弃 ----
async def add_user(minutes_ago):
    async with SessionLocal() as db:
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks("还在吗"),
                       created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)))
        await db.commit()
run(add_user(0))
assert run(follow()) == 0 and run(follow_count()) == 2
jobs.FOLLOWUP_WAIT = 0  # 等太久了（真实是 10 分钟）
assert run(follow()) == 0 and run(job(j3)).followup == "skipped" and run(job(j5)).followup == "skipped"

# ---- 10. 对话删了：不接着说 ----
async def other_conv():
    async with SessionLocal() as db:
        conv = Conversation(title="临时", project_id=pid); db.add(conv); await db.commit()
        return conv.id
oc = run(other_conv())
j6 = run(start("echo hi", conv_id=oc))
wait_exit(j6)
assert c.get(f"/api/jobs/{j6}").json()["followup"] == "pending"
async def drop(conv_id):
    async with SessionLocal() as db:
        await db.delete(await db.get(Conversation, conv_id)); await db.commit()
run(drop(oc))
assert run(follow()) == 0 and run(job(j6)).followup == "none"

# ---- 11. .jobs 不是项目文件；接口列表 ----
(storage.project_dir(pid) / "train.py").write_text("print(1)")
names = [f["path"] for f in c.get(f"/api/projects/{pid}/files").json()]
assert names == ["train.py"], names
assert storage.project_file(pid, f".jobs/{j1}/log") is None
assert c.get(f"/api/projects/{pid}/files/.jobs/{j1}/log", params={"token": "x"}).status_code in (401, 403, 404)
assert ".jobs" not in run(tool("list_files"))
lst = c.get("/api/jobs", params={"project_id": pid}).json()
assert len(lst) == 6 and lst[0]["id"] == j6 and not c.get("/api/jobs", params={"running": True}).json(), lst
assert c.get("/api/jobs/jnope").status_code == 404

# ---- 12. 退出码约定：124 = 超时 ----
async def fake_timeout():
    async with SessionLocal() as db:
        jb = await db.get(Job, j6)
        (jobs.job_dir(jb) / "exit").write_text("124\n")
        (jobs.job_dir(jb) / "cancelled").unlink(missing_ok=True)
        return jobs.observe(jb)
assert run(fake_timeout()) == ("timed_out", 124)

print("smoke_jobs OK")
