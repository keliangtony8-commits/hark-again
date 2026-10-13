# 冒烟：v2.54 E2E 第十轮 B24 缺密钥类环境变量 → request_env，不拿示例 Key 试（app/missing_env.py 唯一规则）。无迁移。
# 1) 规则：中文“缺少环境变量 X”、Python KeyError（有 environ 才算）、Node process.env、shell unbound、英文 not set / is required；
#    非密钥名（PORT）、系统变量、已在保险箱的不认；去重保序、SHOW 个；
# 2) run_command 失败结果带 ⚠（一轮模拟模型）；成功不带；jobs.describe 失败任务读日志尾部带 ⚠。
# 运行：python tests/smoke_missing_env.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
root = os.path.join(os.path.dirname(__file__), "..")
image = os.path.join(root, "..", "sandbox", "image")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from app import missing_env as me, command_env
R = command_env.RESERVED
assert me.names("缺少环境变量 OPENWEATHER_KEY") == ["OPENWEATHER_KEY"]
assert me.names("Traceback...\n  key = os.environ['TG_BOT_TOKEN']\nKeyError: 'TG_BOT_TOKEN'") == ["TG_BOT_TOKEN"]
assert me.names("KeyError: 'API_KEY'") == []  # 普通字典
assert me.names("TypeError: process.env.OPENAI_API_KEY is undefined") == ["OPENAI_API_KEY"]
assert me.names("run.sh: line 3: SLACK_TOKEN: unbound variable") == ["SLACK_TOKEN"]
assert me.names("Error: DEEPL_AUTH_KEY is not set\nError: DEEPL_AUTH_KEY is not set") == ["DEEPL_AUTH_KEY"]
assert me.names("Please set the AMAP_KEY environment variable") == ["AMAP_KEY"]
assert me.names("Error: environment variable GITHUB_TOKEN is required".replace("environment variable GITHUB_TOKEN is required", "GITHUB_TOKEN is required")) == ["GITHUB_TOKEN"]
assert me.names("PORT is not set, using 8000") == []
assert me.names("缺少环境变量 OPENWEATHER_KEY", have={"OPENWEATHER_KEY"}) == []
assert me.names("missing PASS", reserved=frozenset({"PASS"})) == []
assert me.names("") == [] and me.note(None) == "" and me.note("all good") == ""
n = me.note("缺少 A_KEY；缺少 B_TOKEN；缺少 C_SECRET；缺少 D_PASSWORD")
assert n.count("$") == 3 and 'request_env(name="A_KEY"' in n and n.endswith("\n") and "聊天里" in n, n
FAIL = "缺少环境变量 OPENWEATHER_KEY\n"
# 2) run_command
from app import jobs, llm, sandbox_client
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Job, Message, Project
load_builtin()
async def fake_stream(project_id, command, timeout=60, stdin=None, env=None, promote=None, **kw):
    yield {"type": "out", "data": FAIL}
    yield {"type": "exit", "exit_code": 1, "timed_out": False, "output": FAIL}
sandbox_client.stream = fake_stream

async def seed():
    async with SessionLocal() as db:
        p = Project(name="天气", emoji="☁"); db.add(p); await db.flush()
        conv = Conversation(title="t", project_id=p.id); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("运行一下 weather.py，告诉我杭州现在多少度")))
        await db.commit(); return p.id, conv.id
pid, cid = asyncio.run(seed())
seen, script = [], []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append([dict(m) for m in messages])
    step = script.pop(0)
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"c{len(script)}-{i}", function=NS(name=n, arguments=json.dumps(a)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
script.extend([[("run_command", {"command": "python3 weather.py"})], "要你的 Key。"])
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))
reply = asyncio.run(turn())
tool_msg = next(m for m in seen[1] if m["role"] == "tool")
assert "⚠ 程序缺用户自己的密钥 $OPENWEATHER_KEY" in tool_msg["content"] and 'request_env(name="OPENWEATHER_KEY"' in tool_msg["content"], tool_msg["content"]
assert "示例 Key" in tool_msg["content"]
assert reply.steps[0]["tool"] == "run_command"

async def jobcase():
    async with SessionLocal() as db:
        j = Job(id="je1", project_id=pid, conversation_id=cid, command="python3 weather.py", title="天气", state="running", timeout=600)
        db.add(j); await db.commit()
        d = jobs.job_dir(j); d.mkdir(parents=True, exist_ok=True)
        (d / "log").write_text("start\nKeyError: 'TG_BOT_TOKEN'\n  os.environ\n")
        assert "⚠ 程序缺" not in jobs.describe(j)  # 运行中
        j.state = "done"; j.exit_code = 0
        assert "⚠ 程序缺" not in jobs.describe(j)  # 成功了不说
        j.state = "failed"; j.exit_code = 1
        assert "。\n⚠ 程序缺用户自己的密钥 $TG_BOT_TOKEN" in jobs.describe(j), jobs.describe(j)
asyncio.run(jobcase())
print("smoke_missing_env OK")
