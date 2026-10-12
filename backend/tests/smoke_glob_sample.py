# 冒烟：v1.43 glob 超上限时按顶层目录轮流抽样（移植自 deepseek-harness tool-fs-search glob.ts sampleAcrossTopLevel，
# 测试用例照搬它的 tests/tools.spec.ts「sampleAcrossTopLevel」一节）+ 我们的 glob 端到端。
import os, sys, asyncio, subprocess, tempfile, json, time
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import llm, spill, workspace_search as S, workspaces
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message
from app.storage import project_dir

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


f = S.sample_across_top_level
# ---- 移植的用例 ----
paths = ["v/a", "v/b", "v/c", "v/d", "src/e", "guide/f"]
assert f(paths, 3) == (["v/a", "src/e", "guide/f"], 3, 3)
assert f(paths, 5) == (["v/a", "v/b", "v/c", "src/e", "guide/f"], 3, 3)  # 第二圈只给还有剩的组，页面仍按组排
assert f(["solo/a", "many/b", "many/c", "many/d"], 3) == (["solo/a", "many/b", "many/c"], 2, 2)
n = 12500
big = [f"group-{i}/only" for i in range(n)] + [f"late/{i}" for i in range(n)]
t = time.monotonic(); items, shown, total = f(big, len(big) - 1)
assert (len(items), shown, total) == (len(big) - 1, n + 1, n + 1) and time.monotonic() - t < 2  # 不反复扫已用完的组
assert f(["a/1", "b/1", "c/1", "d/1"], 2) == (["a/1", "b/1"], 2, 4)
assert f(["/out/a", "/out/b", "/away/c", "/away/d"], 2) == (["/out/a", "/away/c"], 2, 2)
assert f(["a.ts", "b.ts", "c.ts"], 2) == (["a.ts", "b.ts"], 2, 3)  # 扁平 = 原来的最新前 N
assert f(["workspace/vendor/a.ts", "workspace/vendor/b.ts", "workspace/source/c.ts", "workspace/guides/d.md"], 3, "workspace") \
    == (["workspace/vendor/a.ts", "workspace/source/c.ts", "workspace/guides/d.md"], 3, 3)
assert f(["./vendor/a.ts", "./src/b.ts"], 2, ".") == (["./vendor/a.ts", "./src/b.ts"], 2, 2)
assert f(["/vendor/a.ts", "/src/b.ts"], 2, "/") == (["/vendor/a.ts", "/src/b.ts"], 2, 2)
assert f(["root/a/one", "root/a/two", "root/b/three"], 2, "root") == (["root/a/one", "root/b/three"], 2, 2)
assert f(["other/a.ts"], 1, "src") == (["other/a.ts"], 1, 1)
assert f(["src"], 1, "src") == (["src"], 1, 1)
assert f(["old\\one", "old\\two", "src/a"], 2) == (["old\\one", "old\\two"], 2, 3)  # 反斜杠是文件名字符
assert f([f"dir-{i}/file.txt" for i in range(125000)], 100)[1:] == (100, 125000)

# ---- 端到端：一个刚装完的大目录不再占满整页 ----
root = project_dir("me")  # noqa
now = time.time()
for i in range(300):  # 最新的 300 个都在 vendor/
    p = root / "vendor" / f"m{i}.py"; p.parent.mkdir(parents=True, exist_ok=True); p.write_text("x")
    os.utime(p, (now - i, now - i))
for d in ("src", "tools", "notes"):
    p = root / d / "main.py"; p.parent.mkdir(parents=True, exist_ok=True); p.write_text("y")
    os.utime(p, (now - 10000, now - 10000))
out = S.glob("me", "*.py")
assert "找到 303 个" in out, out[:200]
for d in ("src/main.py", "tools/main.py", "notes/main.py"):
    assert d in out, d  # 旧做法只列 vendor/ 的前 100 个，这三个都看不到
assert "按顶层目录轮流抽样（覆盖 4/4 个顶层目录）" in out and "read_file" in out
assert "想看某个目录" not in out
body = [l for l in out.splitlines() if l.endswith("前)") or "  (" in l]
assert len(body) == S.GLOB_MAX
# 页面按组：vendor 的 97 个连在一起（最新的在前），再是其余三个
assert body[0].startswith("vendor/m0.py") and body[96].startswith("vendor/m96.py") and body[97].startswith("notes/"), body[95:]
# 完整结果落盘，包含全部 303 条
spilled = out.split("完整结果存在 ")[1].split("，")[0]
full = (root / spilled).read_text() if not spilled.startswith("/") else open(spilled).read()
assert full.count(".py  (") == 303
# path 指进子目录：分组相对搜索根
for i in range(120):
    p = root / "pkg" / ("a" if i % 2 else "b") / f"f{i}.txt"; p.parent.mkdir(parents=True, exist_ok=True); p.write_text("z")
sub = S.glob("me", "*.txt", "pkg")
assert "覆盖 2/2 个顶层目录" in sub and "pkg/a/" in sub and "pkg/b/" in sub
# 扁平结果（全在根下）仍是“只列了前 N 行”的老说法
for i in range(150):
    (root / f"flat{i}.md").write_text("w")
flat = S.glob("me", "flat*.md")
assert "只列了前 100 行" in flat and "抽样" not in flat
# 在上限内：原样全列，没有任何附注
assert "抽样" not in S.glob("me", "main.py") and "只列了" not in S.glob("me", "main.py")

# ---- 模拟模型一轮：模型拿到的 glob 结果就是抽样页 ----
seen = []
async def spy(model, messages, **kw):
    seen.append([dict(m) for m in messages])
    return await fake_create(model, messages, **kw)
llm.client.chat.completions.create = spy
async def seed():
    async with SessionLocal() as db:
        conv = Conversation(title="找"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("工作区里有哪些 py 文件")))
        await db.commit()
        return conv.id
cid = asyncio.run(seed())
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))
script.extend([[("glob", {"pattern": "*.py"})], "vendor 里是一堆模块，src/tools/notes 各有 main.py。"])
reply = asyncio.run(turn())
assert [(s["tool"], s["state"]) for s in reply.steps] == [("glob", "done")], reply.steps
tool_msg = [m for m in seen[-1] if m.get("role") == "tool"][-1]["content"]
assert "notes/main.py" in tool_msg and "轮流抽样" in tool_msg
print("smoke_glob_sample OK")
