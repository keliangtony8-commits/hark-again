# 冒烟：v1.41 改文件的稳健性回访——移植 Codex seek_sequence 的标点归一档（含其单测）+ deepseek-harness
# fs-observation-policy 的“看过才许覆盖、看过后变了就拒”（app/file_seen.py）。模拟模型，不用沙盒。
# 运行：python tests/smoke_file_seen.py
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

from app import file_edit, file_seen, llm, workspaces
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message
from app.storage import project_dir


# ---- 1. Codex seek_sequence 单测（移植自 codex-rs/apply-patch/src/seek_sequence.rs，Apache-2.0）----
S = file_edit.seek_sequence
assert S(["foo", "bar", "baz"], ["bar", "baz"], 0, False) == 1                     # test_exact_match_finds_sequence
assert S(["foo   ", "bar\t\t"], ["foo", "bar"], 0, False) == 0                      # test_rstrip_match_ignores_trailing_whitespace
assert S(["    foo   ", "   bar\t"], ["foo", "bar"], 0, False) == 0                 # test_trim_match_ignores_leading_and_trailing_whitespace
assert S(["just one line"], ["too", "many", "lines"], 0, False) is None             # test_pattern_longer_than_input_returns_none
# 我们补的：空 pattern、eof 先找结尾、标点归一档
assert S(["a"], [], 0, False) == 0
assert S(["x", "end", "x", "end"], ["end"], 0, True) == 3 and S(["x", "end", "x", "end"], ["end"], 0, False) == 1
assert S(["let s = “hi” — ok\u00a0done"], ['let s = "hi" - ok done'], 0, False) == 0
assert file_edit.normalise("  ‘a’\u3000–\u2212 ") == "'a' --"

# ---- 2. edit_file 的标点归一档 ----
A, E = file_edit.apply, file_edit.EditError
doc = "# 标题\nprint(“你好”) — 结束\nother\n"
r = A(doc, 'print("你好") - 结束', 'print("再见")')
assert r.loose and r.count == 1 and r.text == '# 标题\nprint("再见")\nother\n', r.text
two = "x — 1\ny\nx - 1\n"  # 标点归一后两处 → 不唯一不改
try:
    A(two, "x \u2013 1", "z"); raise AssertionError
except E as e:
    assert "第 1、3 行" in str(e) or "2 处" in str(e), str(e)
# 前面的档优先：精确/去空白能找到就不会走标点档
assert not A("a — b\n", "a — b", "c").loose

# ---- 3. 规则：看过才许覆盖（移植自 deepseek-harness fs-observation-policy 的单测语义）----
import pathlib
F = file_seen
d = pathlib.Path(tmp) / "seen"; d.mkdir()
f = d / "a.txt"
assert F.owner_of("c1", None) == "c:c1" and F.owner_of("c1", "t1") == "t:t1" and F.owner_of(None, None) is None
def refused(fn, short):
    try:
        fn()
    except F.Refused as e:
        assert e.short == short, (e.short, short); return str(e)
    raise AssertionError("应该被拒")
F.check_write("c:a", f, "a.txt")                         # 新文件：没看过也能建
f.write_text("v1")
refused(lambda: F.check_write("c:a", f, "a.txt"), "没读过就要覆盖")   # unobserved existing → 拒
F.check_write(None, f, "a.txt")                          # 没主人 → 不管
F.observe("c:a", f)
F.check_write("c:a", f, "a.txt")                         # 看过没变 → 放行
refused(lambda: F.check_write("c:b", f, "a.txt"), "没读过就要覆盖")   # A 看过不授权 B
os.utime(f, ns=(1, 1))                                   # 被人改了（版本变）
msg = refused(lambda: F.check_write("c:a", f, "a.txt"), "读过之后文件被改过")
assert "read_file" in msg
refused(lambda: F.check_edit("c:a", f, "a.txt"), "读过之后文件被改过")
F.check_edit("c:b", f, "a.txt")                          # edit 没看过照常（old_string 一字不差兜底）
F.observe("c:a", f); F.check_edit("c:a", f, "a.txt")     # 重读后放行
g = d / "b.txt"
F.observe("c:a", g)                                      # 看时不存在
assert F.prior("c:a", g) == F.ABSENT
F.check_write("c:a", g, "b.txt")
g.write_text("别人建的")
refused(lambda: F.check_write("c:a", g, "b.txt"), "文件刚被别人建了")
F.observe("c:a", g); F.check_write("c:a", g, "b.txt")    # present → absent → present
g.unlink(); F.check_write("c:a", g, "b.txt")             # 看过后被删：允许重建
assert F.prior("c:a", d / "." / "a.txt") is not None     # 路径归一（./a 与 a 同一个）
old = (F.OWNERS_MAX, F.PATHS_MAX); F.OWNERS_MAX, F.PATHS_MAX = 3, 2
F._seen.clear()
for i in range(5):
    F.observe(f"c:{i}", f)
assert list(F._seen) == ["c:2", "c:3", "c:4"]
for n in "xyz":
    F.observe("c:4", d / n)
assert len(F._seen["c:4"]) == 2 and F.prior("c:4", f) is None
F.OWNERS_MAX, F.PATHS_MAX = old; F._seen.clear()

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

async def seed():
    async with SessionLocal() as db:
        conv = Conversation(title="改文件"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("改一下")))
        await db.commit()
        return conv.id
cid = asyncio.run(seed())
events = []
async def emit(ev):
    events.append(ev)
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=emit)


async def seed(title):
    async with SessionLocal() as db:
        conv = Conversation(title=title); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("改一下")))
        await db.commit()
        return conv.id
async def turn(cid):
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))

# ---- 4. 真实一轮（模拟模型）：用户放了一个文件，助手直接 write_file 覆盖 → 被拒；read_file 后覆盖成功 ----
ws = project_dir(workspaces.PERSONAL)
(ws / "notes.md").write_text("用户自己写的笔记\n")
cid = asyncio.run(seed("覆盖"))
script.extend([
    [("write_file", {"path": "notes.md", "content": "助手的新内容\n"})],
    [("read_file", {"path": "notes.md", "limit": 200})],
    [("write_file", {"path": "notes.md", "content": "助手的新内容\n"})],
    [("edit_file", {"path": "notes.md", "old_string": "新内容", "new_string": "第二版"})],
    "好了。"])
reply = asyncio.run(turn(cid))
assert [(s["tool"], s["state"]) for s in reply.steps] == [("write_file", "error"), ("read_file", "done"),
                                                           ("write_file", "done"), ("edit_file", "done")], reply.steps
assert reply.steps[0]["note"] == "没读过就要覆盖" and "change" not in reply.steps[0]
assert (ws / "notes.md").read_text() == "助手的新内容\n".replace("新内容", "第二版")

# ---- 5. 下一轮（同一对话，跨轮记得）：后台/用户改了文件 → edit / write 都拒；重读后再改 ----
import time
time.sleep(0.01)
(ws / "notes.md").write_text("用户又改了：助手的第二版\n")
script.extend([
    [("edit_file", {"path": "notes.md", "old_string": "第二版", "new_string": "第三版"})],
    [("write_file", {"path": "notes.md", "content": "冲掉\n"})],
    [("read_file", {"path": "notes.md"})],
    [("edit_file", {"path": "notes.md", "old_string": "第二版", "new_string": "第三版"})],
    "好了。"])
reply = asyncio.run(turn(cid))
assert [(s["tool"], s["state"], s.get("note")) for s in reply.steps] == [
    ("edit_file", "error", "读过之后文件被改过"), ("write_file", "error", "读过之后文件被改过"),
    ("read_file", "done", None), ("edit_file", "done", None)], reply.steps
assert (ws / "notes.md").read_text() == "用户又改了：助手的第三版\n"

# ---- 6. 另一段对话没读过：不能覆盖；自己新建的文件可以反复写 ----
cid2 = asyncio.run(seed("别的对话"))
script.extend([
    [("write_file", {"path": "notes.md", "content": "x\n"}), ("write_file", {"path": "new/out.txt", "content": "1\n"})],
    [("write_file", {"path": "new/out.txt", "content": "2\n"})],
    "好。"])
reply = asyncio.run(turn(cid2))
assert [(s["tool"], s["state"]) for s in reply.steps] == [("write_file", "error"), ("write_file", "done"),
                                                           ("write_file", "done")], reply.steps
assert (ws / "new/out.txt").read_text() == "2\n" and (ws / "notes.md").read_text().startswith("用户又改了")
print("smoke_file_seen ok")
