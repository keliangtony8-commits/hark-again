# 冒烟：v1.21 主聊天也有“电脑”——个人工作区（app/workspaces.py，id = "me"）。
# 覆盖：主聊天的模型拿到文件/命令/后台任务工具（项目专属的 project 工具没有）；系统提示有个人工作区那句；
# write_file / read_file / list_files 落在 data/projects/me；run_command 前台把 "me" 交给沙盒；后台任务记在 me 名下，
# /api/jobs?project_id=me 列得出；job_status 只看本工作区（看不到项目的任务，项目也看不到我的）；
# 长输出落盘到 me/.spill；/api/projects/me/files 列出文件、能上传/下载/删除，不存在的项目 id 404 且不建目录；
# 主聊天消息能引用“我的文件”（project_files），客户端误传 project_id="me" 也不会把对话挂到一个假项目上；
# 定时任务（无项目）同样在个人工作区。模拟模型，无迁移（Job.project_id 存的就是工作区 id）。
# 运行：python tests/smoke_personal_workspace.py
import os, sys, asyncio, subprocess, tempfile, json, signal, time
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', TOOL_RESULT_MAX="2000")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fake_sandbox import streamed
from app import jobs, llm, sandbox_client, storage, workspaces
from app.agent import context
from app.agent.runner import run_turn
from app.agent.tools import REGISTRY, ToolContext, load_builtin, schemas
from app.auth import require_user, require_query_token
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Job, Message, Project
from app.routes import files as rf, jobs as rj
from app.routes import ws as rws

# ---- 本机顶替沙盒服务：记下收到的工作区 id ----
calls: list = []
procs: dict = {}
async def fake_run(pid, command, timeout=60):
    calls.append(("exec", pid, command))
    if command == "big":
        return {"output": "A" * 50 + "\n…[省略]…\n" + "Z" * 50, "exit_code": 0, "timed_out": False}
    return {"output": f"ran in {pid}\n", "exit_code": 0, "timed_out": False}
async def start_job(pid, jid):
    calls.append(("start", pid, jid))
    procs[jid] = subprocess.Popen(["bash", f".jobs/{jid}/run.sh"], cwd=storage.project_dir(pid), start_new_session=True)
async def job_alive(pid, jid):
    return procs[jid].poll() is None
async def cancel_job(pid, jid):
    os.killpg(procs[jid].pid, signal.SIGTERM); procs[jid].wait(10)
sandbox_client.stream, sandbox_client.start_job, sandbox_client.job_alive, sandbox_client.cancel_job = streamed(fake_run), start_job, job_alive, cancel_job

# ---- 模拟模型 ----
script: list = []
seen: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append({"messages": messages, "tools": [t["function"]["name"] for t in tools or []]})
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
app.dependency_overrides[require_query_token] = lambda: "u"
c = TestClient(app)
run = asyncio.run
ME = workspaces.PERSONAL

# ---- 纯规则 ----
assert workspaces.of(None) == ME and workspaces.of("") == ME and workspaces.of("abc") == "abc"
assert ME not in "0123456789abcdef"  # 不可能和 32 位十六进制的项目 id 撞
for name in ("list_files", "read_file", "write_file", "run_command", "job_status", "cancel_job"):
    assert REGISTRY[name].scope == "always", name
assert REGISTRY["update_project_brief" if "update_project_brief" in REGISTRY else next(
    n for n, t in REGISTRY.items() if t.scope == "project")].scope == "project"

async def seed():
    async with SessionLocal() as db:
        p = Project(name="训练", emoji="🧪"); db.add(p); await db.flush()
        main = Conversation(title="主聊天"); proj = Conversation(title="项目里", project_id=p.id)
        db.add_all([main, proj]); await db.flush()
        for cv in (main, proj):
            db.add(Message(conversation_id=cv.id, role="user", blocks=text_to_blocks("帮我算一下")))
        await db.commit()
        return p.id, main.id, proj.id
pid, mid, prid = run(seed())

async def turn(conv_id):
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, conv_id))

# ---- 1. 主聊天：工具齐、系统提示有工作区那句 ----
script.extend([("write_file", {"path": "算/结果.txt", "content": "42"}), "写好了。"])
reply = run(turn(mid))
tools = seen[-1]["tools"]
assert {"list_files", "read_file", "write_file", "run_command", "job_status", "cancel_job"} <= set(tools), tools
assert not any(REGISTRY[t].scope == "project" for t in tools), tools
system = seen[-1]["messages"][0]["content"]
assert "个人工作区" in system and "我的文件" in system, system
assert (storage.PROJECTS / ME / "算" / "结果.txt").read_text() == "42"
assert not any(b["type"] == "file" for b in reply.blocks), reply.blocks  # v1.22：写文件不再出卡，交付走 display_file
async def proj_prompt():
    async with SessionLocal() as db:
        return (await context.build_system_prompt(db, pid)).text()
assert "个人工作区" not in run(proj_prompt()) and "项目工作区" in run(proj_prompt())

# ---- 2. 前台命令把 "me" 交给沙盒；项目对话交项目 id ----
script.extend([("run_command", {"command": "python3 -c 'print(6*7)'"}), "42。"])
run(turn(mid))
assert calls[-1] == ("exec", ME, "python3 -c 'print(6*7)'"), calls
tool_msg = [m for m in seen[-1]["messages"] if m["role"] == "tool"][-1]  # 前面可能有上一轮重放的工具轨迹（v1.55）
assert f"ran in {ME}" in tool_msg["content"], tool_msg
script.extend([("run_command", {"command": "ls"}), "好。"])
run(turn(prid))
assert calls[-1][:2] == ("exec", pid), calls

# ---- 3. 后台任务记在 me 名下；job_status 各看各的 ----
script.extend([("run_command", {"command": "echo hi; sleep 0.3; echo bye", "background": True, "title": "小活"}), "在后台跑了。"])
reply = run(turn(mid))
jid = next(b for b in reply.blocks if b["type"] == "job")["id"]
assert ("start", ME, jid) in calls
procs[jid].wait(10)
rows = c.get("/api/jobs", params={"project_id": ME}).json()
assert [r["id"] for r in rows] == [jid] and rows[0]["project_id"] == ME, rows
assert c.get("/api/jobs", params={"project_id": pid}).json() == []
async def status(project_id, job_id=""):
    async with SessionLocal() as db:
        return (await REGISTRY["job_status"].run(ToolContext(db=db, project_id=project_id), job_id=job_id)).content
assert "小活" in run(status(None)) and "bye" in run(status(None, jid))
assert "只能看本工作区的" in run(status(pid, jid)) and "还没有后台任务" in run(status(pid))
assert not (storage.PROJECTS / pid / ".jobs").exists()

# ---- 4. 长输出落盘在 me/.spill ----
async def big_listing():
    async with SessionLocal() as db:
        from app.agent import loop
        for i in range(400):
            (storage.project_dir(ME) / "many").mkdir(exist_ok=True)
            (storage.project_dir(ME) / "many" / f"f{i:03}.txt").write_text("x")
script.extend([("list_files", {"path": "many"}), "很多文件。"])
run(big_listing()); run(turn(mid))
tool_msg = [m for m in seen[-1]["messages"] if m["role"] == "tool"][-1]["content"]
assert ".spill/" in tool_msg, tool_msg[-400:]
assert any((storage.PROJECTS / ME / ".spill").iterdir())

# ---- 5. 文件接口：me 可列/传/下/删；不存在的项目 404 且不建目录 ----
names = [f["path"] for f in c.get(f"/api/projects/{ME}/files").json()]
assert "算/结果.txt" in names and not any(n.startswith((".jobs", ".spill")) for n in names), names[:5]
assert c.post(f"/api/projects/{ME}/files", files={"file": ("笔记.md", b"# hi")}).status_code == 200
assert c.get(f"/api/projects/{ME}/files/笔记.md").content == b"# hi"
assert c.delete(f"/api/projects/{ME}/files/笔记.md").status_code == 200
assert not (storage.PROJECTS / ME / "笔记.md").exists()
assert c.get("/api/projects/nope123/files").status_code == 404
assert c.post("/api/projects/nope123/files", files={"file": ("a.txt", b"x")}).status_code == 404
assert not (storage.PROJECTS / "nope123").exists()
assert c.get(f"/api/projects/{pid}/files").status_code == 200

# ---- 6. 主聊天引用“我的文件”；误传 project_id="me" 不会建出挂在假项目上的对话 ----
async def refs(conv_id, paths, event_pid=None):
    async with SessionLocal() as db:
        conv = await db.get(Conversation, conv_id) if conv_id else None
        return await rws._project_files(db, conv.project_id if conv else event_pid, paths, 10)
got = run(refs(mid, ["算/结果.txt", "../etc/passwd", ".jobs/x/log", "算/结果.txt"]))
assert [(b["id"], b["project_id"]) for b in got] == [("算/结果.txt", ME)], got
assert run(refs(prid, ["算/结果.txt"])) == []  # 项目对话只认项目自己的文件
text = context._render([{"type": "text", "text": "看看"}] + got)
assert "个人工作区文件 算/结果.txt" in text and "42" in text, text
events: list = []
async def emit(ev):
    events.append(ev)
script.append("看到了，是 42。")
async def send_new():
    stop = asyncio.Event()
    await rws._handle_user_message(emit, {"text": "读一下", "project_id": ME, "project_files": ["算/结果.txt"]}, stop)
run(send_new())
new_id = next(e for e in events if e["type"] == "message.start")["conversation_id"]
async def conv_of(cid):
    async with SessionLocal() as db:
        cv = await db.get(Conversation, cid)
        msgs = (await db.execute(__import__("sqlalchemy").select(Message).where(Message.conversation_id == cid))).scalars().all()
        return cv.project_id, [b for m in msgs for b in m.blocks if b["type"] == "file"]
proj_of_new, files_new = run(conv_of(new_id))
assert proj_of_new is None and files_new and files_new[0]["project_id"] == ME, (proj_of_new, files_new)

# ---- 7. 定时任务（无项目）也在个人工作区 ----
async def task_ctx():
    async with SessionLocal() as db:
        ctx = ToolContext(db=db, project_id=None, task_id="t1")
        return ctx.workspace, [s["function"]["name"] for s in schemas(ctx)]
ws, names = run(task_ctx())
assert ws == ME and "run_command" in names
print("OK smoke_personal_workspace")
