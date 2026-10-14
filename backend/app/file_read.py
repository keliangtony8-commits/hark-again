# Copyright (c) 2026 DeepSeek — MIT License (see assistant/NOTICE)
# Ported from deepseek-harness/packages/fs/tool-fs/src/read-render.ts buildWindow + read.ts (MIT), modified:
# 按字节流扫行（不先整篇解码），倒数行（日志看尾巴），按字节窗口，中文提示。
"""read_file 读文本的唯一规则：多大的文件都不整篇读进内存（4 GB VPS 上一个 2 GB 的 CSV 也不会撑爆后端）。

三种读法（mode）：
- chars（默认，向后兼容）：按字符分页；文件小于 STREAM_MIN 才整篇读，超过就改按行给并说明；
- lines：按行，offset 是第几行（从 1 起，和 grep 的“路径:行号”一致；负数 = 最后 N 行），每行带行号前缀；
  一次最多 LINES_MAX 行、WINDOW_BYTES 字节，单行超过 LINE_CHARS 字截断；行数总是数准的（只数换行符，不解码）；
- bytes：按字节，offset 负数 = 从结尾倒数，一次最多 BYTES_MAX；首尾对齐到 UTF-8 字符边界。
v2.77（E2E w5）：文字怎么解码也只在这里（decode）：UTF-8 解得开就是 UTF-8；解不开、按 GBK（gb18030）解得开且确有中文
→ 按 GBK 显示并在开头说一句“这是 GBK 编码”（以前一律 UTF-8 替换成 �，模型以为是乱码、按 Latin-1 乱转）。
只管整篇读的 chars 模式（< STREAM_MIN）；lines/bytes 按字节扫，仍按 UTF-8。压缩包成员（archives.decode_text）同一规则。
"""
import codecs
import re
from dataclasses import dataclass, field
from pathlib import Path

STREAM_MIN = 8 * 1024 * 1024  # 字符分页整篇读的上限（更大的改按行）
CHUNK = 1024 * 1024
CHARS_DEFAULT = 12000
CHARS_MAX = 20000
LINES_MAX = 2000  # deepseek READ_LIMIT
LINE_CHARS = 2000  # deepseek READ_MAX_LINE_LENGTH / Gemini MAX_LINE_LENGTH_TEXT_FILE
WINDOW_BYTES = 24000  # deepseek 是 50 KB；省 token 取和 bytes 模式同一个上限
BYTES_MAX = 24000
BIG_TAIL = 200  # 大文件用字符分页倒数读时，改给最后多少行
MODES = ("chars", "lines", "bytes")


class ReadError(ValueError):
    pass


@dataclass
class Window:
    offset: int  # 第一行的行号（从 1 起）
    lines: list[tuple[int, str]] = field(default_factory=list)
    total: int = 0
    capped: bool = False  # 撞到 WINDOW_BYTES
    cut: bool = False  # 有行被截短

    @property
    def end(self) -> int:
        return self.lines[-1][0] if self.lines else max(0, self.offset - 1)


def _chunks(src):
    """src：Path（流式读）或 bytes（内存里的文字，比如文档抽出来的）。"""
    if isinstance(src, (bytes, bytearray)):
        for i in range(0, len(src), CHUNK):
            yield bytes(src[i:i + CHUNK])
        return
    with Path(src).open("rb") as f:
        while b := f.read(CHUNK):
            yield b


def count_lines(src) -> int:
    """总行数：换行符个数，最后一行没有换行也算一行；空文件 0 行。只数字节，不解码。"""
    n, last = 0, b""
    for b in _chunks(src):
        n += b.count(b"\n")
        last = b
    return n + (1 if last and not last.endswith(b"\n") else 0)


def _cut(line: str) -> tuple[str, bool]:
    if len(line) > LINE_CHARS:
        return f"{line[:LINE_CHARS]}…（这行太长，只显示前 {LINE_CHARS} 字）", True
    return line, False


def window(src, offset: int = 1, limit: int = LINES_MAX, max_bytes: int = WINDOW_BYTES) -> Window:
    """取第 offset 行起最多 limit 行（offset 负数 = 最后 |offset| 行）。

    移植 buildWindow 的语义：每行最多留 LINE_CHARS+1 个字（一行没有换行的巨行也不会撑内存）、
    输出超 max_bytes 就停、照样数完总行数、offset 超出末尾报错（空文件读第 1 行不算错）。
    改动：跳到起始行之前只数换行符（不解码）；窗口满了以后剩下的也只数换行符。"""
    limit = max(1, min(int(limit or LINES_MAX), LINES_MAX))
    offset = int(offset or 1)
    if offset < 0:
        total = count_lines(src)
        offset = max(1, total + offset + 1)
    w = Window(offset)
    line_no = 1  # 当前正在读的行
    buf: list[str] = []  # 当前行已解码的片段
    buf_len = 0
    used = 0
    done = False  # 窗口已满：后面只数行
    dec = codecs.getincrementaldecoder("utf-8")("replace")
    last = b""

    def flush(text: str):
        nonlocal used, done
        if text.endswith("\r"):
            text = text[:-1]
        shown, cut = _cut(text)
        size = len(shown.encode("utf-8")) + (1 if w.lines else 0)
        if used + size > max_bytes and w.lines:
            w.capped, done = True, True
            return
        used += size
        w.cut |= cut
        w.lines.append((line_no, shown))
        if len(w.lines) >= limit:
            done = True

    for b in _chunks(src):
        last = b
        pos = 0
        if done:
            line_no += b.count(b"\n")
            continue
        while pos < len(b):
            if line_no < offset:  # 还没到起始行：只找换行符
                nl = b.find(b"\n", pos)
                if nl < 0:
                    pos = len(b)
                    break
                line_no += 1
                pos = nl + 1
                continue
            if done:
                line_no += b.count(b"\n", pos)
                break
            nl = b.find(b"\n", pos)
            piece = b[pos:] if nl < 0 else b[pos:nl]
            if buf_len <= LINE_CHARS:
                s = dec.decode(piece, final=nl >= 0)
                buf.append(s)
                buf_len += len(s)
            if nl < 0:
                pos = len(b)
                break
            flush("".join(buf))
            buf, buf_len = [], 0
            dec.reset()
            line_no += 1
            pos = nl + 1
    if not done and (buf or (last and not last.endswith(b"\n") and line_no >= offset)):
        flush("".join(buf) + dec.decode(b"", final=True))
    w.total = line_no - (1 if last.endswith(b"\n") or not last else 0)
    if not w.lines and not w.capped and offset > w.total and not (w.total == 0 and offset == 1):
        raise ReadError(f"offset={offset} 超出范围：文件只有 {w.total} 行。")
    return w


def render(w: Window) -> str:
    """每行“行号: 内容”，最后一行说明位置和下一段从哪开始。"""
    if w.capped:
        foot = f"（输出到上限，显示第 {w.offset}–{w.end} 行，共 {w.total} 行；下一段用 mode=lines offset={w.end + 1}）"
    elif w.end < w.total:
        foot = f"（第 {w.offset}–{w.end} 行，共 {w.total} 行；下一段用 mode=lines offset={w.end + 1}）"
    elif w.total == 0:
        foot = "（空文件）"
    else:
        foot = f"（已到结尾，共 {w.total} 行）"
    if w.cut:
        foot = foot[:-1] + f"；有的行超过 {LINE_CHARS} 字被截短，要看全用 mode=bytes）"
    body = "\n".join(f"{n}: {t}" for n, t in w.lines)
    return f"{body}\n\n{foot}" if body else foot


def detail(w: Window) -> str:
    if not w.lines:
        return f"共 {w.total} 行"
    return f"第 {w.offset}–{w.end} 行 / 共 {w.total} 行"


def _lead(raw: bytes) -> int:
    """开头有几个 UTF-8 续字节（最多 3 个）：从字符中间切进来的，跳过。"""
    i = 0
    while i < 3 and i < len(raw) and (raw[i] & 0xC0) == 0x80:
        i += 1
    return i


def _tail(raw: bytes) -> int:
    """结尾不完整的那个字符占几个字节（0 = 完整）。"""
    for back in range(1, min(4, len(raw)) + 1):
        c = raw[-back]
        if (c & 0xC0) == 0x80:
            continue
        need = 2 if c >> 5 == 0b110 else 3 if c >> 4 == 0b1110 else 4 if c >> 3 == 0b11110 else 1
        return back if need > back else 0
    return 0


def read_bytes(src, offset: int = 0, limit: int = BYTES_MAX) -> tuple[str, str]:
    """→ (给模型的文字, detail)。src 是 Path 或 bytes；首尾对齐到字符边界，不吐半个汉字。"""
    limit = max(1, min(int(limit or BYTES_MAX), BYTES_MAX))
    mem = isinstance(src, (bytes, bytearray))
    size = len(src) if mem else Path(src).stat().st_size
    offset = int(offset or 0)
    start = max(0, size + offset) if offset < 0 else min(offset, size)
    if mem:
        raw = bytes(src[start:start + limit])
    else:
        with Path(src).open("rb") as f:
            f.seek(start)
            raw = f.read(limit)
    lead = _lead(raw) if start > 0 else 0
    cut = _tail(raw) if start + len(raw) < size else 0
    raw = raw[lead:len(raw) - cut]
    s, e = start + lead, start + lead + len(raw)
    more = f"下一段用 mode=bytes offset={e}" if e < size else "已到结尾"
    return (f"{raw.decode('utf-8', errors='replace')}\n…（第 {s}–{e} 字节，共 {size} 字节；{more}）",
            f"第 {s}–{e} 字节 / 共 {size}")


GBK_NOTE = "（这个文件是 GBK 编码，下面已按 GBK 解码显示；用户要正常打开的版本就转成 UTF-8：iconv -f GBK -t UTF-8，或 Python 按 gb18030 读、utf-8 写。）\n"


def decode(body: bytes) -> tuple[str, str] | None:
    """文字解码的唯一规则：有 NUL → None（二进制）；UTF-8 解得开 → (文字, "")；GBK 解得开且有中文 → (文字, "GBK")；否则 None。"""
    if b"\0" in body[:65536]:
        return None
    try:
        return body.decode("utf-8-sig"), ""
    except UnicodeDecodeError:
        pass
    try:
        text = body.decode("gb18030")
    except UnicodeDecodeError:
        return None
    return (text, "GBK") if re.search(r"[\u4e00-\u9fff]", text) else None


SNIFF_BYTES = 256 * 1024


def sniff(path) -> str:
    """附件提示用：文件是不是 GBK 编码的中文文字 → "GBK"；其他（UTF-8、二进制、读不了）→ ""。只看开头 SNIFF_BYTES（切到换行）。"""
    try:
        with Path(path).open("rb") as f:
            raw = f.read(SNIFF_BYTES + 1)
    except OSError:
        return ""
    if len(raw) > SNIFF_BYTES:
        raw = raw[:raw.rfind(b"\n", 0, SNIFF_BYTES) + 1] or raw[:SNIFF_BYTES]
    got = decode(raw)
    return got[1] if got else ""


def page(text: str, offset: int = 0, limit: int = CHARS_DEFAULT) -> str:
    """按字符分页：全文放得下原样返回；否则给这一段并说明位置和下一段从哪开始。"""
    total = len(text)
    limit = max(200, min(int(limit or CHARS_DEFAULT), CHARS_MAX))
    start = max(0, total + offset if offset < 0 else min(offset, total))
    if start == 0 and total <= limit:
        return text
    end = min(total, start + limit)
    more = f"下一段用 offset={end}" if end < total else "已到结尾"
    return f"{text[start:end]}\n…（第 {start}–{end} 字符，共 {total} 字符；{more}）"


def size_text(n: int) -> str:
    return f"{n / 1024 / 1024 / 1024:.1f} GB" if n >= 1024 ** 3 else f"{n / 1024 / 1024:.0f} MB"


def read(src, mode: str = "chars", offset: int = 0, limit: int = 0) -> tuple[str, str | None]:
    """唯一入口 → (给模型的文字, 时间线 detail 或 None)。src：Path（流式）或 str（已在内存的文字）。
    limit 0 = 这种读法的默认值。"""
    mode = (mode or "chars").strip().lower()
    if mode not in MODES:
        raise ReadError(f"mode 只能是 {' / '.join(MODES)}。")
    data = src.encode("utf-8") if isinstance(src, str) else src
    if mode == "bytes":
        return read_bytes(data, offset, limit or BYTES_MAX)
    if mode == "lines":
        w = window(data, offset or 1, limit or LINES_MAX)
        return render(w), detail(w)
    if isinstance(src, str):
        return page(src, offset, limit or CHARS_DEFAULT), None
    size = Path(src).stat().st_size
    if size < STREAM_MIN:
        raw = Path(src).read_bytes()
        got = decode(raw)
        if got is not None and got[1] == "GBK":
            return GBK_NOTE + page(got[0], offset, limit or CHARS_DEFAULT), "GBK 编码"
        return page(raw.decode("utf-8", errors="replace"), offset, limit or CHARS_DEFAULT), None
    w = window(src, -BIG_TAIL if offset < 0 else 1, BIG_TAIL if offset < 0 else LINES_MAX)
    note = (f"（文件有 {size_text(size)}，按字符分页要整篇读进内存，改按行给"
            f"{'最后 ' + str(BIG_TAIL) + ' 行' if offset < 0 else ''}；之后用 mode=lines 按行号读，或 mode=bytes 按字节读。）\n")
    return note + render(w), detail(w)
