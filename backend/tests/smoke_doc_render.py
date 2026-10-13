# 冒烟：v2.22 CORE 34 排版成 PDF / 长图——app/doc_render.py 唯一规则 + render_document 工具（浏览器一侧换成假的；
# 真 Chromium 的测试在 browser/test_render_chromium.py）。
# 1) output_for：默认换后缀、后缀定格式、冲突 / 不支持的后缀 / 工作区外 / 隐藏目录 / 目录拒绝；
# 2) 源文件：不存在 / 隐藏 / 二进制 / 根目录拒绝；Markdown → 表格 + 删除线 + 标题当 title；纯文本进 <pre> 且转义；
# 3) 内嵌资源：相对 / ../ / /workspace/ 图片 → data:，样式表 → <style>；找不到 / 越界 / 隐藏 / 不是图片 / 太大记 notes；网络地址不动；
# 4) render：交给浏览器的是内嵌好的整页、页数从 PDF 数出来、网络资源个数和长图截断进 notes、覆盖标记、
#    配额满不留文件、记进整轮改动（撤销删掉）、浏览器连不上给原因；
# 5) 一轮（模拟模型）：按名调用按需加载的 render_document → 文件卡进回复、时间线 detail “路径 · N 页”、show=false 不给卡。
# 运行：python tests/smoke_doc_render.py
import os, sys, asyncio, subprocess, tempfile, json, io, base64
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from pypdf import PdfWriter
from app import browser_client, doc_render as D, quota, turn_changes, workspaces
from app.agent.runner import run_turn
from app.agent.tools import REGISTRY, load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message
from app.storage import project_dir

WS = workspaces.PERSONAL
R = project_dir(WS)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (10).to_bytes(4, "big") + (20).to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"

def run(c): return asyncio.run(c)
def err(fn, *a, has=""):
    try:
        fn(*a)
    except D.RenderError as e:
        assert has in str(e), (str(e), has)
        return str(e)
    raise AssertionError(f"应该拒绝 {a}")

# ---- 1. output_for ----
O = lambda out, fmt=None, src="docs/报告.md": (lambda p, f: (p.relative_to(R).as_posix(), f))(*D.output_for(R, src, out, fmt))
assert O("") == ("docs/报告.pdf", "pdf") and O("", "png") == ("docs/报告.png", "png")
assert O("out/a.PNG") == ("out/a.PNG", "png") and O("out/a") == ("out/a.pdf", "pdf") and O("out/a", "png") == ("out/a.png", "png")
err(O, "a.png", "pdf", has="二选一")
err(O, "a.docx", has="只能输出")
err(O, "", "jpg", has="format")
err(O, "../x.pdf", has="工作区外")
err(O, ".jobs/x.pdf", has="隐藏")
(R / "box").mkdir()
assert O("box", "pdf")[0] == "box.pdf"
(R / "dir.pdf").mkdir()
err(O, "dir.pdf", has="目录")

# ---- 2. 源文件 + Markdown ----
(R / "docs").mkdir()
(R / "docs/img").mkdir()
(R / ".spill").mkdir(exist_ok=True)
(R / ".spill/a.md").write_text("# x")
(R / "bin.dat").write_bytes(bytes(range(256)) * 10)
err(D._source, R, "nope.md", has="没有")
err(D._source, R, ".spill/a.md", has="隐藏")
err(D._source, R, "bin.dat", has="不是文本")
err(D._source, R, "", has="源文件")
err(D._source, R, "../../etc/passwd", has="工作区外")
h = D.markdown_html("| a | b |\n|---|---|\n| 1 | ~~2~~ |\n\n<span class=x>raw</span>")
assert "<table>" in h and "<s>2</s>" in h and "<span class=x>raw</span>" in h, h
assert D.title_of("前言\n\n# 期末报告 #\n## 二", "f") == "期末报告" and D.title_of("无标题", "f") == "f"
(R / "notes.txt").write_text("a < b & c")
t = D.to_html(R / "notes.txt")
assert "<pre>a &lt; b &amp; c</pre>" in t and "Noto Sans CJK SC" in t

# ---- 3. 内嵌资源 ----
(R / "docs/img/chart.png").write_bytes(PNG)
(R / "logo.png").write_bytes(PNG)
(R / "docs/style.css").write_text("h1{color:red}</style>")
(R / "docs/fake.png.txt").write_text("x")
(R / ".home").mkdir(exist_ok=True)
(R / ".home/s.png").write_bytes(PNG)
big = R / "docs/big.png"
big.write_bytes(b"\x89PNG" + b"0" * (D.ASSET_MAX + 1))
doc = ('<link rel="stylesheet" href="style.css"><link rel="icon" href="x.ico">'
       '<img src="img/chart.png"><img alt=a src=\'../logo.png\'><img src="/workspace/logo.png">'
       '<img src="missing.png"><img src="../../outside.png"><img src="../.home/s.png"><img src="fake.png.txt">'
       '<img src="big.png"><img src="https://example.com/a.png"><img src="data:image/png;base64,AAA">')
out, notes = D.inline_assets(doc, R, R / "docs")
assert out.count("data:image/png;base64,") == 4, out[:400]  # 3 内嵌 + 原有 data:
assert "<style>h1{color:red}<\\/style></style>" in out and 'rel="icon"' in out
assert 'src="https://example.com/a.png"' in out
joined = "；".join(notes)
for want in ("找不到 missing.png", "../../outside.png 在工作区外面", "../.home/s.png 在隐藏目录里", "fake.png.txt 不是图片", "big.png 超过"):
    assert want in joined, (want, joined)
big.unlink()

# ---- 4. render ----
def pdf(n):
    w = PdfWriter()
    for _ in range(n):
        w.add_blank_page(width=595, height=842)
    b = io.BytesIO(); w.write(b); return b.getvalue()
calls = []
answer = {"data": pdf(3), "blocked": 0, "cut": False, "fail": None}
async def fake_render(html, **kw):
    calls.append((html, kw))
    if answer["fail"]:
        raise RuntimeError(answer["fail"])
    return answer["data"], answer["blocked"], answer["cut"]
browser_client.render = fake_render
(R / "docs/报告.md").write_text("# 期末报告\n\n![图](img/chart.png)\n\n![远程](https://e.com/x.png)\n\n| 项 | 值 |\n|---|---|\n| 甲 | 1 |\n")
tr = turn_changes.Tracker()
answer["blocked"] = 1
x = run(D.render(WS, "docs/报告.md", tracker=tr))
assert x.rel == "docs/报告.pdf" and x.pages == 3 and not x.overwrote and x.fmt == "pdf", x
assert (R / x.rel).read_bytes() == answer["data"] and not list((R / "docs").glob(".*.part"))
html, kw = calls[-1]
assert "<title>期末报告</title>" in html and "data:image/png;base64," in html and "<table>" in html
assert kw == {"fmt": "pdf", "paper": "A4", "landscape": False, "width": D.WIDTH_DEFAULT, "page_numbers": True}, kw
assert any("1 个网络资源没加载" in n for n in x.notes)
m = D.for_model(x, True)
assert "3 页 PDF" in m and "docs/报告.pdf" in m and "文件卡已经给用户了" in m and "网络资源" in m, m
assert D.detail(x) == "docs/报告.pdf · 3 页"
# 长图：宽度夹在范围里、截断进 notes、覆盖标记
answer.update(data=PNG, blocked=0, cut=True)
y = run(D.render(WS, "docs/报告.md", "poster.png", width=99999, landscape=True, paper="Letter", tracker=tr))
assert y.fmt == "png" and y.pages is None and calls[-1][1]["width"] == D.WIDTH_MAX and calls[-1][1]["paper"] == "Letter"
assert any("16384" in n for n in y.notes) and "read_file" in D.for_model(y, False) and "display_file" in D.for_model(y, False)
z = run(D.render(WS, "docs/报告.md", "poster.png", width=10))
assert z.overwrote and calls[-1][1]["width"] == D.WIDTH_MIN and "覆盖了原文件" in D.for_model(z, True)
err(lambda: run(D.render(WS, "docs/报告.md", paper="B5")), has="纸张")
err(lambda: run(D.render(WS, "notes.txt", "notes.txt")), has="只能输出")
(R / "same.html").write_text("<p>x</p>")
# 浏览器连不上
answer["fail"] = "云浏览器没连上，排不了版：boom"
err(lambda: run(D.render(WS, "same.html")), has="云浏览器没连上")
assert not (R / "same.pdf").exists()
answer["fail"] = None
# 配额满：不留文件
real = quota.check
def full(ws, adding=0): raise quota.QuotaError("工作区满了")
quota.check = full
answer["data"] = pdf(1)
err(lambda: run(D.render(WS, "same.html")), has="没有存")
quota.check = real
assert not (R / "same.pdf").exists()
# 整轮撤销：新建的 PDF / PNG 被删
card = turn_changes.finish(tr, WS)
assert card and {f["path"] for f in card["files"]} >= {"docs/报告.pdf", "poster.png"}, card
turn_changes.undo(WS, card["token"])
assert not (R / "docs/报告.pdf").exists() and not (R / "poster.png").exists()

# ---- 5. 一轮（模拟模型）----
from app import llm
load_builtin()
assert REGISTRY["render_document"].deferred
seen, script = [], []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append(([dict(m) for m in messages], [t["function"]["name"] for t in tools or []]))
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
async def seed():
    async with SessionLocal() as db:
        conv = Conversation(title="排版"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("把报告排成 PDF 给我")))
        await db.commit()
        return conv.id
cid = run(seed())
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))
answer.update(data=pdf(2), blocked=0, cut=False)
script.extend([[("render_document", {"path": "docs/报告.md"})], "排好了，2 页。"])
reply = run(turn())
assert "render_document" not in seen[0][1] and "deferred_tool" in seen[0][1]
tool_msg = next(m for m in seen[1][0] if m["role"] == "tool")
assert "已排成2 页 PDF：docs/报告.pdf" in tool_msg["content"], tool_msg
assert [(s["tool"], s["state"], s.get("detail")) for s in reply.steps] == [("render_document", "done", "docs/报告.pdf · 2 页")], reply.steps
files = [b for b in reply.blocks if b.get("type") == "file"]
assert len(files) == 1 and files[0]["name"] == "报告.pdf" and files[0]["mime"] == "application/pdf", reply.blocks
# show=false：只生成不交付；失败一步记 failed
script.extend([[("render_document", {"path": "docs/报告.md", "output": "a.png", "show": False}), ], "好了。"])
answer["data"] = PNG
reply2 = run(turn())
assert not [b for b in reply2.blocks if b.get("type") == "file"] and (R / "a.png").read_bytes() == PNG
script.extend([[("render_document", {"path": "nope.md"})], "没有这个文件。"])
reply3 = run(turn())
assert reply3.steps[0]["state"] == "error", reply3.steps
print("smoke_doc_render ok")
