# 冒烟：v2.76 CORE 压缩包不解压就看——app/archives.py 唯一规则 + read_file(member)。
# 1) 规则：zip/tar.gz/gz 列目录（大小带单位、最大的、文件夹数、加密）、GBK 名字、找成员（精确/大小写/唯一同名/文件夹）、
#    炸弹上限、加密不读、文字 UTF-8/GBK/二进制；
# 2) 工具：工作区 + 附件，member 读文字 / docx / 图片 / 套娃包；非压缩包给 member 报错；7z 提示；工作区不多一个文件；
# 3) 附件提示带“不用解压”；4) 一轮（模拟模型）：列目录 → 读成员 → 回答，工作区不变。
# 运行：python tests/smoke_archives.py
import os, sys, asyncio, subprocess, tempfile, json, io, zipfile, tarfile, gzip
from pathlib import Path
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import archives as AR, attachment_save, storage, workspaces
from app.agent.runner import run_turn
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message
from app.storage import project_dir

WS = workspaces.PERSONAL
r0 = project_dir(WS)
r0.mkdir(parents=True, exist_ok=True)

def docx(text):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   f'<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
    return b.getvalue()

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 60
inner = io.BytesIO()
with tarfile.open(fileobj=inner, mode="w:gz") as t:
    data = "套娃里的字".encode()
    ti = tarfile.TarInfo("deep/内层.txt"); ti.size = len(data); t.addfile(ti, io.BytesIO(data))
with zipfile.ZipFile(r0 / "资料.zip", "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("资料/答案.bin", os.urandom(78643))  # 76.8 KB
    z.writestr("资料/说明.txt", "考试在 3 号楼 201，带身份证。\n")
    z.writestr("资料/纪要.docx", docx("周五前交报告"))
    z.writestr("资料/照片/a.png", PNG)
    z.writestr("资料/inner.tar.gz", inner.getvalue())
    z.writestr("README.TXT", "hello\n")
# GBK 名字（没标 UTF-8）的 zip：Windows 中文系统打出来的那种——用 cp437 名字写入，读回来按 GBK
g = io.BytesIO()
with zipfile.ZipFile(g, "w") as z:
    z.writestr("QQQQQQ.txt", "张三 90".encode("gbk"))  # 同字节长的 ASCII 占位，再换成 GBK 字节（不带 UTF-8 标记）
(r0 / "gbk.zip").write_bytes(g.getvalue().replace(b"QQQQQQ.txt", "成绩单.txt".encode("gbk")))
(r0 / "log.csv.gz").write_bytes(gzip.compress("日期,金额\n10-01,30\n".encode()))
(r0 / "a.7z").write_bytes(b"7z\xbc\xaf\x27\x1c" + b"\0" * 30)
(r0 / "note.txt").write_text("普通文件")
(r0 / "bad.zip").write_bytes(b"PK\x03\x04 broken")

# ---- 1. 规则 ----
assert AR.kind_of("a.tar.gz") == "tar" and AR.kind_of("A.TGZ") == "tar" and AR.kind_of("x.gz") == "gz"
assert AR.kind_of("x.zip") == "zip" and AR.kind_of("x.docx") is None and AR.is_other("a.RAR")
lst = AR.entries(r0 / "资料.zip", "资料.zip")
text = AR.render("资料.zip", lst)
assert "6 个文件、2 个文件夹" in text and "最大的：资料/答案.bin（76.8 KB）" in text, text[:300]
assert "资料/照片/" in text and "member=" in text and " B  " in text  # 每行有单位
assert AR.render("资料.zip", lst, "资料/照片").startswith("资料.zip里的“资料/照片/”：压缩包，1 个文件")
assert AR.find(lst, "资料/说明.txt").name == "资料/说明.txt"
assert AR.find(lst, "./资料/说明.txt").name == "资料/说明.txt"
assert AR.find(lst, "readme.txt").name == "README.TXT"
assert AR.find(lst, "说明.txt").name == "资料/说明.txt"  # 唯一同名
assert AR.find(lst, "资料/照片/") == "资料/照片"
try:
    AR.find(lst, "答案.doc"); raise SystemExit("应找不到")
except AR.ArchiveError as e:
    assert "没有“答案.doc”" in str(e) and "资料/答案.bin" in str(e), e
gl = AR.entries(r0 / "gbk.zip", "gbk.zip")
assert gl.entries[0].name == "成绩单.txt", gl.entries
assert AR.decode_text(AR.read_member(r0 / "gbk.zip", "gbk.zip", gl, gl.entries[0])) == ("张三 90", "按 GBK 解码")
assert AR.decode_text(b"\0\1\2") is None and AR.decode_text("abc".encode()) == ("abc", "")
assert AR.decode_text(b"\xff\xfe\xfa") is None
gz = AR.entries(r0 / "log.csv.gz", "log.csv.gz")
assert gz.entries[0].name == "log.csv" and gz.entries[0].size == len("日期,金额\n10-01,30\n".encode())
# 炸弹：声明小、实际大 → 卡住
old = AR.MEMBER_MAX
AR.MEMBER_MAX = 1000
try:
    big = AR.Entry("资料/答案.bin", 10, ref=next(e.ref for e in lst.entries if e.name == "资料/答案.bin"))
    try:
        AR.read_member(r0 / "资料.zip", "资料.zip", lst, big); raise SystemExit("应超限")
    except AR.ArchiveError as e:
        assert "超过" in str(e)
    try:
        AR.read_member(r0 / "资料.zip", "资料.zip", lst, AR.Entry("x", 5000)); raise SystemExit("应超限")
    except AR.ArchiveError as e:
        assert "不在内存里读" in str(e)
finally:
    AR.MEMBER_MAX = old
try:
    AR.read_member(r0 / "资料.zip", "资料.zip", lst, AR.Entry("s.txt", 3, encrypted=True)); raise SystemExit
except AR.ArchiveError as e:
    assert "密码" in str(e)
try:
    AR.entries(r0 / "bad.zip", "bad.zip"); raise SystemExit
except AR.ArchiveError as e:
    assert "打不开" in str(e)
# 加密标记的 zip 条目列出来带 [有密码]
enc = io.BytesIO()
with zipfile.ZipFile(enc, "w") as z:
    z.writestr("秘密.txt", b"xx"); z.getinfo("秘密.txt").flag_bits |= 0x1  # 中央目录在 close 时写：标成加密
    z.writestr("公开.txt", "ok")
el = AR.entries(enc.getvalue(), "e.zip")
assert "1 个文件加了密码" in AR.render("e.zip", el) and "[有密码]" in AR.render("e.zip", el)

# ---- 2. 工具 ----
load_builtin()
t = REGISTRY["read_file"]
ctx = ToolContext(db=None, conversation_id="c-a")
before = sorted(p.relative_to(r0).as_posix() for p in r0.rglob("*"))
run = lambda **kw: asyncio.run(t.run(ctx, **kw))
res = run(path="资料.zip")
assert "最大的：资料/答案.bin（76.8 KB）" in res.content and res.detail == "6 个文件", (res.detail, res.content[:200])
res = run(path="资料.zip", member="说明.txt")
assert "3 号楼 201" in res.content and not res.failed and res.detail == "资料/说明.txt", res.content
res = run(path="资料.zip", member="资料/纪要.docx")
assert "周五前交报告" in res.content and "Word" in res.content, res.content
res = run(path="资料.zip", member="资料/照片/a.png")
assert res.images and res.images[0].name == "a.png", res.content
res = run(path="资料.zip", member="资料/inner.tar.gz")
assert "deep/内层.txt" in res.content and "1 个文件" in res.content, res.content
res = run(path="资料.zip", member="资料/答案.bin")
assert "不是文本文件" in res.content and "76.8 KB" in res.content, res.content
res = run(path="资料.zip", member="nope.txt")
assert res.failed == "读不了" and "没有“nope.txt”" in res.content
res = run(path="gbk.zip", member="成绩单.txt")
assert "张三 90" in res.content and "GBK" in res.content, res.content
res = run(path="log.csv.gz")
assert "log.csv" in res.content
res = run(path="log.csv.gz", member="log.csv")
assert "10-01,30" in res.content
res = run(path="note.txt", member="x")
assert res.failed == "参数不对" and "不是压缩包" in res.content
assert run(path="note.txt").content.endswith("普通文件")
res = run(path="a.7z")
assert "7z" in res.content and "run_command" in res.content
res = run(path="bad.zip")
assert res.failed == "读不了" and "打不开" in res.content
assert sorted(p.relative_to(r0).as_posix() for p in r0.rglob("*")) == before  # 工作区一个文件都没多
from app import read_many
assert "是压缩包" in read_many.read(WS, ["资料.zip"]).text
# 解压提醒
assert AR.extract_note("tar -xzf 下载/a.tar.gz && grep -R ERROR logs", ["logs/a.log", "logs/b.log"]).startswith("（这次解压在工作区新建了 2 个文件：logs/。")
assert AR.extract_note("unzip -o x.zip", ["说明.txt"]) and AR.extract_note("cd d && unzip x.zip -d out", ["d/out/a"])
assert AR.extract_note("unzip -l x.zip", ["a"]) == "" and AR.extract_note("tar -tzf a.tgz", ["a"]) == ""
assert AR.extract_note("tar -xzf a.tgz", []) == "" and AR.extract_note("python a.py", ["a"]) == ""
assert "f0、f1、f2、f3、f4 等 7 项" in AR.extract_note("7z x a.7z", [f"f{i}" for i in range(7)])
# GBK 短名字也是合法 UTF-8（通知 → ֪ͨ）：选全是中文的那个
g2 = io.BytesIO()
with zipfile.ZipFile(g2, "w") as z:
    z.writestr("QQQQ.txt", "x")
gl2 = AR.entries(g2.getvalue().replace(b"QQQQ.txt", "通知.txt".encode("gbk")), "n.zip")
assert gl2.entries[0].name == "通知.txt", gl2.entries
# 附件
d = storage.UPLOADS / "up1"; d.mkdir(parents=True, exist_ok=True)
(d / "作业.zip").write_bytes((r0 / "资料.zip").read_bytes())
res = run(attachment="up1")
assert res.content.startswith("附件 作业.zip：压缩包，6 个文件"), res.content[:80]
res = run(attachment="up1", member="说明.txt")
assert "3 号楼" in res.content and "附件 作业.zip 里的 资料/说明.txt" in res.content, res.content
h = attachment_save.hint([{"type": "file", "source": "upload", "id": "up1", "name": "作业.zip"}])
assert "member" in h and "不用存也不用解压" in h, h
h = attachment_save.hint([{"type": "file", "source": "upload", "id": "up2", "name": "a.pdf"}])
assert "member" not in h

# ---- 4. 一轮（模拟模型）----
from app import llm
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
            yield chunk(tool=[NS(index=i, id=f"c{len(script)}-{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
async def seed():
    async with SessionLocal() as db:
        conv = Conversation(title="包"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("资料.zip 里有什么？考试在哪")))
        await db.commit()
        return conv.id
cid = asyncio.run(seed())
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))
script.extend([[("read_file", {"path": "资料.zip"})], [("read_file", {"path": "资料.zip", "member": "资料/说明.txt"})],
               "6 个文件，最大的是答案.bin（76.8 KB）。考试在 3 号楼 201。"])
reply = asyncio.run(turn())
tools = [m for m in seen[2] if m["role"] == "tool"]
assert "最大的" in tools[0]["content"] and "3 号楼 201" in tools[1]["content"], tools
assert [(x["tool"], x["state"]) for x in reply.steps] == [("read_file", "done"), ("read_file", "done")], reply.steps
assert sorted(p.relative_to(r0).as_posix() for p in r0.rglob("*")) == before
print("smoke_archives ok")
