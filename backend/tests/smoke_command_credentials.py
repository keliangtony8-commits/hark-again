# 冒烟：v2.20 命令借用已连接账户（app/command_credentials.py 唯一规则）。假沙盒、模拟模型（不打真接口）：
# 1) parse：字符串 / {"provider"} 写法、去重、不认识的服务、太多；env_names；note / labels / prompt；
# 2) grant：GitHub → GH_TOKEN/GITHUB_TOKEN + git 凭证助手（只引用 $GH_TOKEN，值不在配置里）；没连 → missing；
# 3) run_command 前台：只有声明了 credentials 的命令拿到 Token；输出 / 卡片 / 给模型的结果都打码成 [$GH_TOKEN]；标题带“用 GitHub 账户”；
#    没连接 → 不跑、说清去连接器页；坏参数 → 不跑；
# 4) 后台 / 常驻：启动带 Token、jobs.credentials 记下、任务卡 credentials=["GitHub"]、重启现取新 Token；
#    别的进程（缓存刚重读）也能把日志里的 Token 抹掉；没声明的后台任务拿不到；
# 5) 系统提示列出可借的服务；沙盒 runner 收得下 30 个用户变量 + 借用变量。
# 运行：python tests/smoke_command_credentials.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
from cryptography.fernet import Fernet
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY=Fernet.generate_key().decode(), DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', MODEL_ROUTER="off",
  AUTO_TITLE="false", NEXT_SPEAKER_CHECK="off")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import command_credentials as C, command_env as E, jobs, llm, sandbox_client, vault, workspaces
from app.agent.context import build_system_prompt
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.blocks import JobBlock, text_to_blocks
from app.db import SessionLocal
from app.models import Connection, Conversation, Job, Message

def run(coro):
    return asyncio.run(coro)

GH = "gho_abcdefghijklmnopqrstuvwxyz0123456789"
GH2 = "gho_ZYXWVUTSRQPONMLKJIHGFEDCBA9876543210"

# ---- 1. 规则 ----
assert C.parse(None) == [] and C.parse([]) == [] and C.parse("") == []
assert C.parse(["github", {"provider": "GitHub"}, {"provider": "google"}]) == ["github", "google"]
assert C.parse({"provider": "github"}) == ["github"]
for bad, frag in [(["gitlab"], "不是可连接的服务"), ([{"x": 1}], "不是可连接的服务")]:
    try:
        C.parse(bad); raise AssertionError(bad)
    except ValueError as e:
        assert frag in str(e) and "github" in str(e), e
C.MAX, saved = 1, C.MAX
try:
    C.parse(["github", "google"]); raise AssertionError
except ValueError as e:
    assert "最多" in str(e)
C.MAX = saved
assert C.env_names("github") == ("GH_TOKEN", "GITHUB_TOKEN") and C.env_names("slack-x") == ("SLACK_X_TOKEN",)
assert C.labels(["github", "nope"]) == ["GitHub"] and C.note(C.Grant()) == "" and C.prompt([]) == ""
assert '"github"' in C.prompt(["github"]) and "$GH_TOKEN" in C.prompt(["github"])

# ---- 2. grant ----
async def connect(tok):
    async with SessionLocal() as db:
        for c in (await db.scalars(__import__("sqlalchemy").select(Connection))).all():
            await db.delete(c)
        await db.flush()
        db.add(Connection(provider="github", account="octocat", ciphertext=vault.encrypt(json.dumps({"access_token": tok}))))
        await db.commit()
async def grant(ps):
    async with SessionLocal() as db:
        return await C.grant(db, ps)
g = run(grant(["github"]))
assert g.missing == ["还没连接 GitHub：请用户在“连接器”页连上，连好后再跑"], g
run(connect(GH))
g = run(grant(["github", "google"]))
assert g.env["GH_TOKEN"] == GH and g.env["GITHUB_TOKEN"] == GH and g.labels == ["GitHub（octocat）"], g
assert len(g.missing) == 1 and "Google" in g.missing[0]
assert g.env["GIT_CONFIG_COUNT"] == "2" and g.env["GIT_CONFIG_KEY_0"] == "credential.https://github.com.helper"
assert g.env["GIT_CONFIG_VALUE_0"] == "" and "$GH_TOKEN" in g.env["GIT_CONFIG_VALUE_1"] and GH not in g.env["GIT_CONFIG_VALUE_1"]
assert g.env["GIT_TERMINAL_PROMPT"] == "0" and len(g.env) <= C.ENV_EXTRA_MAX
n = C.note(g)
assert "GitHub（octocat）" in n and "$GH_TOKEN" in n and "免密" in n and "没借到" in n and GH not in n, n
assert E.scrub(f"token {GH}") == "token [$GH_TOKEN]"   # 借到就进打码表

# ---- 3. run_command 前台 ----
streams = []
async def fake_stream(project_id, command, timeout=60, stdin=None, env=None, **kw):
    streams.append(env)
    tok = (env or {}).get("GH_TOKEN", "none")
    yield {"type": "out", "data": f"auth {tok}\n"}
    yield {"type": "exit", "exit_code": 0, "timed_out": False, "output": f"auth {tok}\npushed\n"}
sandbox_client.stream = fake_stream

script, seen = [], []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
counter = [0]
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append([dict(m) for m in messages])
    step = script.pop(0)
    async def gen():
        if isinstance(step, tuple):
            counter[0] += 1
            yield chunk(tool=[NS(index=0, id=f"c{counter[0]}", function=NS(name=step[0], arguments=json.dumps(step[1], ensure_ascii=False)))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()

async def seed(text):
    async with SessionLocal() as db:
        conv = Conversation(title="gh"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks(text)))
        await db.commit()
        return conv.id
async def turn(cid):
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid))
def tool_msgs():
    return [m for m in seen[-1] if m["role"] == "tool"]

cid = run(seed("推一下代码"))
script[:] = [("run_command", {"command": "gh repo list", "credentials": [{"provider": "github"}]}), "推好了"]
reply = run(turn(cid))
assert streams, [m for m in seen[-1] if m["role"]=="tool"]
assert streams[-1]["GH_TOKEN"] == GH and streams[-1]["GIT_CONFIG_COUNT"] == "2", streams[-1]
tm = tool_msgs()[-1]["content"]
assert GH not in tm and "auth [$GH_TOKEN]" in tm and "已用 GitHub（octocat）认证" in tm, tm
dump = json.dumps(reply.blocks, ensure_ascii=False)
assert GH not in dump and "用 GitHub 账户" in dump, dump
# 没声明：拿不到
script[:] = [("run_command", {"command": "git status"}), "好"]
run(turn(cid))
assert "GH_TOKEN" not in (streams[-1] or {}) and "auth none" in tool_msgs()[-1]["content"]
# 坏参数 / 没连上：不跑
before = len(streams)
script[:] = [("run_command", {"command": "x", "credentials": [{"provider": "gitlab"}]}), "好"]
run(turn(cid))
assert len(streams) == before and "不是可连接的服务" in tool_msgs()[-1]["content"]
script[:] = [("run_command", {"command": "gcloud x", "credentials": [{"provider": "google"}]}), "好"]
run(turn(cid))
assert len(streams) == before and "没有运行" in tool_msgs()[-1]["content"] and "Google" in tool_msgs()[-1]["content"]

# ---- 4. 后台 / 常驻 ----
launched = []
async def fake_start(project_id, job_id, env=None):
    launched.append((job_id, env))
sandbox_client.start_job = fake_start
script[:] = [("run_command", {"command": "python sync.py", "keep_alive": True, "credentials": [{"provider": "github"}]}), "在跑了"]
reply = run(turn(cid))
jid, env = launched[-1]
assert env["GH_TOKEN"] == GH and env["GITHUB_TOKEN"] == GH, env
assert "已用 GitHub（octocat）认证" in tool_msgs()[-1]["content"]
jb = next(b for b in reply.blocks if b["type"] == "job")
assert jb["credentials"] == ["GitHub"] and JobBlock(**jb).credentials == ["GitHub"], jb
async def get_job():
    async with SessionLocal() as db:
        return await db.get(Job, jid)
j = run(get_job())
assert j.credentials == "github" and jobs.credentials(j) == ["github"] and jobs.wire(j)["credentials"] == ["GitHub"]
# Token 续了：重启现取新的
run(connect(GH2))
async def relaunch():
    async with SessionLocal() as db:
        await jobs._relaunch(db, await db.get(Job, jid))
run(relaunch())
assert launched[-1][1]["GH_TOKEN"] == GH2, launched[-1]
# 别的进程：打码表空 → load 重读时把连接 Token 也装进来
E._set({}); E._borrowed.clear()
async def load():
    async with SessionLocal() as db:
        await E.load(db)
run(load())
log = jobs.job_dir(j) / "log"
log.write_text(f"pulling with {GH2}\n", encoding="utf-8")
assert GH2 not in jobs.log_tail(j) and "[$GH_TOKEN]" in jobs.log_tail(j)
# 没声明的后台任务拿不到
script[:] = [("run_command", {"command": "python other.py", "background": True}), "好"]
reply = run(turn(cid))
assert not launched[-1][1] or "GH_TOKEN" not in launched[-1][1]
assert "credentials" not in next(b for b in reply.blocks if b["type"] == "job")

# ---- 5. 系统提示 + 沙盒上限 ----
async def sys_prompt():
    async with SessionLocal() as db:
        return (await build_system_prompt(db, None)).text()
sp = run(sys_prompt())
assert 'GitHub（"github"）' in sp and GH2 not in sp, sp
sys.path.insert(0, os.path.join(root, "..", "sandbox"))
import importlib.util
spec = importlib.util.spec_from_file_location("sbx_runner_src", os.path.join(root, "..", "sandbox", "runner.py"))
src = open(spec.origin, encoding="utf-8").read()
assert f"ENV_MAX, ENV_VALUE_MAX = {E.ENV_MAX + C.ENV_EXTRA_MAX}," in src
print("smoke_command_credentials OK")
