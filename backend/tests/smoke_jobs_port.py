# 冒烟：v1.39 后台任务对照 deepseek-harness packages/jobs 移植（MIT）：job_status 只给新输出（read_offset 游标、UTF-8 边界、
# 超长留尾巴 + 说清完整日志）；同一对话一起结束的任务并成一轮；叫醒轮数上限 + 用户发言并入（held）；模型取消不通知。迁移 0029。
# 沙盒服务用本机 bash 顶替（同 smoke_jobs）。运行：python tests/smoke_jobs_port.py
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
from app.config import settings
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

def run(coro):
    return asyncio.run(coro)

async def seed():
    async with SessionLocal() as db:
        p = Project(name="训练", emoji="🧪"); db.add(p); await db.flush()
        conv = Conversation(title="跑训练", project_id=p.id); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("把训练脚本放后台跑")))
        await db.flush()
        db.add(Message(conversation_id=conv.id, role="assistant", blocks=text_to_blocks("好，放后台了。")))
        await db.commit()
        return p.id, conv.id
pid, cid = run(seed())

async def job(jid):
    async with SessionLocal() as db:
        return await db.get(Job, jid)
async def tool(name, conv=None, **args):
    async with SessionLocal() as db:
        return (await REGISTRY[name].run(ToolContext(db=db, project_id=pid, conversation_id=conv or cid), **args)).content
async def start(cmd, conv_id=cid, **kw):
    async with SessionLocal() as db:
        return (await jobs.start(db, project_id=pid, command=cmd, conversation_id=conv_id, **kw)).id
async def follow():
    async with SessionLocal() as db:
        return await jobs.follow_ups(db)
async def tick():
    async with SessionLocal() as db:
        return await jobs.tick(db)
def wait_exit(jid, secs=10):
    end = time.time() + secs
    while time.time() < end:
        if (storage.project_dir(pid) / ".jobs" / jid / "exit").exists():
            return
        time.sleep(0.1)
    raise AssertionError("job never exited")
def log_of(jid):
    return storage.project_dir(pid) / ".jobs" / jid / "log"

# ---- 1. UTF-8 边界（移植 ring.spec.ts 的“尾巴永远不从码点中间开始”）----
zh = "中".encode()  # 3 字节
assert jobs.utf8_start(zh, 1) == 3 and jobs.utf8_start(zh, 0) == 0 and jobs.utf8_start(b"", 0) == 0
assert jobs.utf8_complete(b"ab" + zh[:2]) == 2 and jobs.utf8_complete(b"ab" + zh) == 5
assert jobs.utf8_complete("é".encode()[:1]) == 0 and jobs.utf8_complete(b"abc") == 3
emoji = "😀".encode()  # 4 字节
assert jobs.utf8_complete(emoji[:3]) == 0 and jobs.utf8_complete(emoji) == 4 and jobs.utf8_complete(b"") == 0

# ---- 2. read_new：只给游标之后（移植 tool-jobs.spec 的 consuming read）----
j = run(start("sleep 30"))
time.sleep(0.3)
jb = run(job(j))
lp = log_of(j)
lp.write_bytes("第一行\n".encode())
text, cur, dropped = jobs.read_new(jb, 100)
assert text == "第一行\n" and cur == len("第一行\n".encode()) and dropped == 0, (text, cur)
jb.read_offset = cur
assert jobs.read_new(jb, 100) == ("", cur, 0)  # 没有新输出
with lp.open("ab") as f:
    f.write("第二行".encode() + zh[:1])  # 任务正写到“中”的半截
text, cur2, _ = jobs.read_new(jb, 100)
assert text == "第二行" and cur2 == cur + len("第二行".encode()), (text, cur2)
jb.read_offset = cur2
with lp.open("ab") as f:
    f.write(zh[1:] + "\n".encode())
text, cur3, _ = jobs.read_new(jb, 100)
assert text == "中\n" and "\ufffd" not in text, text
# 进度帧折叠
jb.read_offset = cur3
with lp.open("ab") as f:
    f.write(b"10%\r50%\r100%\n")
assert jobs.read_new(jb, 100)[0] == "100%\n"
# 超长：只留尾巴 + 丢掉字节数如实；窗口从字中间切进来不出乱码
jb.read_offset = lp.stat().st_size
big = "".join(f"行{i:04d}中文内容\n" for i in range(2000))
with lp.open("ab") as f:
    f.write(big.encode())
text, cur4, dropped = jobs.read_new(jb, 300)
assert len(text) <= 300 and text.startswith("行") and text.endswith("行1999中文内容\n"), text[:40]
assert "\ufffd" not in text and dropped > 0 and cur4 == lp.stat().st_size, dropped
assert dropped + len(text.encode()) == len(big.encode()), (dropped, len(text.encode()), len(big.encode()))
# 日志比游标短（被重建）→ 从头读
jb.read_offset = 10 ** 9
lp.write_bytes(b"fresh\n")
assert jobs.read_new(jb, 100) == ("fresh\n", 6, 0)
jb.read_offset = 0
lp.unlink()
assert jobs.read_new(jb, 100) == ("", 0, 0)
lp.write_bytes(b"")

# ---- 3. job_status：第一次给全部，第二次只给新的，tail=true 重看 ----
lp.write_bytes("epoch 1 loss=0.9\n".encode())
out = run(tool("job_status", job_id=j))
assert "输出：\nepoch 1 loss=0.9" in out and "上次查看" not in out, out
out = run(tool("job_status", job_id=j))
assert "上次查看之后的新输出：\n（没有新输出）" in out, out
with lp.open("ab") as f:
    f.write(b"epoch 2 loss=0.5\n")
out = run(tool("job_status", job_id=j))
assert "epoch 2 loss=0.5" in out and "epoch 1" not in out, out
out = run(tool("job_status", job_id=j, tail=True))
assert "最近的输出：\nepoch 1 loss=0.9\nepoch 2 loss=0.5" in out, out
with lp.open("ab") as f:
    f.write(("x" * 100 + "\n").encode() * 50)
out = run(tool("job_status", job_id=j, chars=200))
assert "前面还有约" in out and f".jobs/{j}/log" in out and "read_file" in out, out[-200:]
assert "没有新输出" in run(tool("job_status", job_id=j))
run(tool("cancel_job", job_id=j))
assert run(job(j)).followup == "none"

# ---- 4. 同一对话一起结束的任务并成一轮通知（tool-jobs：一起结束只花一步）----
ja = run(start("echo 甲完成"))
jb2 = run(start("echo 乙完成; exit 2"))
wait_exit(ja); wait_exit(jb2)
run(tick())
assert run(job(ja)).followup == "pending" and run(job(jb2)).followup == "pending"
script.append("两个任务都结束了：甲成功，乙失败（退出码 2）。")
n0 = len(seen)
assert run(follow()) == 1 and len(seen) == n0 + 1  # 一轮，一次模型调用
note = [m for m in seen[-1] if m["role"] == "user"][-1]["content"]
assert "2 个任务都已结束" in note and "甲完成" in note and "乙完成" in note and "退出码 2" in note, note
A, B = run(job(ja)), run(job(jb2))
assert A.followup == B.followup == "done" and A.followup_at == B.followup_at and A.followup_at is not None
assert A.read_offset == log_of(ja).stat().st_size  # 通知里给过了，job_status 不重复
assert "没有新输出" in run(tool("job_status", job_id=ja))

# ---- 5. 叫醒上限（移植 maxConsecutiveWakes：用户发言前最多连着叫醒 N 轮，用户一说话就重置）----
settings.job_followup_wakes = 3  # 已经叫醒过 1 轮（第 4 段）
for i in range(2):
    jx = run(start(f"echo 第{i}轮"))
    wait_exit(jx); run(tick())
    script.append(f"第{i}轮结束了。")
    assert run(follow()) == 1
jh = run(start("echo 被压下的结论 acc=0.97"))
wait_exit(jh); run(tick())
n0 = len(seen)
assert run(follow()) == 0 and len(seen) == n0 and run(job(jh)).followup == "held"  # 第 4 轮不叫醒，不调模型
assert run(follow()) == 0 and run(job(jh)).followup == "held"
# 用户说话：压下的结论并进那一轮的系统提示，置 done（不占叫醒轮数）
async def user_turn(text):
    async with SessionLocal() as db:
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks(text)))
        await db.commit()
        conv = await db.get(Conversation, cid)
        return await run_turn(db, conv)
script.append("结果是 0.97。")
run(user_turn("结果怎么样"))
system = seen[-1][0]["content"]
assert seen[-1][0]["role"] == "system" and "被压下的结论 acc=0.97" in system and "没再打扰用户" in system, system[-300:]
H = run(job(jh))
assert H.followup == "done" and H.followup_at is None
script.append("again")
run(user_turn("再说一次"))
assert "被压下的结论" not in seen[-1][0]["content"]  # 只给一次
# 用户说过话 → 预算重置，又能叫醒
jr = run(start("echo 重置后"))
wait_exit(jr); run(tick())
script.append("重置后结束了。")
assert run(follow()) == 1 and run(job(jr)).followup == "done"
# held 时模型自己用 job_status 看了 → seen，用户那一轮不再重复
settings.job_followup_wakes = 1
js = run(start("echo 自己看过"))
wait_exit(js); run(tick())
assert run(follow()) == 0 and run(job(js)).followup == "held"
assert "自己看过" in run(tool("job_status", job_id=js)) and run(job(js)).followup == "seen"
script.append("ok")
run(user_turn("嗯"))
assert "自己看过" not in seen[-1][0]["content"]
# 0 = 不限
settings.job_followup_wakes = 0
for i in range(3):
    jz = run(start(f"echo 不限{i}"))
    wait_exit(jz); run(tick())
    script.append("ok")
    assert run(follow()) == 1
settings.job_followup_wakes = 3

# ---- 6. 模型自己取消的不通知（tool-jobs killedByModel）；日志没了用结算尾巴 ----
jk = run(start("sleep 30"))
time.sleep(0.3)
assert run(tool("cancel_job", job_id=jk)).startswith("已取消") and run(job(jk)).followup == "none"
jg = run(start("echo 尾巴还在"))
wait_exit(jg); run(tick())
log_of(jg).unlink()
assert "尾巴还在" in run(tool("job_status", job_id=jg))

# ---- 7. 迁移 0029 可降可升 ----
for args in (["downgrade", "0028"], ["upgrade", "head"]):
    r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
print("smoke_jobs_port OK")
