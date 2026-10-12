# 冒烟：v1.28 活动时间线（app/activity.py）。模拟模型。
# 1) 一轮里每次工具调用记一步：tool.status 带完整 step（running → done/error），message.done 和库里的消息带 steps；
# 2) 摘要只取白名单参数：命令/路径/网址；write_file 的 content、stdin 不进时间线；
# 3) 退出码非 0 / 危险命令被拦 → error + 原因；审批被拒 → denied（没走到 running）；
# 4) 中途停止：还在跑的步骤落库为 stopped；
# 5) GET /api/conversations/{id} 回放得到同样的 steps；没用工具的回复不带 steps；
# 6) 迁移 0028 可降可升。
# 运行：python tests/smoke_activity.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import activity, llm, sandbox_client
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.auth import require_user
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message
from app.routes import conversations as rc
from fastapi import FastAPI
from fastapi.testclient import TestClient

script: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    step = script.pop(0)
    async def gen():
        if isinstance(step, list):  # 一步里多个工具调用
            yield chunk(tool=[NS(index=i, id=f"c{len(script)}-{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()

async def fake_stream(project_id, command, timeout=60, stdin=None):
    if command == "hang":
        yield {"type": "out", "data": "…\n"}
        await asyncio.sleep(3600)
    yield {"type": "exit", "exit_code": 1 if command.startswith("false") else 0, "timed_out": False, "output": "ok\n"}
sandbox_client.stream = fake_stream

async def seed():
    async with SessionLocal() as db:
        conv = Conversation(title="时间线"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("整理一下")))
        await db.commit()
        return conv.id
cid = asyncio.run(seed())

events = []
async def emit(ev):
    events.append(ev)
async def turn(**kw):
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=emit, **kw)

# ---- 1–3. 一轮四步 ----
SECRET = "我的密码是 hunter2"
script.extend([
    [("run_command", {"command": "ls -la\n  data"}), ("write_file", {"path": "notes/a.md", "content": SECRET})],
    [("run_command", {"command": "false && echo"}), ("run_command", {"command": "rm -rf /"}), ("run_command", {"command": "git push"})],
    "好了。"])
reply = asyncio.run(turn())
steps = reply.steps
assert [s["state"] for s in steps] == ["done", "done", "error", "error", "denied"], steps
assert [s["title"] for s in steps] == ["运行命令", "写文件", "运行命令", "运行命令", "运行命令"], steps
assert steps[0]["detail"] == "ls -la data" and steps[1]["detail"] == "notes/a.md", steps  # 换行压成一行
assert SECRET not in json.dumps(steps, ensure_ascii=False)
assert steps[2]["note"] == "退出码 1" and steps[3]["note"] == "危险命令，已拦下", steps
assert steps[4]["note"] == "你没有批准" and "ms" in steps[4], steps
assert all(isinstance(s["ms"], int) and s["at"].endswith("+00:00") for s in steps), steps
assert "note" not in steps[0]
st = [e for e in events if e["type"] == "tool.status"]
assert st[0]["state"] == "running" and st[0]["step"]["state"] == "running" and "ms" not in st[0]["step"], st[0]
assert st[1]["state"] == "done" and st[1]["step"]["id"] == st[0]["id"], st[1]
assert [e["state"] for e in st if e["id"] == steps[4]["id"]] == ["denied"]  # 没批准：不经过 running
done = [e for e in events if e["type"] == "message.done"][-1]["message"]
assert done["steps"] == steps, done

# ---- 4. 中途停止 ----
events.clear()
async def stop_midway():
    stop = asyncio.Event()
    t = asyncio.create_task(turn(stop=stop))
    for _ in range(300):
        await asyncio.sleep(0.01)
        if any(e["type"] == "tool.status" and e["state"] == "running" for e in events):
            break
    else:
        raise AssertionError(events)
    await asyncio.sleep(0.05)
    stop.set(); t.cancel()
    return await t
script.extend([[("run_command", {"command": "hang"})]])
asyncio.run(stop_midway())
stopped = [e for e in events if e["type"] == "message.done"][-1]["message"]
assert stopped["status"] == "stopped" and [s["state"] for s in stopped["steps"]] == ["stopped"], stopped

# ---- 5. 回放 + 没用工具不带 steps ----
events.clear()
script.extend(["随便聊聊。"])
plain = asyncio.run(turn())
assert plain.steps == [] and "steps" not in plain.to_wire()
app = FastAPI(); app.include_router(rc.router)
app.dependency_overrides[require_user] = lambda: "u"
msgs = TestClient(app).get(f"/api/conversations/{cid}").json()["messages"]
assert msgs[1]["steps"] == steps and msgs[2]["steps"] == stopped["steps"] and "steps" not in msgs[3], msgs

# ---- 规则单测 ----
assert activity.title("正在打开网页") == "打开网页" and activity.title("搜索") == "搜索"
assert activity.detail({"paths": ["a", "b", "c", "d"]}) == "a、b、c 等 4 个"
assert activity.detail({"text": "密码", "ref": "e1"}) == ""
assert len(activity.detail({"command": "x" * 500})) == activity.DETAIL_MAX
rec = activity.Recorder()
for i in range(activity.KEEP + 5):
    rec.start(f"i{i}", "t", "正在做", {})
assert len(rec.steps) == activity.KEEP and rec.steps[0]["id"] == "i5"
assert rec.finish("nope", "done") is None

# ---- 6. 迁移 ----
for args in (["downgrade", "0027"], ["upgrade", "head"]):
    r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
print("smoke_activity ok")
