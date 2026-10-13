"""文档变文字——唯一的规则：PDF / Word / Excel / PowerPoint 怎么变成给模型读的正文、按页怎么选。

读工作区文件（read_file）、聊天附件、结构化提取（extract_data）、读网页遇到 PDF（web_page）都走这里，结果一致：
- PDF：pypdf 逐页抽文字，每页前一行 `--- 第 N 页 ---`；没文字的页记下来（多半是扫描图，提示转图片再看）；
- Word（.docx）：段落按顺序，标题前加 #，表格按行变成 `| a | b |`；
- Excel（.xlsx）：每张表 `--- 表 名字 ---`，每行单元格用 `|` 隔开（共享字符串、行内字符串、数字原样），每表最多 SHEET_ROWS 行；
- PowerPoint（.pptx）：每张幻灯片 `--- 第 N 张 ---` + 文字；
- “页”：PDF 是页，pptx 是幻灯片，xlsx 是工作表；pages="1-5,9" 选（一次最多 PAGES_MAX 页），不给 = 从第 1 页起 PAGES_MAX 页。
只用 pypdf + 标准库 zipfile/xml（不装 LibreOffice：小 VPS 装不起），老格式 .doc/.xls/.ppt 不认（提示在电脑里转）。"""
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

PAGES_MAX = 50           # 一次最多抽这么多页（同 web_page 以前的 PDF_PAGES）
SHEET_ROWS = 2000        # 一张表最多读这么多行
ZIP_XML_MAX = 64 * 1024 * 1024  # 解压后单个 xml 上限：防压缩炸弹
SPEC_MAX = 200
FILE_MAX = 50 * 1024 * 1024  # 文档文件上限：pypdf 按页懒读，50 MB 的扫描件也只在抽到的页上花时间

KINDS = {".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx", ".xlsm": "xlsx", ".pptx": "pptx"}
LABEL = {"pdf": "PDF", "docx": "Word 文档", "xlsx": "Excel 表格", "pptx": "PowerPoint"}
TOTAL = {"pdf": "页", "xlsx": "张表", "pptx": "张幻灯片"}
NTH = {"pdf": "页", "docx": "页", "xlsx": "张表", "pptx": "张"}
OLD = {".doc", ".xls", ".ppt"}

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


class DocError(Exception):
    pass


@dataclass
class Doc:
    kind: str
    total: int                       # 总页数（docx 没有页的概念 = 1）
    text: str
    shown: list[int] = field(default_factory=list)   # 这次抽了哪些页
    blank: list[int] = field(default_factory=list)   # 抽了但没文字的页

    def header(self, name: str) -> str:
        """给模型的一行说明：是什么、共几页、这次是哪些、没文字的页、下一批怎么要。"""
        out = f"{name}：{LABEL[self.kind]}" if name else LABEL[self.kind]
        if self.kind != "docx":
            out += f"，共 {self.total} {TOTAL[self.kind]}"
            if self.shown and len(self.shown) < self.total:
                out += f"，这次是第 {spans(self.shown)} {NTH[self.kind]}"
        out += "。"
        if self.blank and self.text:
            out += f"第 {spans(self.blank)} {NTH[self.kind]}没有可提取的文字"
            out += self._scan_hint() + "。"
        elif self.blank:
            out += "没有可提取的文字" + self._scan_hint() + "。"
        if self.shown and self.shown[-1] < self.total:
            nxt = self.shown[-1] + 1
            out += f"后面还有，下一批用 pages=\"{nxt}-{min(self.total, nxt + PAGES_MAX - 1)}\"。"
        return out

    def _scan_hint(self) -> str:
        if self.kind != "pdf":
            return ""
        first = self.blank[0]
        return (f"（多半是扫描图：可以 run_command `pdftoppm -f {first} -l {first} -r 100 -png 文件.pdf 页` "
                "转成图片再 read_file 看）")


def kind_of(name: str, head: bytes = b"") -> str | None:
    """按扩展名认；没扩展名时 %PDF- 开头也算 PDF。不是文档 = None。"""
    m = re.search(r"\.[A-Za-z0-9]+$", name or "")
    ext = m.group(0).lower() if m else ""
    if ext in KINDS:
        return KINDS[ext]
    if head[:5] == b"%PDF-":
        return "pdf"
    return None


def is_old(name: str) -> bool:
    m = re.search(r"\.[A-Za-z0-9]+$", name or "")
    return bool(m) and m.group(0).lower() in OLD


def spans(nums: list[int]) -> str:
    """[1,2,3,7,9,10] → "1–3、7、9–10"。"""
    out, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if i == j else f"{nums[i]}–{nums[j]}")
        i = j + 1
    return "、".join(out)


def parse_pages(spec: str | None, total: int) -> list[int]:
    """"1-5,9" / "3" / "10-" → 升序去重的页码（1 起）。空 = 前 PAGES_MAX 页。超出总页数的去掉；全部越界 / 写错 → DocError。"""
    if total <= 0:
        return []
    s = (spec or "").strip()
    if not s:
        return list(range(1, min(total, PAGES_MAX) + 1))
    if len(s) > SPEC_MAX:
        raise DocError("pages 太长了，写成 \"1-5,9\" 这样。")
    got: set[int] = set()
    for part in re.split(r"[,，、\s]+", s):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*(?:[-–~]\s*(\d*))?", part)
        if not m:
            raise DocError(f"pages 看不懂“{part}”，写成 \"1-5,9\" 这样（页码从 1 开始）。")
        a = int(m.group(1))
        b = a if m.group(2) is None else (int(m.group(2)) if m.group(2) else total)
        if a < 1 or b < a:
            raise DocError(f"pages 的“{part}”不对：页码从 1 开始、前小后大。")
        got.update(range(a, min(b, total) + 1))
        if len(got) > PAGES_MAX:
            break
    pages = sorted(p for p in got if p <= total)
    if not pages:
        raise DocError(f"一共只有 {total} 页，pages=\"{s}\" 超出了。")
    return pages[:PAGES_MAX]


def read(body: bytes, name: str, pages: str | None = None) -> Doc:
    """把文档变成文字。认不出 / 打不开 → DocError（一句能照做的话）。"""
    kind = kind_of(name, body[:8])
    if kind is None:
        if is_old(name):
            raise DocError(f"{name} 是老格式（.doc/.xls/.ppt），读不了：可以在电脑里 "
                           "`soffice --headless --convert-to docx` 之类转成新格式，或先另存为 PDF。")
        raise DocError(f"{name} 不是 PDF / Word / Excel / PowerPoint 文档。")
    if kind == "pdf":
        return _pdf(body, pages)
    try:
        z = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile as e:
        raise DocError(f"{name} 打不开（不是完整的 {LABEL[kind]}，可能文件不完整或加密了）。") from e
    with z:
        return {"docx": _docx, "xlsx": _xlsx, "pptx": _pptx}[kind](z, pages)


# ---- PDF ----
def _pdf(body: bytes, spec: str | None) -> Doc:
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(body))
        if reader.is_encrypted:
            try:
                reader.decrypt("")  # 只有“权限密码”的 PDF 用空密码就能读
            except Exception:
                pass
        all_pages = reader.pages
        total = len(all_pages)
    except Exception as e:  # pypdf 对坏文件抛各种异常
        raise DocError(f"这个 PDF 打不开（{e.__class__.__name__}），可能文件不完整或加了密码。") from e
    shown = parse_pages(spec, total)
    out, blank = [], []
    for i in shown:
        try:
            t = (all_pages[i - 1].extract_text() or "").strip()
        except Exception:
            t = ""
        if t:
            out.append(f"--- 第 {i} 页 ---\n{t}")
        else:
            blank.append(i)
    return Doc("pdf", total, "\n\n".join(out), shown, blank)


# ---- Office（zip + xml）----
def _xml(z: zipfile.ZipFile, path: str) -> ET.Element | None:
    try:
        info = z.getinfo(path)
    except KeyError:
        return None
    if info.file_size > ZIP_XML_MAX:
        raise DocError(f"文档里的 {path} 解压后太大（{info.file_size} B），不读。")
    try:
        return ET.fromstring(z.read(info))
    except ET.ParseError as e:
        raise DocError(f"文档里的 {path} 坏了（{e}）。") from e


def _rels(z: zipfile.ZipFile, path: str) -> dict[str, str]:
    """关系文件：rId → 目标（相对路径）。"""
    root = _xml(z, path)
    return {} if root is None else {r.get("Id"): r.get("Target", "") for r in root.iter(f"{REL}Relationship")}


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def _docx(z: zipfile.ZipFile, spec: str | None) -> Doc:
    root = _xml(z, "word/document.xml")
    if root is None:
        raise DocError("这个 Word 文档里没有正文（word/document.xml）。")
    body = root.find(f"{W}body")
    lines: list[str] = []

    def para(p: ET.Element) -> str:
        return "".join(t.text or "" if t.tag == f"{W}t" else "\t" if t.tag == f"{W}tab" else "\n"
                       for t in p.iter() if t.tag in (f"{W}t", f"{W}tab", f"{W}br", f"{W}cr")).strip()

    for el in (body if body is not None else []):
        if el.tag == f"{W}p":
            t = para(el)
            if not t:
                continue
            style = el.find(f"{W}pPr/{W}pStyle")
            sid = (style.get(f"{W}val") if style is not None else "") or ""
            m = re.match(r"(?i)heading\s*(\d)|标题\s*(\d)|title$", sid)
            if m:
                level = int(m.group(1) or m.group(2) or 1)
                t = "#" * min(level, 6) + " " + t
            lines.append(t)
        elif el.tag == f"{W}tbl":
            for tr in el.iter(f"{W}tr"):
                cells = [_cell(" ".join(para(p) for p in tc.iter(f"{W}p"))) for tc in tr.iter(f"{W}tc")]
                if any(cells):
                    lines.append("| " + " | ".join(cells) + " |")
    text = "\n".join(lines)
    return Doc("docx", 1, text, [1], [] if text else [1])


def _shared(z: zipfile.ZipFile) -> list[str]:
    root = _xml(z, "xl/sharedStrings.xml")
    if root is None:
        return []
    return ["".join(t.text or "" for t in si.iter(f"{S}t")) for si in root.iter(f"{S}si")]


def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]*", ref or "").group(0):
        n = n * 26 + ord(ch) - 64
    return n


def _xlsx(z: zipfile.ZipFile, spec: str | None) -> Doc:
    wb = _xml(z, "xl/workbook.xml")
    if wb is None:
        raise DocError("这个 Excel 文件里没有工作簿（xl/workbook.xml）。")
    rels = _rels(z, "xl/_rels/workbook.xml.rels")
    sheets = [(s.get("name", ""), rels.get(s.get(R_ID), "")) for s in wb.iter(f"{S}sheet")]
    total = len(sheets)
    shown = parse_pages(spec, total)
    strings = _shared(z)
    out, blank = [], []
    for i in shown:
        name, target = sheets[i - 1]
        path = target.lstrip("/") if target.startswith("/") else "xl/" + target
        root = _xml(z, path)
        rows: list[str] = []
        more = 0
        for row in (root.iter(f"{S}row") if root is not None else []):
            if len(rows) >= SHEET_ROWS:
                more += 1
                continue
            cells: dict[int, str] = {}
            for c in row.iter(f"{S}c"):
                t, v = c.get("t"), c.find(f"{S}v")
                if t == "s" and v is not None and (v.text or "").isdigit():
                    k = int(v.text)
                    val = strings[k] if k < len(strings) else ""
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(f"{S}t"))
                else:
                    val = (v.text or "") if v is not None else ""
                if val != "":
                    cells[_col(c.get("r", "")) or len(cells) + 1] = _cell(val)
            if cells:
                width = max(cells)
                rows.append("| " + " | ".join(cells.get(k, "") for k in range(1, width + 1)) + " |")
        if rows:
            tail = f"\n…（这张表还有 {more} 行没读，要全部就在电脑里用 python 读）" if more else ""
            out.append(f"--- 表 {i}：{name} ---\n" + "\n".join(rows) + tail)
        else:
            blank.append(i)
    return Doc("xlsx", total, "\n\n".join(out), shown, blank)


def _pptx(z: zipfile.ZipFile, spec: str | None) -> Doc:
    pres = _xml(z, "ppt/presentation.xml")
    rels = _rels(z, "ppt/_rels/presentation.xml.rels")
    P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
    ids = [] if pres is None else [s.get(R_ID) for s in pres.iter(f"{P}sldId")]
    slides = [rels.get(i, "") for i in ids]
    if not slides:  # 没有顺序表：按文件名编号
        slides = sorted((n.removeprefix("ppt/") for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                        key=lambda n: int(re.search(r"\d+", n).group(0)))
    total = len(slides)
    shown = parse_pages(spec, total)
    out, blank = [], []
    for i in shown:
        root = _xml(z, "ppt/" + slides[i - 1].lstrip("/").removeprefix("ppt/"))
        paras = []
        for p in (root.iter(f"{A}p") if root is not None else []):
            t = "".join(x.text or "" for x in p.iter(f"{A}t")).strip()
            if t:
                paras.append(t)
        if paras:
            out.append(f"--- 第 {i} 张 ---\n" + "\n".join(paras))
        else:
            blank.append(i)
    return Doc("pptx", total, "\n\n".join(out), shown, blank)


def preview(path: Path, cache: Path, chars: int) -> tuple[str, str, bool]:
    """聊天附件给模型的开头：(说明行, 前 chars 字, 后面还有没有)。每轮历史都要渲染，按上传 id 缓存（一个附件只抽一次）。
    读不了 → (原因, "", False)，同样缓存。"""
    try:
        got = json.loads(cache.read_text(encoding="utf-8"))
        if got.get("chars") == chars:
            return got["header"], got["text"], got["more"]
    except (OSError, ValueError, KeyError):
        pass
    try:
        if path.stat().st_size > FILE_MAX:
            raise DocError(f"{path.name} 太大（{path.stat().st_size} B），读不了。")
        doc = read(path.read_bytes(), path.name)
        header, text = doc.header(""), doc.text[:chars]
        more = len(doc.text) > chars or (bool(doc.shown) and doc.shown[-1] < doc.total)
    except DocError as e:
        header, text, more = str(e), "", False
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"chars": chars, "header": header, "text": text, "more": more}, ensure_ascii=False),
                         encoding="utf-8")
    except OSError:
        pass
    return header, text, more
