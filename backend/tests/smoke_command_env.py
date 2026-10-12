# 冒烟：v1.86 命令环境变量（app/command_env.py 唯一规则；保险箱 kind=env）。假沙盒、模拟模型（不打真接口）：
# 1) 规则：变量名 / 系统变量 / 值长度换行、preview、scrub（整值、长值先换、窗口边上的半截、短片段不误伤）、prompt；
# 2) 保险箱接口：env 不要域名、坏名字 / 系统变量 / 短值 400、同名覆盖、上限、列表不含明文、api_key 仍要域名、删除后缓存同步；
# 3) 系统提示：只有名字、不在“api_request 已授权服务”里；
# 4) run_command：env 传给沙盒、实时尾巴 / 回复卡片 / 给模型的结果都打码；没有变量时不传 env；
# 5) 后台任务：启动带 env；日志尾巴 / read_new（含从值中间切进来的窗口）打码；重启时现取新值；
# 6) 用户 `!命令`：带 env、输出打码；
# 7) 任何工具结果都打码（read_file 读到写着值的文件）；worker 进程缓存过期重读；
# 8) 沙盒 runner：check_env 第二道校验、STDIN_B64 不可被覆盖、/jobs/start 把 env 交给 exec_run。
# 运行：python tests/smoke_command_env.py
import os, sys, asyncio, subprocess, tempfile, json, types, time
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

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import command_env as E, jobs, llm, sandbox_client, storage, user_shell, workspaces
from app.agent.context import build_system_prompt
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.auth import require_user
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Job, Message, Secret
from app.routes import vault as rv

def run(coro):
    return asyncio.run(coro)

TOKEN = "tg-123456:ABCdefGHIjklMNOpqr"
KEY2 = "sk-live-0987654321zyx"

# ---- 1. 规则 ----
assert E.check_name(" $telegram_bot_token ") == "TELEGRAM_BOT_TOKEN"
for bad in ["", "A", "1ABC", "A-B", "中文", "A" * 65, "PATH", "home", "STDIN_B64", "LD_PRELOAD"]:
    try:
        E.check_name(bad); raise AssertionError(bad)
    except ValueError:
        pass
for bad in ["short", "a\nbcdefg", "abc\rdefg", "x" * (E.VALUE_MAX + 1)]:
    try:
        E.check_value(bad); raise AssertionError(bad)
    except ValueError:
        pass
assert E.check_value("abcdef") == "abcdef"
assert E.preview("x" * 15) == "" and E.preview("abcdefghijklmnop") == "mnop"
V = {"TG": TOKEN, "OPENAI": KEY2, "SUB": TOKEN[:10]}
s = E.scrub(f"token={TOKEN} key {KEY2} again {TOKEN}", V)
assert s == "token=[$TG] key [$OPENAI] again [$TG]", s  # 长值先换：SUB（TOKEN 的前半）不会把 TOKEN 劈开
assert E.scrub(f"...{TOKEN[:10]}...", V) == "...[$SUB]..."
assert E.scrub(TOKEN[7:] + " ok", V) == "[$TG] ok"                 # 窗口从值中间切进来
assert E.scrub("tail " + KEY2[:9], V) == "tail [$OPENAI]"           # 结尾只露出前半
assert E.scrub("abc sk-li", V) == "abc sk-li"                        # 不到 EDGE_MIN 的片段不动
assert E.scrub("no secret here", V) == "no secret here" and E.scrub("", V) == "" and E.scrub("x", {}) == "x"
assert E.prompt([]) == "" and "$A_B、$TG" in E.prompt(["A_B", "TG"]) and TOKEN not in E.prompt(["TG"])

# ---- 2. 保险箱接口 ----
app = FastAPI(); app.include_router(rv.router)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
rr = c.post("/api/vault", json={"kind": "env", "name": "telegram_bot_token", "value": "old-value-123"})
assert rr.status_code == 200, rr.text
pub = rr.json()
assert pub["kind"] == "env" and pub["name"] == "TELEGRAM_BOT_TOKEN" and pub["hosts"] == [] and pub["preview"] == "", pub
assert E._values == {"TELEGRAM_BOT_TOKEN": "old-value-123"}
rr = c.post("/api/vault", json={"kind": "env", "name": "TELEGRAM_BOT_TOKEN", "value": TOKEN})  # 同名覆盖
assert rr.status_code == 200 and rr.json()["preview"] == TOKEN[-4:], rr.text
lst = c.get("/api/vault").json()
assert len(lst) == 1 and TOKEN not in json.dumps(lst) and E._values == {"TELEGRAM_BOT_TOKEN": TOKEN}
for body, frag in [({"kind": "env", "name": "PATH", "value": "abcdefgh"}, "系统变量"),
                   ({"kind": "env", "name": "1X", "value": "abcdefgh"}, "大写字母"),
                   ({"kind": "env", "name": "OK_NAME", "value": "abcde"}, "至少"),
                   ({"kind": "env", "name": "OK_NAME", "value": "abc\ndefgh"}, "换行"),
                   ({"kind": "api_key", "name": "X", "value": "abcdefgh"}, "域名"),
                   ({"kind": "weird", "name": "X", "value": "abcdefgh", "hosts": ["a.com"]}, "类型")]:
    rr = c.post("/api/vault", json=body)
    assert rr.status_code == 400 and frag in rr.json()["detail"], (body, rr.text)
rr = c.post("/api/vault", json={"kind": "api_key", "name": "天气", "value": "weatherkey99", "hosts": ["api.weather.com"]})
assert rr.status_code == 200
rr = c.post("/api/vault", json={"kind": "env", "name": "OPENAI", "value": KEY2})
assert rr.status_code == 200
openai_id = rr.json()["id"]
E.ENV_MAX, saved_max = 2, E.ENV_MAX
rr = c.post("/api/vault", json={"kind": "env", "name": "THIRD", "value": "abcdefgh"})
assert rr.status_code == 400 and "最多" in rr.json()["detail"], rr.text
assert c.post("/api/vault", json={"kind": "env", "name": "OPENAI", "value": KEY2}).status_code == 200  # 覆盖不算新增
E.ENV_MAX = saved_max
openai_id = next(x["id"] for x in c.get("/api/vault").json() if x["name"] == "OPENAI")
assert set(E._values) == {"TELEGRAM_BOT_TOKEN", "OPENAI"}

# ---- 3. 系统提示 ----
async def sys_prompt():
    async with SessionLocal() as db:
        return (await build_system_prompt(db, None)).text()
sp = run(sys_prompt())
assert "$OPENAI、$TELEGRAM_BOT_TOKEN" in sp and TOKEN not in sp and KEY2 not in sp, sp
assert "- 天气：api.weather.com" in sp and "- OPENAI" not in sp and "- TELEGRAM_BOT_TOKEN" not in sp

# ---- 4. run_command（模拟模型 + 假沙盒）----
streams, starts = [], []
async def fake_stream(project_id, command, timeout=60, stdin=None, env=None):
    streams.append(env)
    yield {"type": "out", "data": f"connecting with {TOKEN}\n"}
    yield {"type": "exit", "exit_code": 0, "timed_out": False, "output": f"connecting with {TOKEN}\nkey={KEY2}\ndone\n"}
sandbox_client.stream = fake_stream

script, seen = [], []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append([dict(m) for m in messages])
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

async def seed(text):
    async with SessionLocal() as db:
        conv = Conversation(title="bot"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks(text)))
        await db.commit()
        return conv.id
async def turn(cid, live=None):
    async with SessionLocal() as db:
        conv = await db.get(Conversation, cid)
        return await run_turn(db, conv)

cid = run(seed("测一下机器人能不能连上"))
script[:] = [("run_command", {"command": "python bot.py --check"}), "连上了"]
reply = run(turn(cid))
assert streams[-1] == {"TELEGRAM_BOT_TOKEN": TOKEN, "OPENAI": KEY2}, streams
tool_msg = next(m for m in seen[-1] if m["role"] == "tool")
assert TOKEN not in tool_msg["content"] and "[$TELEGRAM_BOT_TOKEN]" in tool_msg["content"] and "[$OPENAI]" in tool_msg["content"], tool_msg
dump = json.dumps(reply.blocks, ensure_ascii=False)
assert TOKEN not in dump and KEY2 not in dump and "[$TELEGRAM_BOT_TOKEN]" in dump, dump

# 实时尾巴也打码（foreground 直接测 live 回调）
from app import foreground
tails = []
o = run(foreground.run("p1", "x", 10, None, tails.append, {"TELEGRAM_BOT_TOKEN": TOKEN}))
assert tails and all(TOKEN not in t for t in tails) and "[$TELEGRAM_BOT_TOKEN]" in tails[0], tails
assert TOKEN not in o.out and TOKEN not in o.shown
# 没有变量：不传 env（老的假沙盒签名不受影响）
async def old_stream(project_id, command, timeout=60, stdin=None):
    yield {"type": "exit", "exit_code": 0, "timed_out": False, "output": "ok"}
sandbox_client.stream = old_stream
assert run(foreground.run("p1", "x", 10, None, None, {})).out == "ok"
sandbox_client.stream = fake_stream

# ---- 5. 后台任务 ----
launched = []
async def fake_start(project_id, job_id, env=None):
    launched.append((job_id, env))
sandbox_client.start_job = fake_start
async def start_job():
    async with SessionLocal() as db:
        j = await jobs.start(db, project_id=workspaces.PERSONAL, command="python bot.py", keep_alive=True)
        await db.commit()
        return j.id
jid = run(start_job())
assert launched[-1] == (jid, {"TELEGRAM_BOT_TOKEN": TOKEN, "OPENAI": KEY2}), launched
async def get_job():
    async with SessionLocal() as db:
        return await db.get(Job, jid)
j = run(get_job())
log = jobs.job_dir(j) / "log"
log.write_text(f"start\nusing {TOKEN}\n" + "x" * 50 + "\n" + KEY2 + "\n", encoding="utf-8")
assert TOKEN not in jobs.log_tail(j) and "[$TELEGRAM_BOT_TOKEN]" in jobs.log_tail(j) and "[$OPENAI]" in jobs.log_tail(j)
cut = jobs.log_tail(j, chars=len(KEY2) + 3)                  # 窗口从 KEY2 中间开始
assert KEY2[-6:] not in cut, cut
text, off, dropped = jobs.read_new(j)
assert TOKEN not in text and KEY2 not in text, text
# 改了值再重启：现取新值
NEW = "tg-999999:newvalueXYZ"
assert c.post("/api/vault", json={"kind": "env", "name": "TELEGRAM_BOT_TOKEN", "value": NEW}).status_code == 200
async def relaunch():
    async with SessionLocal() as db:
        jj = await db.get(Job, jid)
        await jobs._relaunch(db, jj)
run(relaunch())
assert launched[-1] == (jid, {"TELEGRAM_BOT_TOKEN": NEW, "OPENAI": KEY2}), launched
# 没有变量时 start_job 不收 env（老签名）
async def old_start(project_id, job_id):
    launched.append((job_id, "old"))
sandbox_client.start_job = old_start
async def none_env():
    async with SessionLocal() as db:
        jj = await db.get(Job, jid)
        real = E.load
        async def empty(db):
            return {}
        E.load = empty
        try:
            await jobs._relaunch(db, jj)
        finally:
            E.load = real
run(none_env())
assert launched[-1] == (jid, "old")
sandbox_client.start_job = fake_start

# ---- 6. 用户 !命令 ----
async def shell():
    events = []
    async def emit(e):
        events.append(e)
    async with SessionLocal() as db:
        conv = Conversation(title="sh"); db.add(conv); await db.commit()
        await user_shell.run(db, conv.id, None, "echo $TELEGRAM_BOT_TOKEN", emit, None)
    return events
# 假沙盒把注入的值原样打印出来：卡片和落库都只剩 [$NAME]
async def fake_stream_new(project_id, command, timeout=60, stdin=None, env=None):
    streams.append(env)
    yield {"type": "exit", "exit_code": 0, "timed_out": False, "output": f"{env['TELEGRAM_BOT_TOKEN']}\n"}
sandbox_client.stream = fake_stream_new
ev = run(shell())
done = next(e for e in ev if e["type"] == "message.done")
assert NEW not in json.dumps(ev, ensure_ascii=False) and done["message"]["blocks"][0]["output"] == "[$TELEGRAM_BOT_TOKEN]", done

# ---- 7. 任何工具结果都打码 + 缓存过期重读 ----
ws_dir = storage.project_dir(workspaces.PERSONAL)
ws_dir.mkdir(parents=True, exist_ok=True)
(ws_dir / "config.json").write_text(json.dumps({"token": NEW}), encoding="utf-8")
cid2 = run(seed("看看 config.json"))
script[:] = [("read_file", {"path": "config.json"}), "看完了"]
run(turn(cid2))
tool_msg = next(m for m in seen[-1] if m["role"] == "tool")
assert NEW not in tool_msg["content"] and "[$TELEGRAM_BOT_TOKEN]" in tool_msg["content"], tool_msg
E._set({})                     # 别的进程：缓存空且刚装好 → ensure 不重读
async def ens(age):
    async with SessionLocal() as db:
        await E.ensure(db, age)
run(ens(60)); assert E._values == {}
E._loaded_at -= 61             # 过期 → 重读
run(ens(60)); assert E._values.get("TELEGRAM_BOT_TOKEN") == NEW
run(E.ensure(None))            # 没有库会话：不动、不报错
# 删除 → 缓存同步
assert c.delete(f"/api/vault/{openai_id}").status_code == 200 and "OPENAI" not in E._values

# ---- 8. 沙盒 runner ----
class NotFound(Exception):
    pass
captured = {}
class FakeContainer:
    id = name = "sbx-p1"
    status = "running"
    image = NS(id="img")
    attrs = {"State": {"StartedAt": ""}}
    def exec_run(self, cmd, **kw):
        captured.setdefault("exec_run", []).append((cmd, kw))
        return NS(exit_code=0, output=b"0\n")
fc = FakeContainer()
def exec_create(cid, cmd, **kw):
    captured["exec_create"] = kw; return {"Id": "x"}
fake_client = NS(containers=NS(get=lambda n: fc, list=lambda **kw: [fc], run=lambda *a, **kw: fc),
                 images=NS(get=lambda name: NS(id="img")),
                 networks=NS(get=lambda name: (_ for _ in ()).throw(NotFound(name))),
                 api=NS(exec_create=exec_create, exec_start=lambda eid, stream=True: iter([b"ok\n"]),
                        exec_inspect=lambda eid: {"ExitCode": 0}))
docker_mod = types.ModuleType("docker"); docker_mod.from_env = lambda: fake_client
errors_mod = types.ModuleType("docker.errors"); errors_mod.NotFound = NotFound
docker_mod.errors = errors_mod
sys.modules.update({"docker": docker_mod, "docker.errors": errors_mod})
os.environ.update(SANDBOX_TOKEN="t", HOST_PROJECTS_DIR=tmp, SANDBOX_STATE=os.path.join(tmp, "state.json"))
sys.path.insert(0, os.path.join(root, "..", "sandbox"))
import runner
from fastapi import HTTPException
assert runner.check_env(None) == {} and runner.check_env({"A_B": "v"}) == {"A_B": "v"}
for bad in [{"PATH": "x"}, {"STDIN_B64": "x"}, {"lower": "x"}, {"A": "x"}, {"OK_X": "a\x00b"},
            {"OK_X": "v" * (runner.ENV_VALUE_MAX + 1)}, {f"V{i:02d}": "x" for i in range(runner.ENV_MAX + 1)}]:
    try:
        runner.check_env(bad); raise AssertionError(bad)
    except HTTPException as e:
        assert e.status_code == 400
assert runner.ENV_MAX == E.ENV_MAX and runner.ENV_VALUE_MAX == E.VALUE_MAX and runner.ENV_RESERVED == E.RESERVED
runner._container = lambda pid: fc
res = runner._exec("p1", "echo hi", 10, "in", None, None, {"TG": "v1"})
env = captured["exec_create"]["environment"]
assert env["TG"] == "v1" and "STDIN_B64" in env, env
runner._exec("p1", "echo hi", 10, None, None, None, {})
assert captured["exec_create"]["environment"] is None
tc = TestClient(runner.app)
rr = tc.post("/jobs/start", json={"project_id": "p1", "job_id": "jabcdef12", "env": {"TG": "v2"}}, headers={"Authorization": "Bearer t"})
assert rr.status_code == 200, rr.text
start_call = [x for x in captured["exec_run"] if x[0][:2] == ["setsid", "-f"]][-1]
assert start_call[1]["environment"] == {"TG": "v2"}, start_call
rr = tc.post("/jobs/start", json={"project_id": "p1", "job_id": "jabcdef12", "env": {"PATH": "/x"}}, headers={"Authorization": "Bearer t"})
assert rr.status_code == 400
rr = tc.post("/exec", json={"project_id": "p1", "command": "x", "env": {"HOME": "/x"}}, headers={"Authorization": "Bearer t"})
assert rr.status_code == 400
print("smoke_command_env OK")
