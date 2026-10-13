# 冒烟：v1.69 apply_patch 多文件补丁（app/apply_patch.py，移植 Codex apply-patch：解析、compute_replacements、
# SourceFile 换行保留；Codex 的 25 个端到端场景 fixtures 原样复制在 tests/fixtures/apply_patch/，Apache-2.0）。
# 模拟模型，不用沙盒。运行：python tests/smoke_apply_patch.py
import os, sys, asyncio, subprocess, tempfile, json, shutil
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', AUTO_TITLE="false",
  NEXT_SPEAKER_CHECK="off")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from pathlib import Path
from app import apply_patch as AP, llm, workspaces, conversation_files
from app.apply_patch import Chunk, Hunk, PatchError


def wrap(body: str) -> str:
    return f"*** Begin Patch\n{body}\n*** End Patch"


def err(text: str) -> str:
    try:
        AP.parse(text)
    except PatchError as e:
        return str(e)
    raise AssertionError(f"应当报错：{text!r}")


# ---- parser.rs test_parse_patch / lenient / end-of-file（Codex 单测翻译）
assert "第一行必须是 '*** Begin Patch'" in err("bad")
assert "最后一行必须是 '*** End Patch'" in err("*** Begin Patch\nbad")
assert AP.parse("*** Begin Patch \n*** Add File: foo\n+hi\n *** End Patch") == [Hunk("add", "foo", "hi\n")]
assert "第 2 行" in err("*** Begin Patch\n*** Update File: test.py\n*** End Patch") and "test.py" in err(
    "*** Begin Patch\n*** Update File: test.py\n*** End Patch")
assert AP.parse("*** Begin Patch\n*** End Patch") == []
hs = AP.parse("*** Begin Patch\n*** Add File: path/add.py\n+abc\n+def\n*** Delete File: path/delete.py\n"
              "*** Update File: path/update.py\n*** Move to: path/update2.py\n@@ def f():\n-    pass\n+    return 123\n*** End Patch")
assert hs == [Hunk("add", "path/add.py", "abc\ndef\n"), Hunk("delete", "path/delete.py"),
              Hunk("update", "path/update.py", move_to="path/update2.py",
                   chunks=[Chunk("def f():", ["    pass"], ["    return 123"])])], hs
hs = AP.parse("*** Begin Patch\n*** Update File: file.py\n@@\n+line\n*** Add File: other.py\n+content\n*** End Patch")
assert hs == [Hunk("update", "file.py", chunks=[Chunk(None, [], ["line"])]), Hunk("add", "other.py", "content\n")]
p2 = "*** Begin Patch\n*** Update File: file2.py\n import foo\n+bar\n*** End Patch"
want = [Hunk("update", "file2.py", chunks=[Chunk(None, ["import foo"], ["import foo", "bar"], [(0, 0)])])]
assert AP.parse(p2) == want
for wrapped in (f"<<EOF\n{p2}\nEOF\n", f"<<'EOF'\n{p2}\nEOF\n", f'<<"EOF"\n{p2}\nEOF\n'):
    assert AP.parse(wrapped) == want
assert "第一行" in err(f"<<\"EOF'\n{p2}\nEOF\n")
assert "最后一行" in err("<<EOF\n*** Begin Patch\n*** Update File: file2.py\nEOF\n")
assert AP.parse(f"```diff\n{p2}\n```") == want                                         # 嫁接：代码块围栏
eof = AP.parse("*** Begin Patch\n*** Update File: file.txt\n@@\n+quux\n*** End of File\n\n*** End Patch")
assert eof[0].chunks == [Chunk(None, [], ["quux"], [], True)]
assert "Environment ID" in err("*** Begin Patch\n*** Environment ID: remote\n*** Add File: a\n+x\n*** End Patch")

# ---- streaming_parser.rs 用例
ind = AP.parse(wrap("*** Update File: a.txt\n@@\n  *** Update File: not-a-header\n-x\n+y"))      # 缩进的段头 = 上下文
assert ind[0].chunks[0].old == [" *** Update File: not-a-header", "x"], ind
bare = AP.parse(wrap("*** Update File: a.txt\n@@\n a\n\n-b\n+B"))
assert bare[0].chunks[0].old == ["a", "", "b"] and bare[0].chunks[0].new == ["a", "", "B"]
assert AP.parse(wrap("*** Update File: a.txt\n@@\n-x\n+y\n*** End of File\n\n\n"))[0].chunks[0].eof
# E2E B10：Add File 里的裸空行——后面还有 + 行 = 空内容行；紧跟段头 / End Patch = 段间空行，丢掉
b10 = AP.parse(wrap("*** Add File: n1.md\n+# 标题\n\n+正文\n\n\n*** Add File: n2.md\n+a\n   \n+b\n\n"))
assert [h.contents for h in b10] == ["# 标题\n\n正文\n", "a\n\nb\n"], b10
assert AP.parse(wrap("\n*** Delete File: x\n\n*** Add File: y\n+1")) == [Hunk("delete", "x"), Hunk("add", "y", "1\n")]
assert "新建文件的内容每行都要以 + 开头" in err(wrap("*** Add File: z\n+1\nnot plus"))    # 真乱码仍报错
crlf = AP.parse("*** Begin Patch\r\n*** Update File: a.txt\r\n@@\r\n-x\r\n+y\r\n*** End Patch\r\n")
assert crlf[0].chunks[0].old == ["x"] and crlf[0].chunks[0].new == ["y"]
assert "之后不能再有内容" in err("*** Begin Patch\n*** Add File: a\n+x\n*** End Patch\nmore\n*** End Patch")
assert "不是有效的段头" in err(wrap("bad"))
assert "不是有效的段头" in err(wrap("*** Add File: a\nbad"))
assert "不是有效的段头" in err(wrap("*** Delete File: a\nbad"))
assert "'file.txt' 的段是空的" in err(wrap("*** Update File: file.txt"))
assert "'old.txt' 的段是空的" in err(wrap("*** Update File: old.txt\n*** Move to: new.txt"))
assert "没有任何改动行" in err(wrap("*** Update File: a\n@@"))
assert "没有任何改动行" in err(wrap("*** Update File: a\n@@\n*** End of File"))
assert "意外的一行：'@@'" in err(wrap("*** Update File: a\n@@\n@@"))
assert "要以 @@ 开头" in err(wrap("*** Update File: a\n@@\n-x\nbad"))
assert "意外的一行：'*** Update File: other.txt'" in err(wrap("*** Update File: a\n@@\n*** Update File: other.txt"))

# ---- file_update_tests.rs / lib.rs（纯文本层）
upd = lambda text, body: AP.update_text(text, "f", AP.parse(wrap("*** Update File: f\n" + body))[0].chunks)
assert upd("foo\nbar\nbaz\nqux\n", "@@\n foo\n-bar\n+BAR\n@@\n baz\n-qux\n+QUX") == "foo\nBAR\nbaz\nQUX\n"
assert upd("foo\nbar\nbaz\n", "@@\n-foo\n+FOO\n bar\n") == "FOO\nbar\nbaz\n"
assert upd("foo\nbar\nbaz\n", "@@\n foo\n bar\n-baz\n+BAZ\n") == "foo\nbar\nBAZ\n"
assert upd("foo\nbar\nbaz\n", "@@\n+quux\n*** End of File") == "foo\nbar\nbaz\nquux\n"
assert upd("a\nb\nc\nd\ne\nf\n", "@@\n a\n-b\n+B\n@@\n d\n-e\n+E\n@@\n f\n+g\n*** End of File") == "a\nB\nc\nd\nE\nf\ng\n"
assert upd("line1\nline2\nline3\n", "@@\n+after-context\n+second-line\n@@\n line1\n-line2\n-line3\n+line2-replacement") \
    == "line1\nline2-replacement\nafter-context\nsecond-line\n"                         # test_pure_addition_chunk_followed_by_removal
assert upd("import asyncio  # local import \u2013 avoids top\u2011level dep\n",
           "@@\n-import asyncio  # local import - avoids top-level dep\n+import asyncio  # HELLO") == "import asyncio  # HELLO\n"
assert upd("a\r\nb\r\nc\r\n", "@@\n a\n-b\n+B\n+B2") == "a\r\nB\r\nB2\r\nc\r\n"     # CRLF 保留，新行用首选换行
assert upd("x\ny", "@@\n x\n-y\n+Y") == "x\nY\n"                                      # 补上结尾换行
assert upd("def f():\n    pass\ndef g():\n    pass\n", "@@ def g():\n-    pass\n+    return 1") == "def f():\n    pass\ndef g():\n    return 1\n"
try:
    upd("a\nb\n", "@@ nope\n-a\n+b"); raise AssertionError
except PatchError as e:
    assert "定位行" in str(e) and e.short == "补丁对不上原文"

# ---- Codex 端到端场景（fixtures 原样；015 改为我们的“全成或全不动”）
def snap(d: Path) -> dict:
    return {p.relative_to(d).as_posix(): ("DIR" if p.is_dir() else p.read_bytes()) for p in sorted(d.rglob("*"))} if d.is_dir() else {}
base = Path(__file__).parent / "fixtures" / "apply_patch"
scenarios = sorted(x for x in base.iterdir() if x.is_dir())
assert len(scenarios) == 25, len(scenarios)
for sc in scenarios:
    t = Path(tempfile.mkdtemp())
    before = {}
    if (sc / "input").is_dir():
        shutil.copytree(sc / "input", t, dirs_exist_ok=True)
        before = snap(t)
    try:
        AP.commit(AP.plan(t, AP.parse((sc / "patch.txt").read_text())))
    except PatchError:
        pass
    want = before if sc.name.startswith("015_") else snap(sc / "expected")
    assert snap(t) == want, (sc.name, snap(t), want)

# ---- 我们的规则：同一文件多段、改名链、路径、二进制、写盘失败整体还原、heredoc 识别
w = Path(tempfile.mkdtemp())
(w / "a.txt").write_text("1\n2\n3\n")
pl = AP.plan(w, AP.parse(wrap("*** Update File: a.txt\n@@\n-1\n+one\n*** Update File: a.txt\n*** Move to: b/c.txt\n@@\n-3\n+three")))
moved = [e for e in pl.entries if e.changed]
assert [(e.rel, e.after, e.moved_away) for e in moved] == [("a.txt", None, True), ("b/c.txt", "one\n2\nthree\n", False)]
assert moved[1].origin.rel == "a.txt" and moved[1].before_text == "1\n2\n3\n" and AP.summary(moved) == "改名 a.txt → b/c.txt"
pl = AP.plan(w, AP.parse(wrap("*** Add File: n.txt\n+x\n*** Update File: n.txt\n*** Move to: m.txt\n@@\n-x\n+y")))
assert AP.summary([e for e in pl.entries if e.changed]) == "新建 m.txt"                     # 新建再改名 = 新建
pl = AP.plan(w, AP.parse(wrap("*** Delete File: a.txt\n*** Add File: a.txt\n+fresh")))
assert AP.summary([e for e in pl.entries if e.changed]) == "修改 a.txt"
for bad, short in (("*** Add File: ../x\n+1", "路径越界"), ("*** Add File: .spill/x\n+1", "隐藏目录"),
                   ("*** Delete File: a.txt\n*** Delete File: a.txt", "文件不存在"),
                   ("*** Update File: a.txt\n@@\n-zzz\n+y", "补丁对不上原文")):
    try:
        AP.plan(w, AP.parse(wrap(bad))); raise AssertionError(bad)
    except PatchError as e:
        assert e.short == short, (bad, e.short, str(e))
(w / "bin.dat").write_bytes(b"\x00\x01\x02")
try:
    AP.plan(w, AP.parse(wrap("*** Update File: bin.dat\n@@\n-x\n+y"))); raise AssertionError
except PatchError as e:
    assert e.short == "不是文本文件"
assert AP.summary([e for e in AP.plan(w, AP.parse(wrap("*** Delete File: bin.dat"))).entries if e.changed]) == "删除 bin.dat"
pl = AP.plan(w, AP.parse(wrap("*** Update File: a.txt\n@@\n-1\n+uno\n*** Add File: deep/new/z.txt\n+z\n*** Delete File: bin.dat")))
orig_write = Path.write_bytes
def boom(self, data):
    if self.name == "z.txt":
        raise OSError(28, "No space left on device")
    return orig_write(self, data)
Path.write_bytes = boom
try:
    AP.commit(pl); raise AssertionError
except PatchError as e:
    assert e.short == "写盘失败" and "全部还原" in str(e)
finally:
    Path.write_bytes = orig_write
assert (w / "a.txt").read_text() == "1\n2\n3\n" and (w / "bin.dat").exists() and not (w / "deep").exists()
body = wrap("*** Add File: h.txt\n+hi")
assert AP.from_command(f"apply_patch <<'EOF'\n{body}\nEOF\n") == (body, "")
assert AP.from_command(f"cd sub && applypatch <<EOF\n{body}\nEOF") == (body, "sub")
assert AP.from_command(f"cd 'my dir' && apply_patch <<\"PATCH\"\n{body}\nPATCH\n") == (body, "my dir")
for no in (f"echo hi; apply_patch <<'EOF'\n{body}\nEOF", f"apply_patch <<'EOF'\n{body}\nEOF\n&& make", "apply_patch file.diff",
           f"cd $HOME && apply_patch <<EOF\n{body}\nEOF"):
    assert AP.from_command(no) is None, no

# ---- 真实一轮（模拟模型）：一次改三个文件 + 改名 + 删除，时间线一步带 changes，回复末尾改动卡；读后再改的护栏；heredoc 走补丁
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.db import SessionLocal
from app.models import Conversation, Message
from app.storage import project_dir

ws = workspaces.PERSONAL
wr = project_dir(ws)
(wr / "src").mkdir(exist_ok=True)
(wr / "src/app.py").write_text("def greet():\n    print(\"Hi\")\n\n\ndef main():\n    greet()\n")
(wr / "README.md").write_text("# demo\n用法：python app.py\n")
(wr / "obsolete.txt").write_text("old\n")
(wr / "keep.txt").write_text("别人的内容\n")

script: list = []
seen: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append([dict(m) for m in messages])
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

async def seed(text="改一下"):
    async with SessionLocal() as db:
        conv = Conversation(title="补丁"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=[{"type": "text", "text": text}]))
        await db.commit()
        return conv.id
async def turn(cid):
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))

PATCH = wrap("*** Add File: hello.txt\n+Hello world\n*** Update File: src/app.py\n*** Move to: src/main.py\n@@ def greet():\n"
             "-    print(\"Hi\")\n+    print(\"Hello, world!\")\n*** Update File: README.md\n@@\n # demo\n-用法：python app.py\n"
             "+用法：python src/main.py\n*** Delete File: obsolete.txt")
cid = asyncio.run(seed())
script.extend([[("apply_patch", {"patch": PATCH})], "改好了。"])
reply = asyncio.run(turn(cid))
assert (wr / "hello.txt").read_text() == "Hello world\n" and not (wr / "src/app.py").exists() and not (wr / "obsolete.txt").exists()
assert "Hello, world!" in (wr / "src/main.py").read_text() and "src/main.py" in (wr / "README.md").read_text()
step = reply.steps[0]
assert step["tool"] == "apply_patch" and step["state"] == "done" and "change" not in step, step
files = {c["path"]: c for c in step["changes"]}
assert set(files) == {"hello.txt", "src/main.py", "README.md", "obsolete.txt"}, files
assert files["hello.txt"]["created"] and files["src/main.py"]["moved_from"] == "src/app.py" and "created" not in files["src/main.py"]
assert files["src/main.py"]["added"] == 1 and files["src/main.py"]["removed"] == 1                 # diff 按原文件算
assert files["obsolete.txt"]["deleted"] and files["obsolete.txt"]["removed"] == 1
assert step["detail"].endswith("等 4 个文件"), step["detail"]
tool_msg = next(m for m in seen[1] if m.get("role") == "tool")
assert "已应用补丁（4 段）：新建 hello.txt，改名 src/app.py → src/main.py，修改 README.md，删除 obsolete.txt" in tool_msg["content"], tool_msg
card = reply.blocks[-1]
assert card["type"] == "changes" and {f["path"] for f in card["files"]} == {"hello.txt", "src/app.py", "src/main.py", "README.md", "obsolete.txt"}
async def conv_files():
    async with SessionLocal() as db:
        from sqlalchemy import select
        conv = await db.get(Conversation, cid)
        msgs = (await db.scalars(select(Message).where(Message.conversation_id == cid))).all()
        return conversation_files.collect(conv, msgs)
names = {i["name"] for i in asyncio.run(conv_files()) if i["origin"] == "written"}
assert names == {"hello.txt", "main.py", "README.md"}, names                                        # 删掉的不列

# 读后再改：Add 覆盖一个没读过的已有文件 → 整份拒绝，什么都不动（同 write_file）；读过就行
cid2 = asyncio.run(seed())
over = wrap("*** Update File: README.md\n@@\n-# demo\n+# DEMO\n*** Add File: keep.txt\n+覆盖")
script.extend([[("apply_patch", {"patch": over})], [("read_file", {"path": "keep.txt"})],
               [("apply_patch", {"patch": over})], "好。"])
r2 = asyncio.run(turn(cid2))
assert [s["state"] for s in r2.steps] == ["error", "done", "done"], r2.steps
assert r2.steps[0]["note"] == "没读过就要覆盖" and (wr / "keep.txt").read_text() == "覆盖\n" and "# DEMO" in (wr / "README.md").read_text()
assert r2.steps[2]["changes"][0]["path"] == "README.md"
# 格式错 / 对不上：失败步骤 + 原因，给模型的话以“补丁没有应用，什么都没改”开头
cid3 = asyncio.run(seed())
script.extend([[("apply_patch", {"patch": wrap("*** Update File: README.md\n@@\n-不存在的行\n+x")})], "我再看看。"])
r3 = asyncio.run(turn(cid3))
assert r3.steps[0]["state"] == "error" and r3.steps[0]["note"] == "补丁对不上原文"
assert "补丁没有应用，什么都没改" in next(m for m in seen[-1] if m.get("role") == "tool")["content"]
assert [b["type"] for b in r3.blocks] == ["text"]                                                   # 没改成：没有改动卡
# run_command 里 apply_patch heredoc：不进沙盒，直接按补丁改（Codex 的模型习惯）
(wr / "sub").mkdir(exist_ok=True)
cid4 = asyncio.run(seed())
cmd = "cd sub && apply_patch <<'EOF'\n" + wrap("*** Add File: x.txt\n+from heredoc") + "\nEOF\n"
script.extend([[("run_command", {"command": cmd})], "好。"])
r4 = asyncio.run(turn(cid4))
assert (wr / "sub/x.txt").read_text() == "from heredoc\n" and r4.steps[0]["state"] == "done", r4.steps
assert r4.steps[0]["change"]["path"] == "sub/x.txt" and r4.blocks[-1]["type"] == "changes"
# 真实复现（E2E t3）：模型一次写三篇笔记，标题后、文件之间都是裸空行 → 一次成功，没有多余的 "+"
cid5 = asyncio.run(seed())
notes = "*** Begin Patch\n" + "".join(f"*** Add File: notes/note{i}.md\n+# 笔记{i}\n\n+正文{i}\n\n" for i in (1, 2, 3)) + "*** End Patch"
script.extend([[("apply_patch", {"patch": notes})], "好。"])
r5 = asyncio.run(turn(cid5))
assert r5.steps[0]["state"] == "done", r5.steps
for i in (1, 2, 3):
    assert (wr / f"notes/note{i}.md").read_text() == f"# 笔记{i}\n\n正文{i}\n"
# 子助手也能用；工具 schema 自检
from app.agent import subagent
from app.agent.tools import REGISTRY
assert "apply_patch" in subagent.CHILD_TOOLS and "apply_patch" in REGISTRY
assert "改一处用 edit_file" in workspaces.ENVIRONMENT
script.clear()
print("smoke_apply_patch ok")
