# Copyright 2025 OpenAI
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
#
# Ported from openai/codex codex-rs/apply-patch/src/{parser.rs, streaming_parser.rs, file_update.rs,
# text_file.rs, lib.rs, invocation.rs} (Apache-2.0), modified:
#   语法、宽松边界（<<EOF heredoc 包裹、标记两侧空白）、逐行状态机与每条报错的位置、compute_replacements
#   （@@ 上下文定位、结尾空行哨兵重试、上下文行保留原换行）、SourceFile 按行保留 LF / CRLF / CR 原样翻译；
#   seek_sequence 复用 file_edit.py 里已移植的那份。
# 修改：①两阶段——先在内存里把整份补丁算完（同一文件被多段碰到时后段看前段的结果），任何一段对不上就一个文件都不动；
#       提交时出 OSError 把已写的全部退回（Codex 顺序落盘，失败时留下前面的改动，见其 scenario 015）；
#       ②路径限定在工作区内、不碰隐藏目录（.spill/.turns/.home…），不接受 Environment ID；
#       ③报错改成中文（保留行号和原文），给模型的话说清怎么补救；
#       ④run_command 里整条命令就是 `apply_patch <<'EOF' … EOF`（可带 `cd 子目录 &&`）时由 from_command 认出来改走这里
#         （Codex invocation.rs 的同一规则，用正则代替 tree-sitter 查询，同样只认整条就是这一句）。
"""多文件补丁（apply_patch）的唯一规则：解析、在内存里算出结果、整体提交或整体不动。

为什么有它：edit_file 一次只换一处；改一个功能常要动三四个文件、几十处，还要新建、删除、改名。
Codex 的模型就是用这个格式改代码的（GPT / DeepSeek / 阶跃等模型大多见过），一次调用、一份补丁：

*** Begin Patch
*** Add File: 路径          新建（之后每行以 + 开头）
*** Delete File: 路径       删除
*** Update File: 路径       修改（可紧跟 *** Move to: 新路径 改名）
@@ 可选的定位行（类名 / 函数名）
 上下文行（空格开头）
-删掉的行
+加上的行
*** End of File             可选：这一段必须落在文件结尾
*** End Patch

parse(text) → list[Hunk]；plan(root, hunks, …) → Plan（每个受影响文件的 原文 → 新文）；commit(plan) 写盘（失败全退）。
工具在 agent/builtin/workspace.py 的 apply_patch；配额、读后再改检查（file_seen）、整轮撤销基线（turn_changes）、
改动摘要（file_edit.change）都在工具那里接，这里只管补丁本身。
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from .file_edit import seek_sequence
from .storage import hidden, safe_join

BEGIN = "*** Begin Patch"
END = "*** End Patch"
ADD = "*** Add File: "
DELETE = "*** Delete File: "
UPDATE = "*** Update File: "
MOVE = "*** Move to: "
EOF_MARK = "*** End of File"
CONTEXT = "@@ "
EMPTY_CONTEXT = "@@"
ENVIRONMENT = "*** Environment ID:"

READ_MAX = 8 * 1024 * 1024  # 要改的文件超过这么大就不按行打补丁（用 run_command 处理）
HEADERS = "'*** Add File: 路径'、'*** Delete File: 路径'、'*** Update File: 路径'"
COMMANDS = ("apply_patch", "applypatch")


class PatchError(Exception):
    """没改成：消息给模型（说清哪一行、怎么补救）；short 给时间线那一步当原因。"""

    def __init__(self, message: str, short: str = "补丁没打上"):
        super().__init__(message)
        self.short = short


def _hunk_error(message: str, line: int) -> PatchError:
    return PatchError(f"补丁第 {line} 行：{message}", "补丁格式不对")


@dataclass
class Chunk:
    """Codex UpdateFileChunk：old_lines 换成 new_lines；context 定位行；context_lines = 上下文行在两侧的下标。"""
    context: str | None = None
    old: list[str] = field(default_factory=list)
    new: list[str] = field(default_factory=list)
    context_lines: list[tuple[int, int]] = field(default_factory=list)
    eof: bool = False

    def push_context(self, line: str) -> None:
        self.context_lines.append((len(self.old), len(self.new)))
        self.old.append(line)
        self.new.append(line)

    @property
    def empty(self) -> bool:
        return not self.old and not self.new


@dataclass
class Hunk:
    kind: str                      # add | delete | update
    path: str
    contents: str = ""             # add
    move_to: str | None = None     # update
    chunks: list[Chunk] = field(default_factory=list)


# ---------------------------------------------------------------- 解析（parser.rs + streaming_parser.rs）

def _boundaries(lines: list[str]) -> list[str]:
    """Codex check_patch_boundaries_lenient：首尾必须是 Begin/End（两侧空白不算）；
    不是的话看是不是整份被 <<EOF / <<'EOF' / <<"EOF" … EOF 包着（≥4 行），剥掉再查一次。"""
    def strict(ls: list[str]) -> None:
        first = ls[0].strip() if ls else None
        last = ls[-1].strip() if ls else None
        if first == BEGIN and last == END:
            return
        if first != BEGIN:
            raise PatchError("第一行必须是 '*** Begin Patch'。", "补丁格式不对")
        raise PatchError("最后一行必须是 '*** End Patch'。", "补丁格式不对")

    try:
        strict(lines)
        return lines
    except PatchError as original:
        if len(lines) >= 4 and lines[0] in ("<<EOF", "<<'EOF'", '<<"EOF"') and lines[-1].endswith("EOF"):
            inner = lines[1:-1]
            strict(inner)
            return inner
        raise original


def _fences(text: str) -> str:
    """嫁接：模型偶尔把补丁包在 ``` 代码块里——首尾各一行围栏就剥掉。"""
    ls = text.strip().split("\n")
    if len(ls) >= 3 and ls[0].strip().startswith("```") and ls[-1].strip() == "```":
        return "\n".join(ls[1:-1])
    return text


class _Parser:
    """Codex StreamingPatchParser 的逐行状态机（我们一次拿到整份，不需要流式，但规则与报错位置一致）。"""

    def __init__(self) -> None:
        self.mode = "not_started"   # not_started | started | add | delete | update | ended
        self.hunks: list[Hunk] = []
        self.line_no = 0
        self.hunk_line = 0
        self.environment = False
        self.blanks = 0             # Add File 里还没定性的裸空行（见 line()）

    def _ensure_update_not_empty(self, line: str) -> None:
        h = self.hunks[-1] if self.hunks else None
        if h is None or h.kind != "update":
            return
        if not h.chunks and self.mode == "update":
            raise _hunk_error(f"修改 '{h.path}' 的段是空的（Update File 之后至少要有一处改动）。", self.hunk_line)
        if h.chunks and h.chunks[-1].empty:
            if line == END:
                raise _hunk_error("这一段 @@ 之后没有任何改动行。", self.line_no)
            raise _hunk_error(f"修改段里出现了意外的一行：'{line}'。每行都要以 ' '（上下文）、'+'（加）或 '-'（删）开头。",
                              self.line_no)

    def _headers(self, trimmed: str) -> bool:
        if self.mode == "started" and trimmed.startswith(ENVIRONMENT):
            raise _hunk_error("这里不支持 '*** Environment ID'，去掉这一行即可。", self.line_no)
        if trimmed == END:
            self._ensure_update_not_empty(trimmed)
            self.mode = "ended"
            return True
        for marker, kind in ((ADD, "add"), (DELETE, "delete"), (UPDATE, "update")):
            if trimmed.startswith(marker):
                self._ensure_update_not_empty(trimmed)
                path = trimmed[len(marker):].strip()
                if not path:
                    raise _hunk_error(f"'{marker.strip()}' 后面要写路径。", self.line_no)
                self.hunks.append(Hunk(kind, path))
                self.mode = kind
                if kind == "update":
                    self.hunk_line = self.line_no
                return True
        return False

    def line(self, line: str) -> None:
        self.line_no += 1
        trimmed = line.strip()
        bad_header = f"'{trimmed}' 不是有效的段头。有效段头：{HEADERS}。"
        if self.mode == "not_started":
            if trimmed == BEGIN:
                self.mode = "started"
                return
            raise PatchError("第一行必须是 '*** Begin Patch'。", "补丁格式不对")
        if self.mode in ("started", "delete"):
            if self._headers(trimmed):
                return
            if not trimmed:
                return                   # 段与段之间的空行：忽略
            raise _hunk_error(bad_header, self.line_no)
        if self.mode == "add":
            # 唯一规则（E2E B10）：Add File 里的裸空行，后面还有 + 行 → 是一行空内容；
            # 后面紧跟段头 / End Patch → 段间空行，丢掉。（以前当成坏段头报错，模型改写成 "++" 把文件弄脏。）
            if not trimmed:
                self.blanks += 1
                return
            if self._headers(trimmed):
                self.blanks = 0
                return
            if line.startswith("+"):
                self.hunks[-1].contents += "\n" * self.blanks + line[1:] + "\n"
                self.blanks = 0
                return
            raise _hunk_error(bad_header + "新建文件的内容每行都要以 + 开头。", self.line_no)
        if self.mode == "ended":
            if trimmed:
                raise PatchError("'*** End Patch' 之后不能再有内容。", "补丁格式不对")
            return
        self._update(line)

    def _update(self, line: str) -> None:
        u = line.rstrip()
        if self._headers(u):
            return
        h = self.hunks[-1]
        chunks = h.chunks
        is_context = u == EMPTY_CONTEXT or u.startswith(CONTEXT)
        if chunks and chunks[-1].eof:
            if not u:
                return
            if not is_context:
                raise _hunk_error(f"'*** End of File' 之后新的一处改动要以 @@ 开头，看到的是：'{line}'。", self.line_no)
        if not chunks and h.move_to is None and u.startswith(MOVE):
            dest = u[len(MOVE):].strip()
            if not dest:
                raise _hunk_error("'*** Move to:' 后面要写新路径。", self.line_no)
            h.move_to = dest
            return
        if is_context and chunks and chunks[-1].empty:
            raise _hunk_error(f"修改段里出现了意外的一行：'{line}'。每行都要以 ' '（上下文）、'+'（加）或 '-'（删）开头。",
                              self.line_no)
        if u == EMPTY_CONTEXT:
            chunks.append(Chunk())
            return
        if u.startswith(CONTEXT):
            chunks.append(Chunk(context=u[len(CONTEXT):]))
            return
        if u == EOF_MARK:
            if chunks and chunks[-1].empty:
                raise _hunk_error("这一段 @@ 之后没有任何改动行。", self.line_no)
            if chunks:
                chunks[-1].eof = True
            return
        if not line or line[0] in " +-":
            if not chunks:
                chunks.append(Chunk())
            c = chunks[-1]
            if not line:
                c.push_context("")       # 空行 = 空的上下文行（模型常把 ' ' 吃掉）
            elif line[0] == " ":
                c.push_context(line[1:])
            elif line[0] == "+":
                c.new.append(line[1:])
            else:
                c.old.append(line[1:])
            return
        if chunks and not chunks[-1].empty:
            raise _hunk_error(f"新的一处改动要以 @@ 开头，看到的是：'{line}'。", self.line_no)
        raise _hunk_error(f"修改段里出现了意外的一行：'{line}'。每行都要以 ' '（上下文）、'+'（加）或 '-'（删）开头。",
                          self.line_no)

    def last(self, line: str) -> None:
        """Codex finish()：最后一行（没有换行结尾的那行）两侧去空白后是 End Patch 就直接收尾——
        所以缩进的 ' *** End Patch' 在最后一行也认（修改段里别处的缩进标记仍当上下文行）。"""
        if line.strip() == END and self.mode != "not_started":
            self.line_no += 1
            self.blanks = 0
            self._ensure_update_not_empty(END)
            self.mode = "ended"
            return
        self.line(line)

    def finish(self) -> list[Hunk]:
        if self.mode != "ended":
            raise PatchError("最后一行必须是 '*** End Patch'。", "补丁格式不对")
        return self.hunks


def parse(text: str) -> list[Hunk]:
    """补丁文本 → 各段。格式不对抛 PatchError（带行号）。"""
    lines = [ln.removesuffix("\r") for ln in _fences(text).strip().split("\n")]  # 同 Rust lines()：只按 \n 拆
    body = _boundaries(lines)
    p = _Parser()
    for ln in body[:-1]:
        p.line(ln)
    p.last(body[-1])
    return p.finish()


# ---------------------------------------------------------------- 按行保留换行符的文本（text_file.rs）

_ENDING = re.compile(r"\r\n|\r|\n")


class SourceFile:
    """把文件拆成（行文字, 换行符）；第一种出现的换行是插入新行时用的（没有换行的文件默认 \\n）。"""

    def __init__(self, contents: str):
        self.lines: list[list] = []   # [text, ending | None]
        self.preferred: str | None = None
        start = 0
        for m in _ENDING.finditer(contents):
            self.preferred = self.preferred or m.group()
            self.lines.append([contents[start:m.start()], m.group()])
            start = m.end()
        if start < len(contents):
            self.lines.append([contents[start:], None])
        self.preferred = self.preferred or "\n"

    def texts(self) -> list[str]:
        return [t for t, _ in self.lines]

    def apply(self, replacements: list[tuple[int, int, list[str]]]) -> str:
        """按源顺序、不重叠的 (起始行, 删几行, 新行) 重建：没动的行留原换行，新行用首选换行，每行最后都补上换行。"""
        out: list[list] = []
        src = 0
        for start, old_len, new in replacements:
            out.extend(self.lines[src:start])
            out.extend([t, self.preferred] for t in new)
            src = start + old_len
        out.extend(self.lines[src:])
        return "".join(t + (e or self.preferred) for t, e in out)


def _replacements(lines: list[str], path: str, chunks: list[Chunk]) -> list[tuple[int, int, list[str]]]:
    """Codex compute_replacements：逐段定位（先 @@ 定位行，再原文行，都要在上一段之后），上下文行原样保留。"""
    out: list[tuple[int, int, list[str]]] = []
    at = 0
    for c in chunks:
        if c.context is not None:
            idx = seek_sequence(lines, [c.context], at, False)
            if idx is None:
                raise PatchError(f"在 {path} 里没找到定位行 '@@ {c.context}'（要在上一处改动之后）。先 read_file 看准再写。",
                                 "补丁对不上原文")
            at = idx + 1
        if not c.old:
            out.append((len(lines), 0, list(c.new)))   # 纯新增：加到文件末尾
            continue
        pattern, new = c.old, c.new
        found = seek_sequence(lines, pattern, at, c.eof)
        if found is None and pattern and pattern[-1] == "":
            # 结尾的空行代表文件最后的换行，SourceFile 不把它当一行：去掉再找
            pattern = pattern[:-1]
            if new and new[-1] == "":
                new = new[:-1]
            found = seek_sequence(lines, pattern, at, c.eof)
        if found is None:
            shown = "\n".join(c.old[:12]) + ("\n…" if len(c.old) > 12 else "")
            raise PatchError(f"在 {path} 里没找到要改的这几行（要在上一处改动之后、和文件里一致）：\n{shown}\n"
                             "先 read_file 看准原文，上下文行照抄文件里的内容。", "补丁对不上原文")
        o = n = 0
        for oc, nc in c.context_lines:
            if oc >= len(pattern) or nc >= len(new):
                break
            if o != oc or n != nc:
                out.append((found + o, oc - o, list(new[n:nc])))
            o, n = oc + 1, nc + 1
        if o != len(pattern) or n != len(new):
            out.append((found + o, len(pattern) - o, list(new[n:])))
        at = found + len(pattern)
    out.sort(key=lambda r: r[0])
    for (a, la, _), (b, _, _) in zip(out, out[1:]):
        if a + la > b:
            raise PatchError(f"{path} 里有两处改动重叠了：合成一处再写。", "补丁对不上原文")
    return out


def update_text(original: str, path: str, chunks: list[Chunk]) -> str:
    """Codex derive_new_contents_from_chunks（不读盘，纯文本）。"""
    src = SourceFile(original)
    return src.apply(_replacements(src.texts(), path, chunks))


# ---------------------------------------------------------------- 在内存里算整份补丁，整体提交

@dataclass
class Entry:
    """一个受影响的路径：disk = 补丁之前磁盘上的字节（None = 不存在）；after = 补丁之后的文字（None = 不存在 / 删掉）。"""
    rel: str
    p: Path
    disk: bytes | None
    after: str | None = None
    binary: bool = False            # 磁盘上有、但不是 UTF-8 文本（能删、能整篇 Add 覆盖，不能按行改）
    touched: bool = False           # 被补丁里的某一段动过
    origin: "Entry | None" = None   # 改名的新位置：原文件（摘要显示 a → b，diff 按原文件算）
    moved_away: bool = False        # 改名的旧位置：摘要里并进新位置那一项
    whole: bool = False             # 整篇换掉（Add 到已有文件 / 改名到已有文件）：工具按 write_file 的“读过才能覆盖”把关
    order: int = 0

    @property
    def exists(self) -> bool:
        return self.after is not None or (self.binary and not self.touched)

    @property
    def before_text(self) -> str | None:
        """diff 的“之前”：改名过来的按原文件算；不存在 → None（新建）。"""
        src = self.origin if self.origin is not None and self.disk is None else self
        if src.disk is None:
            return None
        return "" if src.binary else src.disk.decode("utf-8")

    @property
    def changed(self) -> bool:
        if not self.touched:
            return False
        if self.after is None:
            return self.disk is not None
        return self.disk is None or self.disk != self.after.encode("utf-8")


@dataclass
class Plan:
    entries: list[Entry]
    hunks: int

    @property
    def growth(self) -> int:
        return sum(len(e.after.encode()) - len(e.disk or b"") for e in self.entries if e.after is not None and e.changed)


def _rel(root: Path, raw: str) -> tuple[str, Path]:
    try:
        p = safe_join(root, raw)
    except ValueError:
        raise PatchError(f"路径 {raw} 在工作区外面，只能改工作区里的文件。", "路径越界") from None
    rel = p.relative_to(root.resolve()).as_posix() if p != root.resolve() else ""
    if not rel:
        raise PatchError(f"路径 {raw} 指向工作区根目录，要写到具体文件。", "路径不对")
    if hidden(Path(rel).parts):
        raise PatchError(f"{rel} 在隐藏的系统目录里，不能用补丁改。", "隐藏目录")
    return rel, p


def plan(root: Path, hunks: list[Hunk]) -> Plan:
    """按顺序在内存里执行每一段（后面的段看到前面段的结果），算出每个路径的最终文字。任何一段不成立就抛 PatchError，
    磁盘一个字节都没动。"""
    if not hunks:
        raise PatchError("补丁里没有任何改动（Begin/End 之间至少要有一段 Add / Delete / Update）。", "空补丁")
    root = root.resolve()
    state: dict[str, Entry] = {}

    def entry(raw: str) -> Entry:
        rel, p = _rel(root, raw)
        if (e := state.get(str(p))) is None:
            if p.is_dir():
                raise PatchError(f"{rel} 是目录，补丁只能处理文件。", "是目录")
            disk = None
            if p.exists():
                if p.stat().st_size > READ_MAX:
                    raise PatchError(f"{rel} 太大（超过 {READ_MAX // 1024 // 1024} MB），不按补丁改；可以用 run_command 处理。",
                                     "文件太大")
                disk = p.read_bytes()
            e = state[str(p)] = Entry(rel, p, disk, order=len(state))
            e.after = _text_or_none(disk)
            e.binary = disk is not None and e.after is None
        return e

    for h in hunks:
        e = entry(h.path)
        if h.kind == "add":   # Codex：已存在也直接覆盖（是否读过由工具那边的 file_seen 把关）
            e.after, e.touched, e.moved_away, e.origin, e.whole = h.contents, True, False, None, True
            continue
        if not e.exists:
            what = "删除" if h.kind == "delete" else "修改"
            hint = "" if h.kind == "delete" else f"：新建文件用 '*** Add File: {h.path}'"
            raise PatchError(f"要{what}的 {e.rel} 不存在{hint}。", "文件不存在")
        if h.kind == "delete":
            e.after, e.touched, e.moved_away, e.origin = None, True, False, None
            continue
        if e.after is None:
            raise PatchError(f"{e.rel} 不是 UTF-8 文本，不能按行打补丁；可以用 run_command 处理。", "不是文本文件")
        new = update_text(e.after, e.rel, h.chunks)
        e.touched = True
        d = entry(h.move_to) if h.move_to is not None else e
        d.after, d.touched = new, True
        if d is not e:
            d.moved_away, d.whole = False, True
            d.origin = e.origin or (e if e.disk is not None else None)
            e.after, e.moved_away, e.origin = None, True, None
    return Plan(sorted(state.values(), key=lambda x: x.order), len(hunks))


def _text_or_none(disk: bytes | None) -> str | None:
    """磁盘上的字节当 UTF-8 文字（文本才能打补丁）；不存在或不是 UTF-8 文本 → None。"""
    if disk is None or b"\0" in disk[:4096]:
        return None
    try:
        return disk.decode("utf-8")
    except UnicodeDecodeError:
        return None


def commit(p: Plan) -> list[Entry]:
    """写盘：先写所有新内容（建上级目录），再删；任何 OSError → 已动过的全部还原再抛 PatchError。返回真的变了的项。"""
    done: list[Entry] = []
    made_dirs: list[Path] = []
    changed = [e for e in p.entries if e.changed]
    try:
        for e in sorted(changed, key=lambda x: x.after is None):
            if e.after is None:
                e.p.unlink()
            else:
                parent = e.p.parent
                missing = []
                while not parent.exists():
                    missing.append(parent)
                    parent = parent.parent
                e.p.parent.mkdir(parents=True, exist_ok=True)
                made_dirs.extend(reversed(missing))
                e.p.write_bytes(e.after.encode("utf-8"))
            done.append(e)
    except OSError as err:
        for e in reversed(done):
            try:
                if e.disk is None:
                    e.p.unlink(missing_ok=True)
                else:
                    e.p.write_bytes(e.disk)
            except OSError:
                pass
        for d in reversed(made_dirs):
            try:
                d.rmdir()
            except OSError:
                pass
        raise PatchError(f"写盘失败（{type(err).__name__}: {err}），已把这份补丁动过的文件全部还原，什么都没改。",
                         "写盘失败") from err
    return changed


# ---------------------------------------------------------------- run_command 里的 apply_patch heredoc（invocation.rs）

_HEREDOC = re.compile(
    r"\A\s*(?:cd\s+(?P<cd>'[^']*'|\"[^\"$`\\]*\"|[^\s;&|<>'\"$`\\]+)\s*&&\s*)?"
    r"(?:apply_patch|applypatch)\s*<<-?\s*(?P<q>['\"]?)(?P<tag>[A-Za-z_][A-Za-z0-9_]*)(?P=q)[ \t]*\n"
    r"(?P<body>.*?)\n(?P=tag)[ \t]*\n?\s*\Z", re.S)


def from_command(command: str) -> tuple[str, str] | None:
    """整条命令就是 `apply_patch <<'EOF' … EOF`（可带 `cd 子目录 && `）→ (补丁文本, 子目录 "" 或相对路径)；否则 None。
    前后再接别的命令（echo; … && make）都不认，交给沙盒照常执行（Codex 同样只认这两种整句形式）。"""
    m = _HEREDOC.match(command)
    if not m:
        return None
    cd = (m.group("cd") or "").strip("'\"")
    return m.group("body"), cd


def summary(entries: list[Entry]) -> str:
    """“新建 a.py，修改 b.py，删除 c.txt，改名 d.md → e.md”（给模型的结果第一句）。"""
    parts = []
    for e in entries:
        if e.moved_away or not e.changed and e.origin is None:
            continue
        if e.origin is not None:
            parts.append(f"改名 {e.origin.rel} → {e.rel}")
        elif e.after is None:
            parts.append(f"删除 {e.rel}")
        elif e.disk is None:
            parts.append(f"新建 {e.rel}")
        else:
            parts.append(f"修改 {e.rel}")
    return "，".join(parts)
