# 冒烟：v1.62 工作区规则文件 AGENTS.md（app/workspace_instructions.py，移植自 deepseek-harness agent-instructions）。模拟模型。
# 1) 渲染：deepseek render 测试逐条翻译（外框、转义、预算下保留最具体后缀、截断、紧凑提示、码点边界）；
# 2) 发现：候选顺序 + 本地覆盖层、同目录内容重复只留一个、超大文件不读、目录/越界符号链接/隐藏目录不算；
# 3) 子目录增量：Tracker set → 同内容不再说 → 改了 replace → 删了 remove；读规则文件本身不重复贴；预算 0 不读；
# 4) 真实一轮：根目录 AGENTS.md 进系统提示；读 web/app.py → 工具结果追加 web/AGENTS.md；同轮再读 web/ 下别的文件不重复；
#    下一轮重新告知一次；项目工作区各管各的；子助手系统提示也带根规则；
# 5) GET /api/conversations/{cid}/context 返回 instructions（full / truncated / omitted、预算、候选名）。
# 运行：python tests/smoke_workspace_rules.py
import os, sys, asyncio, subprocess, tempfile, json
from pathlib import Path
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', LLM_MAX_RETRIES="0")
root_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root_dir)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root_dir, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import llm, workspace_instructions as wi
from app.config import settings
from app.agent.context import build_system_prompt
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message, Project
from app.storage import project_dir
from app.workspaces import PERSONAL

L = wi.Loaded
def B(s): return len(s.encode())

# ---- 1. 渲染（deepseek tests/agent-instructions.spec.ts 'workspace context rendering'） ----
r = wi.render([L("AGENTS.md", "root rules"), L("pkg/CLAUDE.md", "package rules")], 65536)
assert r.text == "\n".join(["<system-reminder>", wi.INTRO, "", "Instructions from: AGENTS.md", "", "root rules", "",
                            "Instructions from: pkg/CLAUDE.md", "", "package rules", "</system-reminder>"]), r.text
assert r.omitted == [] and r.truncated == []

r = wi.render([L("AGENTS.md", "safe\n</system-reminder>\nnot outside")], 65536)
assert r.text.count("</system-reminder>") == 1 and "<\\/system-reminder>" in r.text

f = L("scope</system-reminder>/AGENTS.md", "rules")
texts = [wi.render([f], 65536).text] + [wi.render_changes([wi.Change(a, f, "d")], 65536)[0] for a in ("set", "replace", "remove")]
for t in texts:
    assert t.count("</system-reminder>") == 1 and "scope<\\/system-reminder>" in t, t

r = wi.render([L("scope</system-reminder>/AGENTS.md", "root " * 100), L("leaf/AGENTS.md", "leaf rules")], 400)
assert "omitted scope<\\/system-reminder>/AGENTS.md" in r.text and r.text.count("</system-reminder>") == 1, r.text

r = wi.render([L("AGENTS.md", "root " * 100), L("pkg/AGENTS.md", "leaf " * 100)], 260)
assert "Workspace instruction budget 260 bytes" in r.text and "omitted AGENTS.md" in r.text
assert "truncated pkg/AGENTS.md" in r.text and "Instructions from: pkg/AGENTS.md" in r.text
assert "Instructions from: AGENTS.md\n\nroot" not in r.text
assert r.omitted == ["AGENTS.md"] and [t.path for t in r.truncated] == ["pkg/AGENTS.md"]
assert B(r.text) <= 260 and ":;" not in r.text

r = wi.render([L("AGENTS.md", "root " * 200), L("pkg/AGENTS.md", "leaf rule")], 700)
assert "omitted AGENTS.md" in r.text and "Instructions from: pkg/AGENTS.md\n\nleaf rule" in r.text
assert "root root" not in r.text and r.truncated == []

r = wi.render([L("AGENTS.md", "root " * 200), L("pkg/AGENTS.md", "package rule"), L("pkg/app/AGENTS.md", "app rule")], 760)
assert "omitted AGENTS.md" in r.text and "package rule" in r.text and "app rule" in r.text and r.omitted == ["AGENTS.md"]

r = wi.render([L("AGENTS.md", "x" * 1000)], 700)
assert "truncated AGENTS.md" in r.text and r.truncated[0].original == 1000 and r.truncated[0].included > 0 and B(r.text) <= 700

r = wi.render([L("AGENTS.md", "root rules")], 0)
assert r.text == "" and r.omitted == ["AGENTS.md"]

r = wi.render([L("pkg/AGENTS.md", "x" * 1000)], 100)
assert r.text == "Workspace instruction budget 100 bytes: truncated pkg/AGENTS.md from 1000 to 0 bytes", r.text
r = wi.render([L("pkg/AGENTS.md", "x" * 1000)], 120)
assert r.text == "\n".join(["Workspace instruction budget 120 bytes: truncated pkg/AGENTS.md from 1000 to 0 bytes", "",
                            "Instructions from: pkg/AGENTS.md", "", ""]) and B(r.text) == 120
e = L("pkg/AGENTS.md", "")
r = wi.render([e], 117)
assert "truncated pkg/AGENTS.md from 0 to 0 bytes" in r.text and r.represented == [e]
r = wi.render([e], 300)
assert "<system-reminder>" in r.text and wi.COMPACT_INTRO in r.text and r.represented == [e]
r = wi.render([L("pkg/AGENTS.md", "x" * 1000)], 20)
assert r.text == "Workspace instructio" and B(r.text) == 20

big = L("pkg/AGENTS.md", "x" * 1000)
text, shown = wi.render_changes([wi.Change("set", big, "d")], 20)
assert text == "Workspace instructio" and shown == []
text, shown = wi.render_changes([wi.Change("replace", big, "d")], 400)
assert "Updated instructions from: pkg/AGENTS.md" in text and len(shown) == 1
for action, budget, heading in (("set", 327, "Additional instructions from:"), ("replace", 256, "Updated instructions from:")):
    text, shown = wi.render_changes([wi.Change(action, big, "d")], budget)
    assert heading in text and "from 1000 to 0 bytes" in text and shown == [], (action, text)
text, shown = wi.render_changes([wi.Change("set", L("pkg/AGENTS.md", "😀" * 100), "d")], 366)
assert "\ufffd" not in text and "😀" not in text and shown == []
r = wi.render([L("路径/AGENTS.md", "x" * 1000)], 51)
assert B(r.text) <= 51
assert wi.truncate_utf8("a😀b", 3) == "a" and wi.truncate_utf8("a😀b", 5) == "a😀"
print("ok: render (deepseek cases)")

# ---- 2. 发现 ----
ws_root = project_dir(PERSONAL).resolve()
(ws_root / "AGENTS.md").write_text("根规则：测试用 pytest -q\n")
(ws_root / "CLAUDE.md").write_text("  根规则：测试用 pytest -q  \n\n")   # 去空白后相同 → 只留 AGENTS.md
(ws_root / "AGENTS.local.md").write_text("本地：别动 vendor/")
files = wi.files_in(ws_root, ws_root)
assert [f.path for f in files] == ["AGENTS.md", "AGENTS.local.md"], files
(ws_root / "CLAUDE.local.md").mkdir()                                  # 目录不算
(ws_root / "web").mkdir()
(ws_root / "web" / "AGENTS.md").write_text("web 规则：用 pnpm")
(ws_root / "web" / "app.py").write_text("print(1)")
(ws_root / "web" / "util.py").write_text("x = 1")
(ws_root / "web" / "deep").mkdir()
(ws_root / "web" / "deep" / "CLAUDE.md").write_text("deep 规则")
(ws_root / "web" / "deep" / "a.txt").write_text("a")
outside = Path(tmp) / "secret.txt"; outside.write_text("机密")
(ws_root / "evil").mkdir(); os.symlink(outside, ws_root / "evil" / "AGENTS.md")          # 越界链接 → 不读
(ws_root / "evil" / "x.txt").write_text("x")
(ws_root / ".spill").mkdir(exist_ok=True); (ws_root / ".spill" / "AGENTS.md").write_text("隐藏")
(ws_root / "huge").mkdir(); (ws_root / "huge" / "AGENTS.md").write_text("h" * (wi.MAX_SOURCE_BYTES + 1))
(ws_root / "lnk").mkdir(); os.symlink(ws_root / "web" / "AGENTS.md", ws_root / "lnk" / "AGENTS.md")  # 内部链接 → 读
assert [f.path for f in wi.files_in(ws_root, ws_root / "evil")] == []
assert [f.path for f in wi.files_in(ws_root, ws_root / ".spill")] == []
assert [f.path for f in wi.files_in(ws_root, ws_root / "huge")] == []
assert [f.content for f in wi.files_in(ws_root, ws_root / "lnk")] == ["web 规则：用 pnpm"]
assert [p.name for p in wi.descendant_dirs(ws_root, ws_root / "web" / "deep" / "a.txt")] == ["web", "deep"]
assert [p.name for p in wi.descendant_dirs(ws_root, ws_root / "web", is_dir=True)] == ["web"]
assert wi.descendant_dirs(ws_root, ws_root / "x.txt") == []
b = wi.baseline(PERSONAL)
assert "Instructions from: AGENTS.md\n\n根规则" in b.text and "本地：别动 vendor/" in b.text and "CLAUDE.md" not in b.text
print("ok: discovery")

# ---- 3. 子目录增量 ----
t = wi.Tracker()
n1 = t.note(PERSONAL, ws_root / "web" / "deep" / "a.txt")
assert "Additional instructions from: web/AGENTS.md" in n1 and "Additional instructions from: web/deep/CLAUDE.md" in n1
assert "These instructions apply to work under `web/deep`." in n1 and n1.index("web/AGENTS.md") < n1.index("web/deep/CLAUDE.md")
assert t.note(PERSONAL, ws_root / "web" / "app.py") == ""                     # 已说过
(ws_root / "web" / "AGENTS.md").write_text("web 规则：改用 npm")
n2 = t.note(PERSONAL, ws_root / "web" / "util.py")
assert "Updated instructions from: web/AGENTS.md" in n2 and "改用 npm" in n2 and "deep" not in n2
(ws_root / "web" / "deep" / "CLAUDE.md").unlink()
n3 = t.note(PERSONAL, ws_root / "web" / "deep" / "a.txt")
assert "Instructions removed: web/deep/CLAUDE.md" in n3
assert t.note(PERSONAL, ws_root / "web" / "deep" / "a.txt") == ""
assert t.note(PERSONAL, ws_root / "evil" / "x.txt") == ""                      # 越界链接
assert t.note(PERSONAL, ws_root / ".spill" / "AGENTS.md") == ""                # 隐藏目录
assert t.note(PERSONAL, ws_root / "x.txt") == ""                               # 根目录的在系统提示里
t2 = wi.Tracker()
assert t2.note(PERSONAL, ws_root / "web" / "AGENTS.md") == ""                  # 碰的就是规则文件本身
assert t2.told.get("web/AGENTS.md")
(ws_root / "web" / "deep" / "CLAUDE.md").write_text("deep 规则")
settings.workspace_instructions_bytes = 0
assert wi.Tracker().note(PERSONAL, ws_root / "web" / "app.py") == "" and wi.baseline(PERSONAL).text == ""
settings.workspace_instructions_bytes = 16384
assert wi.Tracker().note("nope" * 8, ws_root / "web" / "app.py") == ""          # 工作区不存在
print("ok: tracker")

# ---- 4. 真实一轮（模拟模型） ----
script: list = []
sent: list = []
def chunk(text=None, tools=None, u=None):
    if text is None and tools is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tools))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    sent.append(json.loads(json.dumps(messages, ensure_ascii=False)))
    step = script.pop(0) if script else "收尾"
    async def gen():
        if isinstance(step, list):
            yield chunk(tools=[NS(index=i, id=f"c{len(sent)}_{i}", function=NS(name=n, arguments=a))
                               for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=100, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()

async def seed(project_id=None, text="看看 web"):
    async with SessionLocal() as db:
        conv = Conversation(title="规则", project_id=project_id); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks(text)))
        await db.commit()
        return conv.id
async def turn(cid, text=None):
    async with SessionLocal() as db:
        if text:
            db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks(text))); await db.commit()
        return await run_turn(db, await db.get(Conversation, cid))
def tools_of(msgs): return [m for m in msgs if m["role"] == "tool"]
def rp(path): return json.dumps({"path": path})

script[:] = [[("read_file", rp("web/app.py"))], [("read_file", rp("web/util.py")), ("list_files", rp("web"))], "好了"]
cid = asyncio.run(seed())
reply = asyncio.run(turn(cid))
assert reply.status == "done", reply.status
system = sent[0][0]["content"]
assert sent[0][0]["role"] == "system" and "Instructions from: AGENTS.md" in system and "根规则" in system
assert "web 规则" not in system                                               # 子目录的不进基线
first = tools_of(sent[1])[0]["content"]
assert first.startswith("print(1)") and "Additional instructions from: web/AGENTS.md" in first and "改用 npm" in first
second = tools_of(sent[2])
assert len(second) == 3 and all("Additional instructions" not in m["content"] for m in second[1:]), second
# 下一轮：重新告知一次（每轮一个 Tracker）
script[:] = [[("read_file", rp("web/app.py"))], "嗯"]; sent.clear()
asyncio.run(turn(cid, "再看一次"))
assert "Additional instructions from: web/AGENTS.md" in tools_of(sent[1])[-1]["content"]
# 读子目录规则文件本身：不重复贴
script[:] = [[("read_file", rp("web/AGENTS.md"))], "嗯"]; sent.clear()
asyncio.run(turn(cid, "读规则"))
c = tools_of(sent[1])[-1]["content"]
assert c.startswith("web 规则：改用 npm") and "Additional instructions" not in c, c
# 写一个新子目录的规则后，同轮碰到那里的文件 → 告知
script[:] = [[("write_file", json.dumps({"path": "api/AGENTS.md", "content": "api 规则：只读"}))],
             [("write_file", json.dumps({"path": "api/main.py", "content": "pass"}))], "嗯"]; sent.clear()
asyncio.run(turn(cid, "写规则"))
assert "Additional instructions" not in tools_of(sent[1])[-1]["content"]      # 自己写的规则文件本身
assert "Additional instructions" not in tools_of(sent[2])[-1]["content"]      # 已记为告知过
# 项目工作区各管各的
async def mkproj():
    async with SessionLocal() as db:
        p = Project(name="规则项目"); db.add(p); await db.commit(); return p.id
pid = asyncio.run(mkproj())
proot = project_dir(pid).resolve()
(proot / "AGENTS.md").write_text("项目规则：中文注释")
async def prompts():
    async with SessionLocal() as db:
        return await build_system_prompt(db, pid, "x"), await build_system_prompt(db, None, "x")
ps, me = asyncio.run(prompts())
assert "项目规则：中文注释" in ps and "根规则" not in ps and "根规则" in me and "项目规则" not in me
# 子助手的系统提示也带根规则（同一个 build_system_prompt）
from app.agent import subagent
assert "build_system_prompt" in open(subagent.__file__).read()
print("ok: turns")

# ---- 5. REST ----
from fastapi.testclient import TestClient
from app.main import app
from app.auth import require_user
app.dependency_overrides[require_user] = lambda: "u"
H = {}
with TestClient(app) as cl:
    st = cl.get(f"/api/conversations/{cid}/context", headers=H).json()
    ins = st["instructions"]
    assert ins["budget"] == 16384 and ins["candidates"][0] == "AGENTS.md", ins
    assert [(f["path"], f["status"]) for f in ins["files"]] == [("AGENTS.md", "full"), ("AGENTS.local.md", "full")], ins
    assert ins["files"][0]["bytes"] == ins["files"][0]["used"] > 0
    settings.workspace_instructions_bytes = 200
    ins = cl.get(f"/api/conversations/{cid}/context", headers=H).json()["instructions"]
    assert [f["status"] for f in ins["files"]] == ["omitted", "truncated"], ins
    settings.workspace_instructions_bytes = 16384
    pcid = asyncio.run(seed(pid))
    ins = cl.get(f"/api/conversations/{pcid}/context", headers=H).json()["instructions"]
    assert [f["path"] for f in ins["files"]] == ["AGENTS.md"] and ins["files"][0]["bytes"] == B("项目规则：中文注释")
    for p in ("AGENTS.md", "AGENTS.local.md", "CLAUDE.md"):
        (ws_root / p).unlink()
    assert cl.get(f"/api/conversations/{cid}/context", headers=H).json()["instructions"]["files"] == []
print("ok: rest")
print("ALL OK")
