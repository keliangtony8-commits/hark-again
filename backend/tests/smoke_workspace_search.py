# 冒烟：v1.35 工作区搜索 glob + grep（app/workspace_search.py 唯一规则）。模拟模型，不用沙盒。
# 1) glob：任意深度文件名 / 带 / 的路径模式 / {a,b} / [!x] / 新改的在前 / 隐藏与依赖目录默认跳过、明确指进去才搜 / 越界与不存在；
# 2) grep：分组 + 行号、CRLF、二进制跳过、ignore_case、include、fixed、正则写错、context、命中过多内联前 100 条全量落盘、
#    超大文件跳过、文件数上限如实说没搜完；
# 3) 一轮里 glob + grep + 写错的 grep：时间线标题“找文件/搜索内容”、摘要取 pattern、失败步带原因。
# 运行：python tests/smoke_workspace_search.py
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


ws = project_dir(workspaces.PERSONAL)
def put(rel, text, age=0, data=None):
    p = ws / rel; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data) if data is not None else p.write_text(text)
    t = time.time() - age; os.utime(p, (t, t))
put("src/app.py", "import os\ndef load_user(id):\n    return db.get(id)  # TODO cache\n", age=3600)
put("src/util/helpers.py", "def load_users():\n    pass\n# todo: tests\n", age=60)
put("src/web/page.tsx", "export const Page = () => null // TODO\n", age=10)
put("docs/readme.md", "Load User docs\n", age=86400 * 3)
put("node_modules/lib/index.js", "// TODO in deps\n")
put(".jobs/j1/log", "Traceback: boom TODO\n")
put(".home/.local/x.py", "TODO\n")
put("img.png", "", data=b"\x89PNG\0\0TODO")
put("crlf.txt", "a\r\nTODO here\r\n")

# ---- 1. glob 规则 ----
m = S.matcher
assert m("*.py")("src/util/helpers.py") and not m("*.py")("src/page.tsx")
assert m("src/**/*.py")("src/app.py") and m("src/**/*.py")("src/util/helpers.py") and not m("src/*.py")("src/util/helpers.py")
assert m("*.{ts,tsx}")("a/b.tsx") and not m("*.{ts,tsx}")("a/b.js")
assert m("./docs/*.md")("docs/readme.md") and m("[!a]*.md")("b.md") and not m("[!a]*.md")("a.md")
for bad, word in (("", "不能为空"), ("*.{py", "大括号")):
    try: m(bad); raise AssertionError(bad)
    except S.SearchError as e: assert word in str(e), e
for bad in ("*.py,*.md", "!*.py"):
    try: S.check_include(bad); raise AssertionError(bad)
    except S.SearchError as e: assert e.short == "include 写错了"
S.check_include("*.{py,md}")

g = S.glob("me", "*.py")
lines = g.splitlines()
assert lines[0].startswith("工作区里找到 2 个"), g
assert lines[1].startswith("src/util/helpers.py") and lines[2].startswith("src/app.py"), g  # 新改的在前
assert "node_modules" not in g and ".home" not in g and "1 分钟前" in g and "1 小时前" in g, g
assert "src/web/page.tsx" in S.glob("me", "**/*.tsx", "src")
assert S.glob("me", "web/*.tsx", "src").count("page.tsx") == 1  # 带 / 相对搜索根
assert "没有文件名匹配" in S.glob("me", "*.rs")
assert "index.js" in S.glob("me", "*.js", "node_modules")  # 明确指进依赖目录才搜
try: S.glob("me", "*", "nope"); raise AssertionError
except S.SearchError as e: assert e.short == "路径不存在"
try: S.glob("me", "*", "../.."); raise AssertionError
except S.SearchError as e: assert e.short == "路径越界"

# ---- 2. grep 规则 ----
r = S.grep("me", "TODO")
assert "src/app.py\n  3:     return db.get(id)  # TODO cache" in r, r
assert "crlf.txt\n  2: TODO here" in r and "\r" not in r, r
assert "node_modules" not in r and ".jobs" not in r and ".home" not in r and "img.png" not in r, r
assert "跳过 " not in r.splitlines()[0]
assert "# todo" not in r and "# todo: tests" in S.grep("me", "todo", ignore_case=True)
assert "page.tsx" in S.grep("me", "TODO", include="*.{ts,tsx}") and "app.py" not in S.grep("me", "TODO", include="*.tsx")
assert "Traceback" in S.grep("me", "boom", ".jobs/j1/log")  # 明确指进隐藏目录
assert "load_users" in S.grep("me", r"def load_\w+\(")
assert "src/app.py" in S.grep("me", "db.get(id)", fixed=True)
try: S.grep("me", "db.get(id"); raise AssertionError
except S.SearchError as e: assert e.short == "正则写错了" and "fixed=true" in str(e)
c = S.grep("me", "return db", context=1)
assert "  2- def load_user(id):" in c and "  3:     return db.get(id)" in c and "  1- import os" not in c, c
nf = S.grep("me", "zzz_nothing")
assert nf.startswith("工作区里没有找到 zzz_nothing"), nf

# rg 预筛与纯 Python 两条路结果一字不差；rg 不认的正则（环视）自动走 Python
import shutil
HAS_RG = shutil.which("rg") is not None
rg_bin = S._rg_bin
QUERIES = [dict(pattern="TODO"), dict(pattern="todo", ignore_case=True), dict(pattern="db.get(id)", fixed=True),
           dict(pattern="TODO", include="*.{ts,tsx}"), dict(pattern="return db", context=1), dict(pattern="zzz_nothing"),
           dict(pattern="TODO", path="src"), dict(pattern="boom", path=".jobs/j1"), dict(pattern="(?<=def )load_\\w+")]
with_rg = [S.grep("me", **q) for q in QUERIES]
S._rg_bin = lambda: None
no_rg = [S.grep("me", **q) for q in QUERIES]
assert "二进制" in S.grep("me", "zzz_nothing")  # Python 路会数二进制
for q, a, b in zip(QUERIES, with_rg, no_rg):
    if q["pattern"] == "zzz_nothing":
        assert a.startswith(b.split("（")[0]), (a, b)
    else:
        assert a == b, (q, a, b)
assert "load_users" in no_rg[-1] and "load_user(" in no_rg[-1]
if HAS_RG:
    S._rg_bin = rg_bin
    w = S.Walk(*S.resolve("me", ""))
    cands = S.rg_candidates(w, "TODO", False, False)
    rels = sorted(w.rel(p) for p in cands)
    assert rels == ["crlf.txt", "src/app.py", "src/web/page.tsx"], rels  # 隐藏/依赖目录、二进制都被排除
    assert S.rg_candidates(w, "(?<=x)y", False, False) is None  # rg 不认 → 走 Python
    assert "index.js" in S.grep("me", "TODO", path="node_modules")  # 起点在依赖目录里照搜
S._rg_bin = lambda: None  # 下面的上限测试走 Python 路（rg 会安静跳过大文件）

# 很多命中：内联前 GREP_MAX 条，全量落盘
put("big/log.txt", "\n".join(f"line {i} ERROR x" for i in range(400)))
b = S.grep("me", "ERROR", "big")
assert b.startswith("「big」里找到 400 处"), b[:80]
assert "  100: line 99 ERROR" in b and "line 100 ERROR" not in b and ".spill/" in b and len(b) <= S.INLINE_CHARS + 400, b[-300:]
where = b.split("完整结果存在 ")[1].split("，")[0]
assert (ws / where).read_text().count("ERROR x") == 400
# 超大文件跳过
S.FILE_MAX_BYTES, old = 10, S.FILE_MAX_BYTES
assert "超过" in S.grep("me", "zzz")
S.FILE_MAX_BYTES = old
# 文件数上限 → 如实说没搜完
S.FILES_MAX, old = 3, S.FILES_MAX
assert "没搜完" in S.grep("me", "TODO") and "没走完" in S.glob("me", "*")
S.FILES_MAX = old

S._rg_bin = rg_bin

# ---- 3. 一轮（模拟模型）：时间线标题与摘要、失败步 ----
async def seed():
    async with SessionLocal() as db:
        conv = Conversation(title="搜"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("找找 TODO")))
        await db.commit()
        return conv.id
cid = asyncio.run(seed())
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))
script.extend([[("glob", {"pattern": "*.py"}), ("grep", {"pattern": "TODO", "include": "*.py"}),
                ("grep", {"pattern": "(", "path": "src"})], "找到了。"])
reply = asyncio.run(turn())
st = reply.steps
assert [(s["tool"], s["state"], s["title"], s["detail"]) for s in st] == [
    ("glob", "done", "找文件", "*.py"), ("grep", "done", "搜索内容", "TODO"), ("grep", "error", "搜索内容", "(")], st
assert st[2]["note"] == "正则写错了"
from app.agent.tools import REGISTRY
assert {"glob", "grep"} <= set(REGISTRY) and REGISTRY["grep"].scope == "always"
assert "grep" in workspaces.ENVIRONMENT and "glob" in workspaces.ENVIRONMENT
print("smoke_workspace_search ok")
