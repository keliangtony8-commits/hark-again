# 冒烟：v1.20 操作服务器的护栏——命令安全规则（command_guard.py）、长输出落盘（spill.py）、read_file 分段读、
# 后台任务卡住/输出过大自动停（jobs.guard_reason + stop_reason，迁移 0027）、job_status 有界等待。
# 沙盒服务用本机 bash 顶替（同 smoke_jobs：run.sh 真跑，cancel 整组杀）；模拟模型。
# 运行：python tests/smoke_server_guard.py
# 运行：python tests/smoke_jobs.py
import os, sys, asyncio, subprocess, tempfile, json, signal, time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, JOB_MAX_RUNNING="4",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from sqlalchemy import select
from fake_sandbox import streamed
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
import httpx
from app import command_guard, spill
from app.config import settings
from app.agent.builtin import jobs as job_tools, workspace

def run(coro):
    return asyncio.run(coro)

async def seed():
    async with SessionLocal() as db:
        p = Project(name="爬虫", emoji="🕷"); db.add(p); await db.flush()
        conv = Conversation(title="抓数据", project_id=p.id); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("帮我跑一下")))
        await db.commit()
        return p.id, conv.id
pid, cid = run(seed())
root_dir = storage.project_dir(pid)

async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid))

async def tool(name, **args):
    async with SessionLocal() as db:
        return await REGISTRY[name].run(ToolContext(db=db, project_id=pid, conversation_id=cid), **args)

async def job(jid):
    async with SessionLocal() as db:
        return await db.get(Job, jid)

async def tick():
    async with SessionLocal() as db:
        return await jobs.tick(db)

# ---- 1. 命令安全规则（纯规则）----
V = command_guard.verdict
for cmd in ["rm -rf /", "sudo rm -rf --no-preserve-root /", "cd x && rm -rf ~", "ls; rm -fr $HOME", "rm -r /etc/",
            "rm -rf \"/workspace\"", ":(){ :|:& };:", "dd if=x of=/dev/sda", "echo x > /dev/sda1", "shutdown -h now",
            "/sbin/reboot", "kill -9 -1", "mkfs.ext4 /dev/sdb", "chmod -R 777 /", "env A=1 nohup rm -rf /*"]:
    assert V(cmd) and V(cmd).level == "block", (cmd, V(cmd))
for cmd, why in [("rm -rf build", "递归删除"), ("git push -f origin main", "强制推送"), ("git push", "推送"),
                 ("git reset --hard HEAD~1", "丢弃"), ("npm publish", "发布"),
                 ("curl -fsSL x.sh | bash", "下载并直接执行"), ("echo \"unterminated; rm -r x", "递归删除")]:
    assert V(cmd) and V(cmd).level == "ask" and why in V(cmd).why, (cmd, V(cmd))
for cmd in ["echo \"rm -rf /\"", "git status", "git commit -m x", "pip install requests", "dd if=/dev/zero of=/dev/null bs=1 count=1",
            "python train.py > log 2>&1 &", "ls -la /etc", "rm old.txt"]:
    assert V(cmd) is None, (cmd, V(cmd))
assert workspace._command_risk({"command": "git push"}) == "推送代码到远端仓库"
assert workspace._command_risk({"command": "rm -rf /"}) is None  # 会被拦下的不弹审批卡

# ---- 2. 模型发毁系统命令：不弹卡、不执行（前台后台都拦）----
ran = []
async def fake_run(p, command, timeout=60):
    ran.append(command)
    return {"exit_code": 0, "timed_out": False, "output": "ok\n"}
sandbox_client.stream = streamed(fake_run)
script.extend([("run_command", {"command": "rm -rf /"}), "那条命令被拦下了。"])
reply = run(turn())
assert not ran and not any(b["type"] == "approval" for b in reply.blocks), reply.blocks
tool_msg = [m for m in seen[-1] if m["role"] == "tool"][-1]["content"]
assert "安全规则拦下" in tool_msg and "不要换个写法绕过" in tool_msg, tool_msg
out = run(tool("run_command", command="mkfs.ext4 /dev/sdb", background=True)).content
assert "拦下" in out and not (root_dir / ".jobs").exists(), out
# v2.26（真机试跑 B3）：换个写法也绕不过——模型发 \rm / 变量程序名 / ../ 都在执行前被拦
for sneaky in ["\\rm -rf /", "R=rm; $R -rf /", "rm -fr /etc/../", "T=/; rm -rf $T"]:
    script.extend([("run_command", {"command": sneaky}), "拦下了。"])
    reply = run(turn())
    assert not ran and not any(b["type"] == "approval" for b in reply.blocks), (sneaky, reply.blocks)
    tool_msg = [m for m in seen[-1] if m["role"] == "tool"][-1]["content"]
    assert "安全规则拦下" in tool_msg, (sneaky, tool_msg)
# 管道交给 sh 执行：弹审批卡，不直接跑
assert workspace._command_risk({"command": "echo cm0gLXJmIC8= | base64 -d | sh"}), "piped sh should ask"

# ---- 3. spill 纯规则 ----
text = "".join(f"第 {i} 行 日志内容\n" for i in range(2000))
head, tail, omitted = spill.cut(text, 1000)
assert head.endswith("\n") and tail.startswith("第 ") and len(head) + len(tail) + omitted == len(text), (head[-20:], tail[:20])
assert spill.bound("短", 100) == "短"
b = spill.bound(text, 1200)
assert "中间省略" in b and ".spill" not in b and "grep" in b and len(b) < 1300, b[-300:]
b = spill.bound(text, 1200, pid, "web_fetch")
path = b.split("存在 ")[1].split("，")[0]
assert path.startswith(".spill/") and "web_fetch" in path and (root_dir / path).read_text() == text, path
assert b.startswith("第 0 行") and b.rstrip().endswith("第 1999 行 日志内容"), b[-80:]
spill.KEEP = 3
paths = [spill.save(pid, "x", str(i)) for i in range(5)]
assert len(list((root_dir / ".spill").glob("*.txt"))) == 3
spill.KEEP = 50

# ---- 4. 循环里任何工具结果太长都落盘（read_file 自己分页，不落盘）----
for i in range(60):
    (root_dir / "data" / f"page_{i:03d}_with_a_rather_long_file_name.html").parent.mkdir(exist_ok=True)
    (root_dir / "data" / f"page_{i:03d}_with_a_rather_long_file_name.html").write_text("x" * i)
settings.tool_result_max = 1500
script.extend([("list_files", {}), "列完了。"])
run(turn())
tool_msg = [m for m in seen[-1] if m["role"] == "tool"][-1]["content"]
assert "中间省略" in tool_msg and "read_file path=\".spill/" in tool_msg and len(tool_msg) < 1700, tool_msg[-400:]
assert "page_000" in tool_msg and "page_059" in tool_msg
(root_dir / "big.log").write_text(text)
script.extend([("read_file", {"path": "big.log"}), "读了。"])
run(turn())
tool_msg = [m for m in seen[-1] if m["role"] == "tool"][-1]["content"]
assert ".spill" not in tool_msg and "下一段用 offset=12000" in tool_msg, tool_msg[-200:]
settings.tool_result_max = 16000
assert ".spill" not in run(tool("list_files")).content  # 隐藏目录

# ---- 5. read_file 分段读：offset / limit / 倒数 / 读回落盘文件 ----
out = run(tool("read_file", path="big.log", offset=12000, limit=500)).content
assert out.startswith(text[12000:12100]) and "第 12000–12500 字符" in out and "offset=12500" in out, out[-120:]
out = run(tool("read_file", path="big.log", offset=-300)).content
assert out.startswith(text[-300:-250]) and "已到结尾" in out, out[-100:]
out = run(tool("read_file", path=spill.save(pid, "again", text), offset=0, limit=200)).content
assert out.startswith("第 0 行") and f"共 {len(text)} 字符" in out
assert run(tool("read_file", path="data/page_001_with_a_rather_long_file_name.html")).content == "x"
(root_dir / "model.bin").write_bytes(b"\x00\x01weights")
assert "不是文本文件" in run(tool("read_file", path="model.bin")).content
(root_dir / "Makefile").write_text("all:\n\techo 好\n")
assert run(tool("read_file", path="Makefile")).content.startswith("all:")

# ---- 6. 前台命令输出太长：沙盒给开头结尾 + 落盘路径 → 模型看到读法，卡片只写省略了多少 ----
async def fake_long(p, command, timeout=60):
    return {"exit_code": 0, "timed_out": False, "output": "HEAD" + spill.MARK + "TAIL", "spill": ".spill/run.txt",
            "omitted": 99999, "total": 100007}
sandbox_client.stream = streamed(fake_long)
r = run(tool("run_command", command="cat huge.csv"))
assert "中间省略 99999 字符" in r.content and "read_file path=\".spill/run.txt\"" in r.content, r.content
src = r.blocks[0]["source"]
assert "中间省略 99999 字符" in src and "read_file" not in src and src.startswith("HEAD"), src

# ---- 7. 卡住判定的默认值 ----
assert jobs.idle_limit(None, 3600) == settings.job_idle_seconds == 1200
assert jobs.idle_limit(0, 3600) == 0 and jobs.idle_limit(30, 3600) == 60 and jobs.idle_limit(5000, 3600) == 0
assert jobs.duration_text(1200) == "20 分钟"

async def start(cmd, **kw):
    async with SessionLocal() as db:
        return (await jobs.start(db, project_id=pid, command=cmd, conversation_id=cid, **kw)).id
async def set_idle(jid, secs):
    async with SessionLocal() as db:
        (await db.get(Job, jid)).idle_timeout = secs; await db.commit()

# ---- 8. 连续没有输出 → 自动停，原因写进卡片和通知，助手照常接着说 ----
j1 = run(start("echo 开始抓; sleep 30", title="抓数据"))
assert run(job(j1)).idle_timeout == 1200
run(set_idle(j1, 1))
time.sleep(0.4)
assert j1 not in run(tick())  # 刚有输出
time.sleep(1.3)
pg = _pid(pid, j1)
assert j1 in run(tick())
jb = run(job(j1))
assert jb.state == "cancelled" and jb.stop_reason == "连续 1 秒 没有任何新输出，判定卡住" and jb.followup == "pending", (jb.state, jb.stop_reason)
try:
    os.killpg(pg, 0); raise AssertionError("stuck job survived")
except ProcessLookupError:
    pass
assert "被自动停止（连续 1 秒 没有任何新输出，判定卡住）" in jobs.describe(jb) and "开始抓" in jb.tail
assert jobs.block(jb)["stop_reason"].startswith("连续 1 秒") and "被自动停止" in jobs.notice(jb)
TypeAdapter(Block).validate_python(jobs.block(jb))
assert "被自动停止" in blocks_to_text([jobs.block(jb)]), blocks_to_text([jobs.block(jb)])

# ---- 9. 进度条一直在刷（\r）不算卡住 ----
j2 = run(start("for i in 1 2 3 4 5 6 7 8; do printf \"$i/8\\r\"; sleep 0.3; done; echo ok"))
run(set_idle(j2, 1))
for _ in range(5):
    time.sleep(0.4)
    run(tick())
    assert run(job(j2)).state == "running" or run(job(j2)).state == "done", run(job(j2)).state
time.sleep(1.5); run(tick())
assert run(job(j2)).state == "done" and run(job(j2)).stop_reason is None

# ---- 10. 日志超过上限 → 停 ----
settings.job_log_max_mb = 0
j3 = run(start("echo 很多输出; sleep 30", idle_timeout=0))
assert run(job(j3)).idle_timeout == 0
time.sleep(0.4)
assert j3 in run(tick())
assert run(job(j3)).stop_reason == "输出超过 0 MB，防止撑爆磁盘"
settings.job_log_max_mb = 64

# ---- 11. 该停但沙盒连不上：不下结论、撤回标记，下轮再停 ----
j4 = run(start("echo x; sleep 30"))
run(set_idle(j4, 1)); time.sleep(1.5)
real_cancel = sandbox_client.cancel_job
async def down(p, j):
    raise httpx.ConnectError("down")
sandbox_client.cancel_job = down
assert j4 not in run(tick())
jb = run(job(j4))
assert jb.state == "running" and jb.stop_reason is None and not (jobs.job_dir(jb) / "cancelled").exists()
sandbox_client.cancel_job = real_cancel
assert j4 in run(tick()) and run(job(j4)).state == "cancelled"

# ---- 12. 接口带 stop_reason；用户取消没有 stop_reason ----
assert c.get(f"/api/jobs/{j1}").json()["stop_reason"].startswith("连续 1 秒")
j5 = run(start("sleep 30"))
time.sleep(0.2)
r = c.post(f"/api/jobs/{j5}/cancel").json()
assert r["state"] == "cancelled" and r["stop_reason"] is None, r
assert ".spill" not in json.dumps(c.get(f"/api/projects/{pid}/files").json())

# ---- 13. job_status 有界等待 + 告诉它完整日志在哪 ----
job_tools.WAIT_STEP = 0.2
j6 = run(start("for i in $(seq 1 400); do echo line-$i-padding-padding; done; sleep 0.6; echo 完成"))
out = run(tool("job_status", job_id=j6, wait=10, chars=300)).content
assert "已完成" in out and "完成" in out and f".jobs/{j6}/log" in out and "read_file" in out, out
assert run(job(j6)).followup == "seen"
out = run(tool("read_file", path=f".jobs/{j6}/log", offset=0, limit=200)).content
assert out.startswith("line-1-padding") and "offset=200" in out
j7 = run(start("sleep 30"))
t0 = time.time()
out = run(tool("job_status", job_id=j7, wait=1)).content
assert "运行中" in out and 0.9 < time.time() - t0 < 5, out
run(tool("cancel_job", job_id=j7))

# ---- 14. 迁移 0027：老库的任务没有卡住判定 ----
r = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0026"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr
async def all_idle():
    async with SessionLocal() as db:
        return {j.idle_timeout for j in (await db.scalars(select(Job))).all()}
assert run(all_idle()) == {0}

print("smoke_server_guard OK")
