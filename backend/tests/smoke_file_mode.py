# 冒烟：v2.16 CORE 31 改动卡 / 整轮撤销记权限位（chmod +x 也算改动，撤销连权限一起回去）。
# 规则在 app/turn_changes.py（mode_of / mode_note）+ app/command_changes.py（stat 缓存带权限）。
# 最后一段走真实回合：模拟模型 + 模拟沙盒（foreground.run 换成直接 chmod）。运行：python tests/smoke_file_mode.py
import os, sys, asyncio, subprocess, tempfile, json, time
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', AUTO_TITLE="false")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import command_changes as C, foreground, llm, turn_changes as T, workspaces
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.blocks import ChangesBlock
from app.db import SessionLocal
from app.models import Conversation, Message
from app.storage import project_dir

ws = workspaces.PERSONAL
wr = project_dir(ws); wr.mkdir(parents=True, exist_ok=True)
mode = lambda p: os.stat(p).st_mode & 0o777

# ---- 1. 规则：权限变化的话 ----
assert T.mode_note(0o644, 0o755) == "加了可执行" and T.mode_note(0o755, 0o644) == "去掉可执行"
assert T.mode_note(0o644, 0o600) == "权限 644→600" and T.mode_note(0o644, 0o700) == "权限 644→700"
assert T.mode_note(0o644, 0o644) is None and T.mode_note(None, 0o755) is None and T.mode_note(0o644, None) is None

# ---- 2. 命令只 chmod（mtime 不变）：扫得出来，卡上 +0 −0 带“加了可执行”，撤销 chmod 回去 ----
s = wr / "run.sh"; s.write_text("echo hi\n"); os.chmod(s, 0o644)
(wr / "plain.txt").write_text("x\n")
t = T.Tracker()
C.before(ws, t)
idx = json.loads((wr / ".turns/shadow/index.json").read_text())
assert idx["run.sh"][3] == 0o644, idx["run.sh"]                                 # index 第 4 项 = 权限
os.chmod(s, 0o755)
assert C.after(ws, t) == ["run.sh"]
card = T.finish(t, ws)
f = card["files"][0]
assert f == {"path": "run.sh", "added": 0, "removed": 0, "diff": "", "command": True, "mode": "加了可执行"}, f
ChangesBlock(**card)
assert "加了可执行" in T.history_text(card)
assert T.undo(ws, card["token"]) == ["run.sh"] and mode(s) == 0o644 and s.read_text() == "echo hi\n"

# ---- 3. 内容 + 权限都改；删掉一个可执行文件 → 撤销后内容和 +x 都回来 ----
os.chmod(s, 0o755)
k = wr / "tool.sh"; k.write_text("#!/bin/sh\n"); os.chmod(k, 0o750)
t = T.Tracker()
C.before(ws, t); time.sleep(0.01)
s.write_text("echo bye\n"); os.chmod(s, 0o600); k.unlink()
C.after(ws, t)
card = T.finish(t, ws)
files = {f["path"]: f for f in card["files"]}
assert files["run.sh"]["mode"] == "权限 755→600" and files["run.sh"]["added"] == 1
assert files["tool.sh"]["deleted"] and "mode" not in files["tool.sh"]
T.undo(ws, card["token"])
assert s.read_text() == "echo hi\n" and mode(s) == 0o755 and k.read_text() == "#!/bin/sh\n" and mode(k) == 0o750

# ---- 4. write_file 的基线也记权限：之后 chmod 掉，撤销恢复；改回原样 + 原权限 = 没有净改动 ----
t = T.Tracker(); t.before(wr, s); s.write_text("new\n"); os.chmod(s, 0o644)
card = T.finish(t, ws)
assert card["files"][0]["mode"] == "去掉可执行"
T.undo(ws, card["token"]); assert mode(s) == 0o755 and s.read_text() == "echo hi\n"
t = T.Tracker(); t.before(wr, s); s.write_text("tmp\n"); os.chmod(s, 0o700); s.write_text("echo hi\n"); os.chmod(s, 0o755)
assert T.finish(t, ws) is None

# ---- 5. 撤销前核对：之后只改了权限也算冲突，一个都不动 ----
t = T.Tracker(); t.before(wr, s); s.write_text("v2\n")
card = T.finish(t, ws)
os.chmod(s, 0o700)
try:
    T.undo(ws, card["token"]); raise SystemExit("应该冲突")
except T.Conflict as e:
    assert e.paths == ["run.sh"]
assert s.read_text() == "v2\n"
os.chmod(s, 0o755); T.undo(ws, card["token"]); assert s.read_text() == "echo hi\n"

# ---- 6. 旧版本留下的记录（没有 mode 字段）照样能撤销，只比内容；旧 3 项 index 当过期重读 ----
t = T.Tracker(); t.before(wr, s); s.write_text("old-style\n")
card = T.finish(t, ws)
mf = wr / ".turns" / card["token"] / "manifest.json"
data = json.loads(mf.read_text()); [x.pop("mode") or x.pop("after_mode") for x in data["files"]]
for x in data["files"]: x.pop("after_mode", None)
mf.write_text(json.dumps(data)); os.chmod(s, 0o700)
assert T.undo(ws, card["token"]) == ["run.sh"] and s.read_text() == "echo hi\n" and mode(s) == 0o700
os.chmod(s, 0o755)
(wr / ".turns/shadow/index.json").write_text(json.dumps({"run.sh": [8, 1, None]}))
t = T.Tracker(); C.before(ws, t)
assert len(t.seen["run.sh"]) == 4 and t.seen["run.sh"][3] == 0o755 and t.seen["run.sh"][2]

# ---- 7. 真实回合：模型跑 chmod +x → 回复末尾改动卡带“加了可执行”，撤销回去 ----
os.chmod(s, 0o644)
async def fake_run(workspace, command, timeout, stdin=None, live=None, env=None, promote=None):
    if command.startswith("chmod"):
        os.chmod(s, 0o755)
    return foreground.Outcome(exit_code=0, status="退出码 0", out="", shown="")
foreground.run = fake_run
script: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    step = script.pop(0)
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"m{len(script)}-{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()
async def go():
    async with SessionLocal() as db:
        conv = Conversation(title="权限"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=[{"type": "text", "text": "让脚本能跑"}]))
        await db.commit()
        return await run_turn(db, conv, emit=lambda ev: asyncio.sleep(0))
script.extend([[("run_command", {"command": "chmod +x run.sh"})], "好了。"])
reply = asyncio.run(go())
card = reply.blocks[-1]
assert card["type"] == "changes" and card["files"][0]["mode"] == "加了可执行" and card["files"][0]["command"], reply.blocks
assert mode(s) == 0o755
T.undo(ws, card["token"]); assert mode(s) == 0o644
print("smoke_file_mode ok")
