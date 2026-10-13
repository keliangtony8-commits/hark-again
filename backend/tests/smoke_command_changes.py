# 冒烟：v2.14 CORE 30 run_command 改的文件进改动卡 + 整轮撤销（app/command_changes.py，Gemini 影子仓库思路）。
# 模拟模型 + 模拟沙盒（foreground.run 换成直接改文件）。运行：python tests/smoke_command_changes.py
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
from app.db import SessionLocal
from app.models import Conversation, Message
from app.storage import project_dir

ws = workspaces.PERSONAL
wr = project_dir(ws); wr.mkdir(parents=True, exist_ok=True)

def tick():
    time.sleep(0.01)  # mtime_ns 一定变

# ---- 1. 规则 ----
assert C.tracks("python build.py") and C.tracks("rm a.txt") and C.tracks("echo x > a")
assert not C.tracks("ls -la") and not C.tracks("cat a.txt") and not C.tracks("git status")
(wr / "a.txt").write_text("one\n")
(wr / "keep.txt").write_text("same\n")
(wr / "gone.txt").write_text("x\ny\n")
(wr / "node_modules/pkg").mkdir(parents=True); (wr / "node_modules/pkg/i.js").write_text("1")
(wr / ".git").mkdir(); (wr / ".git/HEAD").write_text("ref")
t = T.Tracker()
C.before(ws, t)
assert set(t.seen) == {"a.txt", "keep.txt", "gone.txt"}, t.seen                # 隐藏目录、依赖目录不扫
tick()
(wr / "a.txt").write_text("one\ntwo\n"); (wr / "gone.txt").unlink(); (wr / "out").mkdir(); (wr / "out/new.md").write_text("hi\n")
(wr / "node_modules/pkg/i.js").write_text("2"); (wr / ".git/HEAD").write_text("x")
(wr / "keep.txt").write_text("same\n")                                           # mtime 变了内容没变 → finish 不出
assert C.after(ws, t) == ["a.txt", "gone.txt", "keep.txt", "out/new.md"]
card = T.finish(t, ws)
files = {f["path"]: f for f in card["files"]}
assert set(files) == {"a.txt", "gone.txt", "out/new.md"}, files
assert all(f.get("command") for f in files.values())
assert files["a.txt"]["added"] == 1 and "+two" in files["a.txt"]["diff"]
assert files["gone.txt"]["deleted"] and files["gone.txt"]["removed"] == 2 and files["out/new.md"]["created"]
assert "命令 " in T.history_text(card) and "命令" in T.history_text(card)
assert T.undo(ws, card["token"])
assert (wr / "a.txt").read_text() == "one\n" and (wr / "gone.txt").read_text() == "x\ny\n" and not (wr / "out/new.md").exists()

# write_file 先记的基线优先（先到先得）；同一轮第二条命令仍按这一轮第一次见到的版本
t = T.Tracker()
C.before(ws, t)
p = wr / "a.txt"; t.before(wr, p); tick(); p.write_text("by write_file\n")   # write_file 改
C.after(ws, t)
C.before(ws, t); tick(); (wr / "keep.txt").write_text("v2\n"); C.after(ws, t)
C.before(ws, t); tick(); (wr / "keep.txt").write_text("v3\n"); p.write_text("by cmd\n"); C.after(ws, t)
card = T.finish(t, ws)
files = {f["path"]: f for f in card["files"]}
assert not files["a.txt"].get("command") and files["keep.txt"]["command"], files
assert "-same" in files["keep.txt"]["diff"] and "+v3" in files["keep.txt"]["diff"]
T.undo(ws, card["token"])
assert p.read_text() == "one\n" and (wr / "keep.txt").read_text() == "same\n"

# 影子库：没变的不重读（对象复用）；不再引用的对象清掉；太大的不存 → 列出、不能撤销
obj = wr / ".turns/shadow/obj"
C.before(ws, T.Tracker())
snap = {o.name: o.stat().st_mtime_ns for o in obj.iterdir()}
idx = json.loads((wr / ".turns/shadow/index.json").read_text())
assert snap and set(snap) == {e[2] for e in idx.values()}, (snap, idx)          # 只留现在引用的对象
t = T.Tracker(); C.before(ws, t); C.after(ws, t)
assert {o.name: o.stat().st_mtime_ns for o in obj.iterdir()} == snap and T.finish(t, ws) is None
old = C.FILE_MAX; C.FILE_MAX = 5
(wr / "big.bin").write_bytes(b"0123456789")
t = T.Tracker(); C.before(ws, t)
assert t.seen["big.bin"][2] is None
tick(); (wr / "big.bin").write_bytes(b"changed!!!!"); C.after(ws, t)
card = T.finish(t, ws)
assert card["token"] == "" and card["files"][0]["big"] and card["files"][0]["command"], card
C.FILE_MAX = old
(wr / "big.bin").unlink()

# 扫不完（文件太多）：不判新建 / 删除，只比看到的
old = C.FILES_MAX; C.FILES_MAX = 2
t = T.Tracker(); C.before(ws, t)
assert t.seen_capped
tick(); (wr / "brand_new.txt").write_text("n")
found = C.after(ws, t)
assert "brand_new.txt" not in found, found
C.FILES_MAX = old
(wr / "brand_new.txt").unlink()
# 没扫过（只读命令）：after 什么都不记
t = T.Tracker(); assert C.after(ws, t) == [] and not t.touched
# 影子库坏了：不抛
(wr / ".turns/shadow/index.json").write_text("{bad")
t = T.Tracker(); C.before(ws, t); assert "a.txt" in t.seen

# ---- 2. 真实回合（模拟模型 + 模拟沙盒）：命令改文件 → 回复末尾改动卡（标命令）；只读命令不扫 ----
calls = []
async def fake_run(workspace, command, timeout, stdin=None, live=None, env=None, promote=None):
    calls.append(command)
    if command.startswith("sed -i"):
        (wr / "a.txt").write_text("one\nsed\n")
        (wr / "made.txt").write_text("made\n")
    return foreground.Outcome(exit_code=0, status="退出码 0", out="", shown="")
foreground.run = fake_run
scans = []
orig_before = C.before
C.before = lambda w, tr: (scans.append(w), orig_before(w, tr))[1]

script: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    step = script.pop(0)
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"c{len(script)}-{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()

async def seed(text):
    async with SessionLocal() as db:
        conv = Conversation(title="命令改文件"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=[{"type": "text", "text": text}]))
        await db.commit()
        return conv.id
async def turn(cid):
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))

cid = asyncio.run(seed("用 sed 改一下"))
script.extend([[("run_command", {"command": "cat a.txt"})], [("run_command", {"command": "sed -i s/x/y/ a.txt"})], "改好了。"])
reply = asyncio.run(turn(cid))
assert calls == ["cat a.txt", "sed -i s/x/y/ a.txt"], calls
assert len(scans) == 1, scans                                                    # cat 只读：不扫
assert [b["type"] for b in reply.blocks][-2:] == ["text", "changes"], reply.blocks
card = reply.blocks[-1]
assert [f["path"] for f in card["files"]] == ["a.txt", "made.txt"] and all(f["command"] for f in card["files"]) and card["token"]
from app.blocks import ChangesBlock
ChangesBlock(**card)                                                             # 块模型认 command 字段
T.undo(ws, card["token"])
assert (wr / "a.txt").read_text() == "one\n" and not (wr / "made.txt").exists()
print("smoke_command_changes ok")
