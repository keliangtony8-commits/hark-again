# 冒烟：v1.34 精确改文件 edit_file（app/file_edit.py 唯一规则）+ 文件改动摘要进活动时间线。模拟模型，不用沙盒。
# 1) 规则单测：精确唯一替换、不唯一报行号、replace_all、没找到、新旧相同、空 old、CRLF 保留、宽松匹配按原缩进重排、
#    宽松也不唯一则不改；diff 统计与截断；
# 2) 一轮里 write_file 新建 → edit_file 改一行 → edit_file 不唯一（失败）→ write_file 覆盖：
#    时间线步骤带 change（+N −M、diff、created），失败那步 error + 原因、无 change，文件内容正确；
# 3) 本对话全部文件把 edit_file 改过的文件也算“助手写的”；
# 4) 磁盘满时变大的修改被拒、变小的修改照常。
# 运行：python tests/smoke_edit_file.py
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

from app import conversation_files, file_edit, llm, quota, workspaces
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message
from app.storage import project_dir

# ---- 1. 规则 ----
E, A = file_edit.EditError, file_edit.apply
def fails(fn, word):
    try:
        fn()
    except E as e:
        assert word in str(e), (word, str(e)); return e
    raise AssertionError("应该失败")
src = "a = 1\nb = 2\na = 1\n"
assert A(src, "b = 2", "b = 3").text == "a = 1\nb = 3\na = 1\n"
e = fails(lambda: A(src, "a = 1", "a = 9"), "第 1、3 行"); assert e.short == "匹配到 2 处，不唯一"
r2 = A(src, "a = 1", "a = 9", replace_all=True); assert r2.count == 2 and r2.text.count("a = 9") == 2 and not r2.loose
fails(lambda: A(src, "zzz", "y"), "read_file")
fails(lambda: A(src, "b = 2", "b = 2"), "一样")
fails(lambda: A(src, "", "x"), "write_file")
crlf = "x\r\ny\r\nz\r\n"
assert A(crlf, "y\n", "Y\n").text == "x\r\nY\r\nz\r\n"  # 模型给 \n，文件 \r\n 保留
py = "def f():\n    if x:\n        return 1\n    return 2\n"
lo = A(py, "if x:\n    return 1", "if x:\n    log()\n    return 1")  # 模型丢了缩进
assert lo.loose and lo.count == 1 and lo.text == "def f():\n    if x:\n        log()\n        return 1\n    return 2\n", lo.text
assert A("k = 1   \nm\n", "k = 1\nm", "k = 2\nm").text == "k = 2\nm\n"  # 行尾空白
fails(lambda: A("  p\n  q\n  p\n  q\n", "p\nq", "r"), "忽略空白后")
assert A("  p\n  q\n  p\n  q\n", "p\nq", "r", replace_all=True).text == "  r\n  r\n"
assert A("one\ntwo\nthree\n", "two\n", "").text == "one\nthree\n"  # 删一行
c = file_edit.change("a.py", "1\n2\n3\n", "1\n2b\n3\n4\n")
assert (c["added"], c["removed"]) == (2, 1) and "-2" in c["diff"] and "+2b" in c["diff"] and "---" not in c["diff"], c
assert file_edit.change("n.md", None, "hi\n")["created"] is True
big = file_edit.change("big", "", "\n".join(str(i) for i in range(1000)))
assert big["added"] == 1000 and "还有" in big["diff"] and len(big["diff"]) <= file_edit.DIFF_CHARS + 40
assert file_edit.stat(c) == "+2 −1"
sec = file_edit.change("cfg.py", "", 'API_KEY = "sk-123"\npassword: hunter2\nname = x\n')
assert "sk-123" not in sec["diff"] and "hunter2" not in sec["diff"] and 'API_KEY = ••••' in sec["diff"] and "name = x" in sec["diff"], sec
env = file_edit.change(".env", None, "A=1\n"); assert env["hidden"] and env["diff"] == "" and env["added"] == 1, env
assert "hidden" not in file_edit.change("notes.md", None, "x\n")

# ---- 2. 一轮 ----
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

script.extend([
    [("write_file", {"path": "src/app.py", "content": "x = 1\ny = 2\nx = 1\n"})],
    [("edit_file", {"path": "src/app.py", "old_string": "y = 2", "new_string": "y = 3\nz = 4"})],
    [("edit_file", {"path": "src/app.py", "old_string": "x = 1", "new_string": "x = 0"}),
     ("edit_file", {"path": "nope.py", "old_string": "a", "new_string": "b"})],
    [("write_file", {"path": "src/app.py", "content": "done\n"})],
    "改好了。"])
reply = asyncio.run(turn())
steps = reply.steps
assert [(s["tool"], s["state"]) for s in steps] == [("write_file", "done"), ("edit_file", "done"), ("edit_file", "error"),
                                                     ("edit_file", "error"), ("write_file", "done")], steps
assert [s["title"] for s in steps][:2] == ["写文件", "改文件"]
c0, c1, c4 = steps[0]["change"], steps[1]["change"], steps[4]["change"]
assert c0["created"] and c0["added"] == 3 and c0["path"] == "src/app.py", c0
assert (c1["added"], c1["removed"]) == (2, 1) and "+z = 4" in c1["diff"] and "created" not in c1, c1
assert steps[2]["note"] == "匹配到 2 处，不唯一" and "change" not in steps[2], steps[2]
assert steps[3]["note"] == "文件不存在"
assert c4["removed"] == 4 and c4["added"] == 1 and "created" not in c4, c4
st = [e for e in events if e["type"] == "tool.status" and e["state"] == "done"]
assert st[1]["step"]["change"] == c1  # 实时事件也带
ws = project_dir(workspaces.PERSONAL)
assert (ws / "src/app.py").read_text() == "done\n"

# ---- 3. 本对话全部文件 ----
async def files():
    async with SessionLocal() as db:
        conv = await db.get(Conversation, cid)
        from sqlalchemy import select
        msgs = (await db.execute(select(Message).where(Message.conversation_id == cid).order_by(Message.created_at))).scalars().all()
        return conversation_files.collect(conv, msgs)
fl = asyncio.run(files())
assert [f["id"] for f in fl] == ["src/app.py"] and fl[0]["origin"] == "written", fl

# ---- 4. 磁盘满 ----
(ws / "t.txt").write_text("aaaa bbbb\n")
real = quota.check
def full(w, adding=0):
    raise quota.QuotaError("满了")
quota.check = full
script.extend([[("edit_file", {"path": "t.txt", "old_string": "aaaa", "new_string": "aaaaaaaa"}),
                ("edit_file", {"path": "t.txt", "old_string": " bbbb", "new_string": ""})], "好。"])
events.clear()
reply = asyncio.run(turn())
quota.check = real
assert [s["state"] for s in reply.steps] == ["error", "done"] and reply.steps[0]["note"] == "工作区磁盘满了", reply.steps
assert (ws / "t.txt").read_text() == "aaaa\n"
print("smoke_edit_file ok")
