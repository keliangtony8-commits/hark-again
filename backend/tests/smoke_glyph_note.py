# 冒烟：v2.40 E2E B13 画图中文成方块（sandbox/image/matplotlibrc + workspace-env.sh + backend app/glyph_note.py）。无迁移。
# 1) glyph_note：新旧两种 matplotlib 警告都认、去重保序、超过 SHOW 个写“等 N 个字”、字体名、没警告 → 空；
# 2) workspace-env.sh：没有用户配置 → MATPLOTLIBRC=/etc/matplotlibrc 那份（这里用临时文件代替检查条件）；用户有自己的 / 已设 → 不动；
# 3) matplotlibrc 能被 matplotlib 解析（装了 matplotlib 才查）、CJK 字体在前、unicode_minus 关；
# 4) run_command 结果带 ⚠（一轮模拟模型，工具结果交回模型）；jobs.describe 读日志尾部带 ⚠，运行中不带。
# 运行：python tests/smoke_glyph_note.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
root = os.path.join(os.path.dirname(__file__), "..")
image = os.path.join(root, "..", "sandbox", "image")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from app import glyph_note
NEW = ("/w/plot.py:9: UserWarning: Glyph 21608 (\\N{CJK UNIFIED IDEOGRAPH-5468}) missing from font(s) DejaVu Sans.\n"
       "  plt.savefig('t.png')\n"
       "/w/plot.py:9: UserWarning: Glyph 19968 (\\N{CJK UNIFIED IDEOGRAPH-4E00}) missing from font(s) DejaVu Sans.\n"
       "/w/plot.py:9: UserWarning: Glyph 21608 (\\N{CJK UNIFIED IDEOGRAPH-5468}) missing from font(s) DejaVu Sans.\n")
OLD = "plot.py:3: RuntimeWarning: Glyph 27668 missing from current font.\n  font.set_text(s, 0.0, flags=flags)\n"
assert glyph_note.missing(NEW) == (["周", "一"], ["DejaVu Sans"]), glyph_note.missing(NEW)
assert glyph_note.missing(OLD) == (["气"], [])
assert glyph_note.missing("") == ([], []) and glyph_note.note("all good\n") == "" and glyph_note.note(None) == ""
n = glyph_note.note(NEW)
assert n.startswith("⚠ 画图时有字在字体里找不到（当时用的字体 DejaVu Sans）：周、一——") and n.endswith("\n"), n
assert "Noto Sans CJK JP" in n and "unicode_minus" in n and "XDG_CACHE_HOME" in n and "别把图发给用户" in n
many = "".join(f"Glyph {0x4e00 + i} missing from current font.\n" for i in range(9))
assert "等 9 个字" in glyph_note.note(many)
assert glyph_note.note_tail(b"x" * 200000 + NEW.encode()).startswith("⚠") and glyph_note.note_tail(NEW.encode() + b"y" * 70000) == ""

# 2) workspace-env.sh 的条件
env_sh = open(os.path.join(image, "workspace-env.sh")).read()
assert "/etc/matplotlibrc" in env_sh
def probe(extra_cmd="", preset=""):
    ws = tempfile.mkdtemp()
    script = f"{preset} WORKSPACE={ws}; {extra_cmd} . {os.path.join(image, 'workspace-env.sh')}; echo \"[$MATPLOTLIBRC]\""
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env={"PATH": os.environ["PATH"]}).stdout.strip(), ws
has_etc = os.path.isfile("/etc/matplotlibrc")
out, _ = probe()
assert out == ("[/etc/matplotlibrc]" if has_etc else "[]"), out
out, _ = probe(preset="export MATPLOTLIBRC=/mine;")
assert out == "[/mine]", out
out, _ = probe(extra_cmd='mkdir -p "$WORKSPACE/.home/.config/matplotlib"; touch "$WORKSPACE/.home/.config/matplotlib/matplotlibrc";')
assert out == "[]", out
assert "COPY matplotlibrc /etc/matplotlibrc" in open(os.path.join(image, "Dockerfile")).read()

# 3) matplotlibrc 本身
rc_path = os.path.join(image, "matplotlibrc")
rc = open(rc_path).read()
fams = next(l for l in rc.splitlines() if l.startswith("font.sans-serif:")).split(":", 1)[1]
assert fams.strip().startswith("Noto Sans CJK JP") and "DejaVu Sans" in fams and "axes.unicode_minus: False" in rc
try:
    import matplotlib
    p = matplotlib.rc_params_from_file(rc_path, use_default_template=False)
    assert p["font.sans-serif"][0] == "Noto Sans CJK JP" and p["axes.unicode_minus"] is False
    print("matplotlibrc parsed by matplotlib", matplotlib.__version__)
except ImportError:
    print("(matplotlib not installed: rc parse check skipped)")
from app import workspaces
assert "Noto Sans CJK" in workspaces.PREINSTALLED
assert "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc" in workspaces.PREINSTALLED  # v2.45 i2：Pillow 直接用这个路径

# 4) run_command / 后台任务
from app import jobs, llm, sandbox_client
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Job, Message, Project
load_builtin()
async def fake_stream(project_id, command, timeout=60, stdin=None, env=None, promote=None, **kw):
    yield {"type": "out", "data": NEW}
    yield {"type": "exit", "exit_code": 0, "timed_out": False, "output": NEW}
sandbox_client.stream = fake_stream

async def seed():
    async with SessionLocal() as db:
        p = Project(name="画图", emoji="📈"); db.add(p); await db.flush()
        conv = Conversation(title="t", project_id=p.id); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("把这周气温画成折线图")))
        await db.commit(); return p.id, conv.id
pid, cid = asyncio.run(seed())
seen, script = [], []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append([dict(m) for m in messages])
    step = script.pop(0)
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"c{len(script)}-{i}", function=NS(name=n, arguments=json.dumps(a)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
script.extend([[("run_command", {"command": "python plot.py"})], "图里中文缺字，我换字体重画。"])
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))
reply = asyncio.run(turn())
tool_msg = next(m for m in seen[1] if m["role"] == "tool")
assert "⚠ 画图时有字在字体里找不到" in tool_msg["content"] and "周、一" in tool_msg["content"], tool_msg["content"]
assert reply.steps[0]["tool"] == "run_command"

async def jobcase():
    async with SessionLocal() as db:
        j = Job(id="jg1", project_id=pid, conversation_id=cid, command="python plot.py", title="画图", state="running", timeout=600)
        db.add(j); await db.commit()
        d = jobs.job_dir(j); d.mkdir(parents=True, exist_ok=True)
        assert "⚠ 画图" not in jobs.describe(j)  # 还没日志
        (d / "log").write_text("start\n" + OLD)
        assert "⚠ 画图" not in jobs.describe(j)  # 运行中不说
        j.state = "done"; j.exit_code = 0
        text = jobs.describe(j)
        assert "。\n⚠ 画图时有字在字体里找不到：气" in text, text
asyncio.run(jobcase())
print("smoke_glyph_note OK")
