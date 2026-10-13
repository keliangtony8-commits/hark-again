"""把工作区里的 Markdown / HTML / 纯文本排成 PDF 或长图 PNG（v2.22，render_document 工具的唯一规则）。

为什么要有：报告、简历、讲义、海报交给用户时，读起来该是 PDF / 图片，而不是一份 .md（Hark 交付文档也是先排成 PDF）。
沙盒里装 pandoc + TeX 要上 G 的盘、排中文还要配字体；云浏览器里本来就有 Chromium，用它打印最省。

规则（全在这里）：
- 源文件：.md/.markdown → markdown-it（commonmark + 表格 + 删除线 + 允许内嵌 HTML）套上 PRINT_CSS；
  .html/.htm 原样；.txt 和其它文本 → <pre>。二进制 / 文档类（pdf、docx…）不收，给原因。
- 本地资源内嵌：<img src> 和 <link rel=stylesheet href> 指向工作区里的相对路径 → data: / <style>（渲染时浏览器不联网，
  不能指望它去读工作区）。只认源文件所在目录下解析得到、在工作区内、不在隐藏目录、单个 ≤ ASSET_MAX 的；
  找不到 / 越界 / 太大的记进 notes。http(s) 资源不加载（浏览器一侧拦下并回报个数）。
- 输出：默认同名换后缀；只许 .pdf / .png；不进隐藏目录；会覆盖同名文件（改完源文件重排是常态）；
  写之前 quota.check，tracker.before（整轮撤销能撤），原子写入，file_seen.observe。
- 选项：paper A3/A4/A5/Letter/Legal，landscape，width（png 视口宽 320–2000，默认 1024），page_numbers（pdf 页脚页码）。
- 浏览器一侧（browser/service.py POST /render）：一次性上下文、不跑脚本、不联网，PDF 尊重源里的 @page，长图最高 16384 像素。
"""
import asyncio
import base64
import io
import html as html_lib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from . import browser_client, quota, workspace_write
from .storage import hidden, looks_text, mime_of, project_dir, safe_join

FORMATS = ("pdf", "png")
PAPERS = ("A3", "A4", "A5", "Letter", "Legal")  # browser/service.py PAPERS 同值
MD_EXT = frozenset({".md", ".markdown"})
HTML_EXT = frozenset({".html", ".htm"})
SOURCE_MAX = 5 * 1024 * 1024  # 源文件
ASSET_MAX = 5 * 1024 * 1024  # 单个内嵌资源
HTML_MAX = 16 * 1024 * 1024  # 内嵌后的整页（browser RENDER_HTML_MAX 同值）
WIDTH_MIN, WIDTH_MAX, WIDTH_DEFAULT = 320, 2000, 1024
NOTES_SHOWN = 5
IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml", "image/bmp", "image/x-icon"})

PRINT_CSS = """
@page { size: auto; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: "Noto Sans CJK SC", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", -apple-system, "Segoe UI", sans-serif;
       font-size: 11pt; line-height: 1.7; color: #1f2328; max-width: 46em; margin: 0 auto; padding: 8px 4px; }
h1, h2, h3, h4 { line-height: 1.3; margin: 1.4em 0 .5em; break-after: avoid; }
h1 { font-size: 1.9em; border-bottom: 1px solid #d0d7de; padding-bottom: .25em; }
h2 { font-size: 1.45em; border-bottom: 1px solid #eaeef2; padding-bottom: .2em; }
h3 { font-size: 1.2em; }
p, ul, ol, blockquote, table, pre { margin: .6em 0 .9em; }
a { color: #0969da; text-decoration: none; }
img { max-width: 100%; break-inside: avoid; }
blockquote { border-left: 3px solid #d0d7de; color: #57606a; padding: 0 1em; margin-left: 0; }
code { font-family: "JetBrains Mono", "Noto Sans Mono CJK SC", Menlo, Consolas, monospace; font-size: .9em;
       background: #f3f4f6; border-radius: 4px; padding: .1em .35em; }
pre { background: #f6f8fa; border-radius: 6px; padding: .8em 1em; overflow: hidden; white-space: pre-wrap; word-break: break-word; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; font-size: .95em; break-inside: auto; }
tr { break-inside: avoid; }
th, td { border: 1px solid #d0d7de; padding: .4em .7em; text-align: left; vertical-align: top; }
th { background: #f6f8fa; }
hr { border: 0; border-top: 1px solid #d0d7de; margin: 1.6em 0; }
"""


class RenderError(Exception):
    pass


@dataclass
class Rendered:
    rel: str
    size: int
    fmt: str
    pages: int | None = None
    overwrote: bool = False
    notes: list[str] = field(default_factory=list)


def output_for(root: Path, source_rel: str, output: str, fmt: str | None) -> tuple[Path, str]:
    """输出路径 + 格式。output 空 → 源文件换后缀；有后缀就以后缀为准（和 fmt 冲突 → 报错）。"""
    out = (output or "").strip()
    if fmt is not None and fmt not in FORMATS:
        raise RenderError("format 只能是 pdf 或 png。")
    if not out:
        f = fmt or "pdf"
        out = str(Path(source_rel).with_suffix(f".{f}"))
    else:
        ext = Path(out).suffix.lower().lstrip(".")
        if ext in FORMATS:
            if fmt is not None and fmt != ext:
                raise RenderError(f"output 是 .{ext}，format 却是 {fmt}；二选一就行。")
            f = ext
        elif ext:
            raise RenderError(f"只能输出 .pdf 或 .png，{out} 不行。")
        else:
            f = fmt or "pdf"
            out = f"{out}.{f}"
    try:
        p = safe_join(root, out)
    except ValueError:
        raise RenderError(f"{out} 在工作区外面；给相对工作区的路径。") from None
    if hidden(p.relative_to(root).parts):
        raise RenderError(f"{out} 在隐藏目录里，换个地方放。")
    if p.is_dir():
        raise RenderError(f"{out} 是个目录，要给文件名。")
    return p, f


def _source(root: Path, path: str) -> Path:
    try:
        p = safe_join(root, (path or "").strip())
    except ValueError:
        raise RenderError(f"{path} 在工作区外面。") from None
    if p == root or not (path or "").strip():
        raise RenderError("要给源文件路径（.md / .html / .txt）。")
    if hidden(p.relative_to(root).parts):
        raise RenderError(f"{path} 在隐藏目录里，先复制出来再排版。")
    if not p.is_file():
        raise RenderError(f"没有 {path} 这个文件。" + output_mixup(root, p))
    if p.stat().st_size > SOURCE_MAX:
        raise RenderError(f"{path} 超过 {SOURCE_MAX // 1024 // 1024} MB，拆小再排。")
    if p.suffix.lower() not in MD_EXT | HTML_EXT and not looks_text(p):
        raise RenderError(f"{path} 不是文本（只排 Markdown / HTML / 纯文本；PDF、Word 这类先 read_file 读出来再写成 Markdown）。")
    return p


SOURCE_GUESS = (".md", ".markdown", ".html", ".htm", ".txt")


def output_mixup(root: Path, p: Path) -> str:
    """path 写成了输出文件（todo.pdf）= 把 path 和 output 弄反了（v2.38 B12，真实 E2E f10）：说清 path 是源文件，
    有同名源文件就点名它，免得模型另写一份副本再排。不是 .pdf/.png 就空串。"""
    if p.suffix.lower().lstrip(".") not in FORMATS:
        return ""
    found = [c for c in (p.with_suffix(x) for x in SOURCE_GUESS) if c.is_file() and not hidden(c.relative_to(root).parts)]
    tip = f"已有 {found[0].relative_to(root).as_posix()}，直接 path={found[0].relative_to(root).as_posix()}" if found \
        else "先把内容写进一个 .md 文件，再把它当 path"
    return (f"path 是要排版的源文件（.md / .html / .txt），输出文件名写在 output（如 output=\"{p.relative_to(root).as_posix()}\"）；"
            f"{tip}，不要另写一份副本。")


def title_of(text: str, fallback: str) -> str:
    m = re.search(r"^#\s+(.+?)\s*#*\s*$", text, re.M)
    return (m.group(1).strip() if m else "") or fallback


def markdown_html(text: str) -> str:
    from markdown_it import MarkdownIt
    md = MarkdownIt("commonmark", {"html": True, "linkify": False, "typographer": False}).enable(["table", "strikethrough"])
    return md.render(text)


def page(body: str, title: str) -> str:
    return (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{html_lib.escape(title)}</title>'
            f"<style>{PRINT_CSS}</style></head><body>{body}</body></html>")


def to_html(src: Path) -> str:
    """源文件 → 整页 HTML（还没内嵌资源）。"""
    text = src.read_text(encoding="utf-8", errors="replace")
    ext = src.suffix.lower()
    if ext in HTML_EXT:
        return text
    if ext in MD_EXT:
        return page(markdown_html(text), title_of(text, src.stem))
    return page(f"<pre>{html_lib.escape(text)}</pre>", src.stem)


_IMG = re.compile(r"""(<img\b[^>]*?\bsrc\s*=\s*)(["'])(.*?)\2""", re.I | re.S)
_LINK = re.compile(r"""<link\b[^>]*>""", re.I | re.S)
_HREF = re.compile(r"""\bhref\s*=\s*(["'])(.*?)\1""", re.I | re.S)
_STYLESHEET = re.compile(r"""\brel\s*=\s*(["'])[^"']*stylesheet[^"']*\1""", re.I)


def _remote(ref: str) -> bool:
    return bool(re.match(r"^(?:[a-z][a-z0-9+.-]*:|//)", ref, re.I))


def _asset(root: Path, base: Path, ref: str, notes: list[str]) -> Path | None:
    """相对引用 → 工作区里的文件；不行就记一条并返回 None。"""
    clean = unquote(html_lib.unescape(ref).split("#", 1)[0].split("?", 1)[0].strip())
    if not clean:
        return None
    if clean.startswith("/"):  # 沙盒里的绝对路径 /workspace/… 也认；别的绝对路径算工作区外
        rel = clean.removeprefix("/workspace").lstrip("/") if clean == "/workspace" or clean.startswith("/workspace/") else None
    else:
        rel = os.path.relpath(os.path.normpath(base / clean), root)
    try:
        if rel is None or rel.startswith(".."):
            raise ValueError
        p = safe_join(root, rel)
    except ValueError:
        notes.append(f"{ref} 在工作区外面，没放进去")
        return None
    if hidden(p.relative_to(root).parts):
        notes.append(f"{ref} 在隐藏目录里，没放进去")
        return None
    if not p.is_file():
        notes.append(f"找不到 {ref}")
        return None
    if p.stat().st_size > ASSET_MAX:
        notes.append(f"{ref} 超过 {ASSET_MAX // 1024 // 1024} MB，没放进去")
        return None
    return p


def inline_assets(doc: str, root: Path, base: Path) -> tuple[str, list[str]]:
    """把本地图片 / 样式表嵌进 HTML。返回 (新 HTML, notes)。"""
    notes: list[str] = []

    def img(m: re.Match) -> str:
        ref = m.group(3)
        if _remote(ref):
            return m.group(0)
        p = _asset(root, base, ref, notes)
        if p is None:
            return m.group(0)
        mime = mime_of(p.name)
        if mime not in IMAGE_TYPES:
            notes.append(f"{ref} 不是图片，没放进去")
            return m.group(0)
        data = base64.b64encode(p.read_bytes()).decode()
        return f"{m.group(1)}{m.group(2)}data:{mime};base64,{data}{m.group(2)}"

    def link(m: re.Match) -> str:
        tag = m.group(0)
        h = _HREF.search(tag)
        if not _STYLESHEET.search(tag) or h is None or _remote(h.group(2)):
            return tag
        p = _asset(root, base, h.group(2), notes)
        if p is None:
            return tag
        css = p.read_text(encoding="utf-8", errors="replace").replace("</style", "<\\/style")
        return f"<style>{css}</style>"

    return _LINK.sub(link, _IMG.sub(img, doc)), notes


def _write(workspace: str, p: Path, data: bytes, tracker, owner: str | None) -> bool:
    """原子写入（workspace_write.put）；返回是否覆盖了已有文件。配额不够 → RenderError。"""
    try:
        return workspace_write.put(workspace, p, data, tracker, owner)
    except quota.QuotaError as e:
        raise RenderError(f"没有存：{e}") from None


def pdf_pages(data: bytes) -> int | None:
    try:
        from pypdf import PdfReader
        return len(PdfReader(io.BytesIO(data)).pages)
    except Exception:
        return None


async def render(workspace: str, source: str, output: str = "", fmt: str | None = None, paper: str = "A4",
                 landscape: bool = False, width: int = 0, page_numbers: bool = True,
                 tracker=None, owner: str | None = None) -> Rendered:
    if paper not in PAPERS:
        raise RenderError(f"纸张只能是 {'/'.join(PAPERS)}。")
    root = project_dir(workspace)
    src = _source(root, source)
    out, f = output_for(root, src.relative_to(root).as_posix(), output, fmt)
    if out == src:
        raise RenderError("输出不能和源文件同名。")
    doc = await asyncio.to_thread(to_html, src)
    doc, notes = await asyncio.to_thread(inline_assets, doc, root, src.parent)
    if len(doc.encode()) > HTML_MAX:
        raise RenderError(f"放进图片后整页超过 {HTML_MAX // 1024 // 1024} MB，把图片压小些再排。")
    w = min(max(width or WIDTH_DEFAULT, WIDTH_MIN), WIDTH_MAX)
    try:
        data, blocked, cut = await browser_client.render(doc, fmt=f, paper=paper, landscape=landscape, width=w,
                                                         page_numbers=page_numbers)
    except RuntimeError as e:
        raise RenderError(str(e)) from None
    if blocked:
        notes.append(f"{blocked} 个网络资源没加载（排版时不联网；要用的图片先下载进工作区再引用相对路径）")
    if cut:
        notes.append("页面太长，长图只截了最上面 16384 像素；要全部就排成 PDF")
    existed = await asyncio.to_thread(_write, workspace, out, data, tracker, owner)
    return Rendered(out.relative_to(root).as_posix(), len(data), f, pdf_pages(data) if f == "pdf" else None, existed, notes)


def for_model(r: Rendered, shown: bool) -> str:
    what = f"{r.pages} 页 PDF" if r.pages else ("PDF" if r.fmt == "pdf" else "长图 PNG")
    head = f"已排成{what}：{r.rel}（{quota.size_text(r.size)}{'，覆盖了原文件' if r.overwrote else ''}）。"
    tail = "文件卡已经给用户了，回复里一句话说清是什么，别再贴内容。" if shown else "要交给用户就 display_file。"
    if r.notes:
        more = f"……还有 {len(r.notes) - NOTES_SHOWN} 条" if len(r.notes) > NOTES_SHOWN else ""
        head += "注意：" + "；".join(r.notes[:NOTES_SHOWN]) + more + "。"
    if r.fmt == "png":
        tail = "要检查排得对不对可以 read_file 看这张图。" + tail
    return head + tail


def detail(r: Rendered) -> str:
    return f"{r.rel} · {r.pages} 页" if r.pages else r.rel
