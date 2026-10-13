# 冒烟：v2.24 CORE 35 写文件前查“省略占位行”（core-gaps #2；移植 Gemini CLI omissionPlaceholderDetector，规则在 app/omission.py）。
# 1) Gemini 原测试逐条照搬；2) 我们加的：注释外壳 / … / 中文 / 散文文件更严 / 只认“新出现的”；
# 3) 一轮模拟模型：write_file 带占位被拒（文件不动）→ edit_file 带占位被拒 → apply_patch 带占位整份不动 →
#    文件里本来就有的占位行原样保留可写 → 正常写入成功。运行：python tests/smoke_omission.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', AUTO_TITLE="false")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import llm, omission as O, workspaces
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message
from app.storage import project_dir

tok = lambda s, p="a.py": [h.token for h in O.detect(s, p)]

# ---- 1. Gemini omissionPlaceholderDetector.test.ts ----
assert tok("(rest of methods ...)") == ["rest of methods ..."]
assert tok("(rest of code ...)") == ["rest of code ..."]
assert tok("(unchanged code ...)") == ["unchanged code ..."]
assert tok("// rest of methods ...") == ["rest of methods ..."]
assert tok("(Rest Of Methods ...)") == ["rest of methods ..."]
assert tok("class Example {\n  run() {}\n  (rest of methods ...)\n  (unchanged code ...)\n}") == ["rest of methods ...", "unchanged code ..."]
assert tok('const note = "(rest of methods ...)";\nconsole.log(note);') == []
assert tok("return value; // rest of methods ...") == []
assert tok('const message = "loading...";') == []

# ---- 2. 我们加的 ----
yes = {"// ... existing code ...": "existing code ...", "# ... rest of the file unchanged ...": "rest of file ...",
       "# rest of the code remains unchanged": "rest of code ...", "<!-- rest of html ... -->": "rest of html ...",
       "/* other methods … */": "other methods ...", "{/* rest of component ... */}": "rest of component ...",
       "-- rest of query ...": "rest of query ...", "   * rest of methods …": "rest of methods ...",
       "# 其余代码不变": "其余代码不变 ...", "// 其余代码保持不变……": "其余代码保持不变 ...", "（此处省略……）": "此处省略 ...",
       "# 以下省略": "以下省略 ...", "【原有逻辑不变】": "原有逻辑不变 ...", "// 其余方法 ...": "其余方法 ..."}
for s, t in yes.items():
    assert tok(s) == [t], (s, tok(s))
no = ["...", "// ...", "# other methods here", "# Rest of setup", "rest ... of code", "# 同上", "# 保持不变", "  # 省略",
      "x = 1  # 其余不变", "其余代码不变", "print('rest of code ...')", "# rest of my notes ...", "x" * 300 + " rest of code ..."]
for s in no:
    assert tok(s) == [], (s, tok(s))
# 散文：小说里的“此处省略一万字”“（此处省略……）”是正文；“其余内容不变……”仍算；英文要带省略号
assert tok("（此处省略一万字）", "a.md") == [] and tok("（此处省略……）", "story.txt") == []
assert tok("（其余内容不变……）", "a.md") == ["其余内容不变 ..."]
assert tok("rest of chapter unchanged", "a.md") == [] and tok("(rest of text ...)", "a.md") == ["rest of text ..."]
assert O.is_prose("Docs/A.MD") and not O.is_prose("a.py")
# 只认新出现的：之前就有同样的一行不算；多出来的那一处才算（按次数）
assert O.introduced("a\n# 其余代码不变\n", "b\n# 其余代码不变\n") == []
h = O.introduced("a\n# 其余代码不变\n", "# 其余代码不变\nb\n# 其余代码不变\n")
assert [(x.line, x.token) for x in h] == [(3, "其余代码不变 ...")], h
assert O.introduced(None, "x\r\n// rest of code ...\r\n")[0].line == 2
assert O.introduced("", "print(1)\n") == []
msg = O.refusal("a.py", [O.Hit(i, f"// rest {i}", "t") for i in range(1, 6)])
assert "第 1 行「// rest 1」" in msg and "等 5 处" in msg and "第 4 行" not in msg and "write_file" not in msg.split("：")[0]
assert "edit_file / apply_patch" in msg and "new_string" in O.refusal("a.py", h, "edit_file")

# ---- 3. 一轮 ----
script: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
n = [0]
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    step = script.pop(0)
    async def gen():
        if isinstance(step, list):
            n[0] += 1
            yield chunk(tool=[NS(index=i, id=f"c{n[0]}-{i}", function=NS(name=nm, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (nm, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()

ws = project_dir(workspaces.PERSONAL); ws.mkdir(parents=True, exist_ok=True)
orig = "def a():\n    return 1\n\ndef b():\n    return 2\n"
(ws / "m.py").write_text(orig)
(ws / "keep.py").write_text("x = 1\n# 其余代码不变\n")

async def seed():
    async with SessionLocal() as db:
        conv = Conversation(title="占位"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("改一下")))
        await db.commit()
        return conv.id
cid = asyncio.run(seed())
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))

patch = ("*** Begin Patch\n*** Add File: new.py\n+print(1)\n*** Update File: m.py\n@@\n def b():\n-    return 2\n"
         "+    # ... existing code ...\n+    return 3\n*** End Patch")
script.extend([
    [("read_file", {"path": "m.py"}), ("read_file", {"path": "keep.py"})],
    [("write_file", {"path": "m.py", "content": "def a():\n    return 9\n\n# rest of methods ...\n"})],
    [("edit_file", {"path": "m.py", "old_string": "    return 2", "new_string": "    # 其余代码保持不变\n    return 3"})],
    [("apply_patch", {"patch": patch})],
    [("write_file", {"path": "keep.py", "content": "x = 2\n# 其余代码不变\n"})],
    [("edit_file", {"path": "m.py", "old_string": "return 2", "new_string": "return 3"})],
    "改好了。"])
reply = asyncio.run(turn())
st = [(s["tool"], s["state"], s.get("note")) for s in reply.steps]
assert st == [("read_file", "done", None), ("read_file", "done", None), ("write_file", "error", O.SHORT),
              ("edit_file", "error", O.SHORT), ("apply_patch", "error", O.SHORT), ("write_file", "done", None),
              ("edit_file", "done", None)], st
assert "change" not in reply.steps[2] and "change" not in reply.steps[4]
assert (ws / "m.py").read_text() == orig.replace("return 2", "return 3")      # 被拒的三次都没动它
assert not (ws / "new.py").exists()                                            # 补丁整份不动
assert (ws / "keep.py").read_text() == "x = 2\n# 其余代码不变\n"               # 原有的占位行照旧可写
print("ok smoke_omission")
