# 冒烟：v2.08 CORE 27 读文档——app/documents.py 唯一规则（PDF / docx / xlsx / pptx → 带页标记的文字、pages 选页）。
# 1) 规则：页码解析（1-5,9 / 10- / 越界 / 写错 / 上限 50）、spans、PDF 有字页 + 空白页提示 pdftoppm、docx 标题 / 表格、
#    xlsx 共享字符串 / 行内字符串 / 空列对齐 / 多表选表、pptx 按幻灯片顺序、坏文件 / 老格式 / 压缩炸弹拒绝；
# 2) read_file：工作区 PDF 第一批 + 下一批提示、pages 选页、offset 分页、docx；attachment 读附件全文；path / attachment 二选一；
# 3) 聊天附件：PDF / Word 开头进历史（带编号和“用 read_file attachment 读”），缓存只抽一次；长文本附件也给读全文提示；
# 4) web_page PDF、extract_data 读 xlsx 都走同一套；一轮（模拟模型）：read_file attachment + pages。
# 运行：python tests/smoke_documents.py
import os, sys, asyncio, subprocess, tempfile, json, io, zipfile
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import documents as D, llm, storage, web_page, workspaces
from app.agent import context
from app.agent.runner import run_turn
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.agent.builtin import extract as extract_tool
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message
from app.storage import project_dir


# ---- 夹具：手写最小 PDF（Helvetica 文字页 + 空白页）、docx / xlsx / pptx（zip + xml）----
def make_pdf(pages: list[str]) -> bytes:
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for t in pages:
        stream = f"BT /F1 12 Tf 20 100 Td ({t}) Tj ET" if t else ""
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Resources << /Font << /F1 3 0 R >> >> "
                    f"/Contents {len(objs)} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out)); out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offs).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return bytes(out)


def make_zip(files: dict[str, str]) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for n, c in files.items():
            z.writestr(n, c)
    return b.getvalue()


WNS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
DOCX = make_zip({"word/document.xml": f'<w:document {WNS}><w:body>'
    '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>季度报告</w:t></w:r></w:p>'
    '<w:p><w:r><w:t xml:space="preserve">收入 </w:t></w:r><w:r><w:t>增长</w:t></w:r></w:p>'
    '<w:p/>'
    '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>月份</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>金额</w:t></w:r></w:p></w:tc></w:tr>'
    '<w:tr><w:tc><w:p><w:r><w:t>一月</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>1|200</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
    '</w:body></w:document>'})
SNS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' \
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
RNS = 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'
XLSX = make_zip({
    "xl/workbook.xml": f'<workbook {SNS}><sheets><sheet name="价格" sheetId="1" r:id="rId1"/>'
                       '<sheet name="空表" sheetId="2" r:id="rId2"/><sheet name="备注" sheetId="3" r:id="rId3"/></sheets></workbook>',
    "xl/_rels/workbook.xml.rels": f'<Relationships {RNS}><Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
                                  '<Relationship Id="rId2" Target="worksheets/sheet2.xml"/>'
                                  '<Relationship Id="rId3" Target="/xl/worksheets/sheet3.xml"/></Relationships>',
    "xl/sharedStrings.xml": f'<sst {SNS}><si><t>名称</t></si><si><t>价格</t></si><si><r><t>牛</t></r><r><t>奶</t></r></si></sst>',
    "xl/worksheets/sheet1.xml": f'<worksheet {SNS}><sheetData>'
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
        '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="C2"><v>12.5</v></c></row></sheetData></worksheet>',
    "xl/worksheets/sheet2.xml": f'<worksheet {SNS}><sheetData/></worksheet>',
    "xl/worksheets/sheet3.xml": f'<worksheet {SNS}><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>现货</t></is></c></row></sheetData></worksheet>',
})
PNS = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" ' \
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" ' \
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
def slide(t): return f'<p:sld {PNS}><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{t}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>'
PPTX = make_zip({
    "ppt/presentation.xml": f'<p:presentation {PNS}><p:sldIdLst><p:sldId id="256" r:id="rId9"/><p:sldId id="257" r:id="rId8"/></p:sldIdLst></p:presentation>',
    "ppt/_rels/presentation.xml.rels": f'<Relationships {RNS}><Relationship Id="rId8" Target="slides/slide1.xml"/>'
                                       '<Relationship Id="rId9" Target="slides/slide2.xml"/></Relationships>',
    "ppt/slides/slide1.xml": slide("结尾页"), "ppt/slides/slide2.xml": slide("开场页"),
})

# ---- 1. 规则 ----
assert D.parse_pages("", 120) == list(range(1, 51)) and D.parse_pages(None, 3) == [1, 2, 3]
assert D.parse_pages("1-3,9，2", 10) == [1, 2, 3, 9] and D.parse_pages("8-", 10) == [8, 9, 10]
assert D.parse_pages("5-500", 10) == list(range(5, 11)) and len(D.parse_pages("1-1000", 2000)) == 50
for bad, word in (("abc", "看不懂"), ("0-3", "从 1 开始"), ("5-2", "前小后大"), ("30", "只有 10 页")):
    try: D.parse_pages(bad, 10); raise AssertionError(bad)
    except D.DocError as e: assert word in str(e), (bad, e)
assert D.spans([1, 2, 3, 7, 9, 10]) == "1–3、7、9–10"
assert D.kind_of("a.PDF") == "pdf" and D.kind_of("x", b"%PDF-1.4") == "pdf" and D.kind_of("a.txt") is None
assert D.kind_of("b.xlsm") == "xlsx" and D.is_old("c.doc")

PDF = make_pdf([f"Page{i} hello" if i not in (3, 4) else "" for i in range(1, 61)])
d = D.read(PDF, "r.pdf")
assert d.total == 60 and d.shown == list(range(1, 51)) and d.blank == [3, 4], (d.total, d.blank)
assert d.text.startswith("--- 第 1 页 ---\nPage1 hello") and "--- 第 3 页 ---" not in d.text and "Page51" not in d.text
h = d.header("r.pdf")
assert "共 60 页" in h and "这次是第 1–50 页" in h and "第 3–4 页没有可提取的文字" in h and "pdftoppm -f 3 -l 3" in h, h
assert 'pages="51-60"' in h, h
d2 = D.read(PDF, "r.pdf", "55,3")
assert d2.shown == [3, 55] and d2.blank == [3] and "Page55" in d2.text and "下一批" in d2.header("r.pdf")
assert "后面还有" not in D.read(PDF, "r.pdf", "51-60").header("x")
scan = D.read(make_pdf(["", ""]), "s.pdf")
assert scan.text == "" and "没有可提取的文字" in scan.header("s.pdf") and "pdftoppm" in scan.header("s.pdf")

w = D.read(DOCX, "q.docx")
assert w.text == "# 季度报告\n收入 增长\n| 月份 | 金额 |\n| 一月 | 1\\|200 |", w.text
assert w.header("q.docx") == "q.docx：Word 文档。", w.header("q.docx")
x = D.read(XLSX, "p.xlsx")
assert x.total == 3 and x.blank == [2], x
assert "--- 表 1：价格 ---\n| 名称 | 价格 |\n| 牛奶 |  | 12.5 |" in x.text and "--- 表 3：备注 ---\n| 现货 |" in x.text, x.text
assert "共 3 张表" in x.header("p.xlsx") and "第 2 张表没有可提取的文字" in x.header("p.xlsx")
assert D.read(XLSX, "p.xlsx", "3").text == "--- 表 3：备注 ---\n| 现货 |"
D.SHEET_ROWS, old = 1, D.SHEET_ROWS
assert "还有 1 行没读" in D.read(XLSX, "p.xlsx", "1").text
D.SHEET_ROWS = old
pp = D.read(PPTX, "s.pptx")
assert pp.text == "--- 第 1 张 ---\n开场页\n\n--- 第 2 张 ---\n结尾页", pp.text  # 按 sldIdLst 顺序，不按文件名
assert "共 2 张幻灯片" in pp.header("s.pptx")
for body, name, word in ((b"garbage", "a.docx", "打不开"), (b"%PDF-1.4 broken", "b.pdf", "打不开"),
                         (b"x", "c.doc", "老格式"), (b"x", "d.bin", "不是 PDF")):
    try: D.read(body, name); raise AssertionError(name)
    except D.DocError as e: assert word in str(e), (name, e)
D.ZIP_XML_MAX, old = 100, D.ZIP_XML_MAX
try: D.read(DOCX, "big.docx"); raise AssertionError
except D.DocError as e: assert "太大" in str(e)
D.ZIP_XML_MAX = old

# ---- 2. read_file ----
load_builtin()
ws = project_dir(workspaces.PERSONAL)
(ws / "docs").mkdir(parents=True, exist_ok=True)
(ws / "docs/r.pdf").write_bytes(PDF)
(ws / "docs/q.docx").write_bytes(DOCX)
(ws / "docs/old.doc").write_bytes(b"\xd0\xcf\x11\xe0junk")
ctx = ToolContext(db=None)
RF = REGISTRY["read_file"].run
def call(**kw): return asyncio.run(RF(ctx, **kw))
a = call(path="docs/r.pdf")
assert a.content.startswith("docs/r.pdf：PDF，共 60 页，这次是第 1–50 页。") and "--- 第 50 页 ---" in a.content, a.content[:200]
b = call(path="docs/r.pdf", pages="51-52")
assert "Page51" in b.content and "Page50" not in b.content and "这次是第 51–52 页" in b.content
c = call(path="docs/r.pdf", limit=200)
assert "下一段用 offset=" in c.content and len(c.content) < 800, c.content
assert "# 季度报告" in call(path="docs/q.docx").content
assert "老格式" in call(path="docs/old.doc").content
bad = call(path="docs/r.pdf", pages="abc")
assert bad.failed and "看不懂" in bad.content
two = call(path="docs/r.pdf", attachment="x")
assert two.failed and "给一个" in two.content and call().failed

up_pdf = storage.save_upload("合同.pdf", PDF)
up_txt = storage.save_upload("长日志.txt", ("行\n" * 5000).encode())
up_doc = storage.save_upload("报告.docx", DOCX)
att = call(attachment=up_pdf["id"], pages="58-60")
assert att.content.startswith("附件 合同.pdf：PDF，共 60 页，这次是第 58–60 页。") and "Page60" in att.content, att.content
assert "行" in call(attachment=up_txt["id"], offset=9000).content
assert call(attachment="nope").failed and call(attachment="../../etc").failed

# ---- 3. 聊天附件进历史 ----
def fb(u): return {"type": "file", "source": "upload", "id": u["id"], "name": u["name"], "mime": u["mime"], "size": u["size"]}
calls = []
real = D.read
def counting(*a, **k):
    calls.append(a[1]); return real(*a, **k)
D.read = counting
t1 = context._render([{"type": "text", "text": "看看"}, fb(up_pdf), fb(up_doc), fb(up_txt)])
t2 = context._render([{"type": "text", "text": "看看"}, fb(up_pdf), fb(up_doc), fb(up_txt)])
D.read = real
assert t1 == t2 and calls == ["合同.pdf", "报告.docx"], calls  # 缓存：每个附件只抽一次，历史逐字不变
assert "[附件 合同.pdf] PDF，共 60 页，这次是第 1–50 页。" in t1 and "Page1 hello" in t1, t1[:400]
assert f'read_file attachment="{up_pdf["id"]}"' in t1 and "[附件 报告.docx] Word 文档。\n# 季度报告" in t1
assert f'read_file attachment="{up_txt["id"]}"' in t1  # 长文本附件以前只截断不提示
assert f'attachment="{up_doc["id"]}"' not in t1  # 短文档全给了，不用提示

# ---- 4. 同一套：web_page PDF、extract 读 xlsx ----
wp = web_page._pdf(PDF)
assert wp.startswith("--- 第 1 页 ---") and "共 60 页，只抽了前 50 页" in wp and "第 3–4 页没有可提取的文字" in wp, wp[-300:]
assert "扫描件" in web_page._pdf(make_pdf([""]))
(ws / "p.xlsx").write_bytes(XLSX)
text, label = extract_tool._file_text(ctx, "p.xlsx")
assert label == "Excel 表格" and "| 牛奶 |  | 12.5 |" in text

# ---- 5. 一轮（模拟模型）：读附件后面的页 ----
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
async def seed():
    async with SessionLocal() as db:
        conv = Conversation(title="合同"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("合同最后几页说了什么") + [fb(up_pdf)]))
        await db.commit()
        return conv.id
cid = asyncio.run(seed())
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))
script.extend([[("read_file", {"attachment": up_pdf["id"], "pages": "59-60"})], "最后两页是 Page59、Page60。"])
reply = asyncio.run(turn())
first_user = next(m for m in seen[0] if m["role"] == "user")
assert "合同.pdf" in str(first_user["content"]) and "attachment=" in str(first_user["content"])
tool_msg = next(m for m in seen[1] if m["role"] == "tool")
assert "Page60" in tool_msg["content"] and "这次是第 59–60 页" in tool_msg["content"], tool_msg
assert [(s["tool"], s["state"]) for s in reply.steps] == [("read_file", "done")], reply.steps
print("smoke_documents ok")
