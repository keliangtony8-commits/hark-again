"""工作区搜索的唯一规则：glob（按文件名找文件）+ grep（按内容找行）。工具壳在 agent/builtin/workspace.py。

为什么不让模型 run_command grep：要起沙盒（睡着了还得唤醒）、输出没上限、会翻进 .home 里成千上万个 pip 包、
时间线上只是一句“运行命令”。这里直接在后端读工作区目录（和 read_file / write_file 一样，零沙盒成本、沙盒挂了也能搜）。

参考（docs/core-research.md 第 12 项有逐文件对比）：
- deepseek-harness tool-fs-search：glob 按修改时间新→旧排、grep 结果按文件分组、内联条数有上限、超出部分整份落盘
  （formatted result spill）而不是截断丢掉、include 只收一个正向 glob（{a,b} 可以，逗号列表/!取反不行）、
  显式指定 path 进 VCS 目录时仍要排除 → 我们：隐藏目录默认跳过，但 path 明确指进去（如 .jobs/<id>）就搜；
- Gemini CLI grep.ts / ripGrep.ts / glob.ts：总条数上限 100、超时提示“缩小 dir_path / include”、
  case_sensitive / fixed_strings / context 参数、默认忽略 node_modules 这类依赖目录、单文件 path 也行；
- Codex CLI：没有专门的搜索工具，靠 shell 跑 rg，只在显示层把 rg/grep 命令归类成“搜索” → 我们取专门工具（省 token、可控）。
结论（三家排名见 core-research 12）：deepseek-harness 最稳（固定 argv、--no-config、错误分类、格式化结果落盘）当底子，
嫁接 Gemini 的参数集与“rg → 纯代码”回退链。grep 两段式：后端装了 rg（Dockerfile 已加）就先用 rg -l 圈出含命中的文件
（argv 规矩移植自 deepseek-harness search-core.ts / grep.ts：--no-config 防 rg.conf 注入 --pre、pattern 走 --regexp=、
--glob= 排除目录、路径放在 -- 之后），再用 Python 在这些文件里出行号/上下文——两条路格式完全一致；
没有 rg、rg 不认这个正则（比如 Python 的环视）、rg 出错/超时 → 整个走 Python。
文件数 / 单文件大小 / 总耗时三道上限兜住，到顶就如实说“没搜完”。
"""
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import spill
from .storage import HIDDEN_DIRS, project_dir, safe_join

# 依赖/缓存目录：默认不进（又大又不是用户的东西）；path 明确指进去时照搜
HEAVY_DIRS = frozenset({"node_modules", "__pycache__", ".venv", "venv", "site-packages", ".mypy_cache",
                        ".pytest_cache", ".ruff_cache", ".next", ".cache", ".tox", ".gradle", ".dart_tool"})
GLOB_MAX = 100        # glob 内联最多列多少个路径（deepseek-harness 同值）
GREP_MAX = 100        # grep 内联最多给多少条命中（Gemini CLI DEFAULT_TOTAL_MAX_MATCHES 同值）
INLINE_CHARS = 12000  # 内联结果的字符预算（低于 loop 的 tool_result_max，免得被二次截断）
LINE_MAX = 240        # 一行命中最多显示多少字符
MATCH_LINE_MAX = 4000  # 参与匹配的单行长度上限（压缩过的 js 一行几 MB；也防正则回溯卡死）
CONTEXT_MAX = 5
FILE_MAX_BYTES = 5 * 1024 * 1024  # 单文件超过就跳过（计数告诉模型）
FILES_MAX = 20000     # 最多看这么多个文件
TIME_BUDGET = 8.0     # 秒；到点就停，结果标“没搜完”


class SearchError(Exception):
    """参数不对（正则写错、include 是列表、目录不存在）：原样告诉模型，时间线记一句短原因。"""
    def __init__(self, message: str, short: str):
        super().__init__(message)
        self.short = short


# ---------- glob → 正则 ----------
def _translate(pattern: str) -> str:
    """glob 语法：** 跨目录、* ? [..] 不跨 /、{a,b} 二选一。"""
    out, i, n, depth = [], 0, len(pattern), 0
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern[i:i + 2] == "**":
                i += 2
                if i < n and pattern[i] == "/":
                    out.append("(?:.*/)?")
                    i += 1
                else:
                    out.append(".*")
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = pattern.find("]", i + 2 if pattern[i + 1:i + 2] in ("!", "^") else i + 1)
            if j < 0:
                out.append(re.escape(c))
            else:
                body = pattern[i + 1:j]
                if body[:1] in ("!", "^"):
                    body = "^" + body[1:]
                out.append("[" + body.replace("\\", "\\\\") + "]")
                i = j
        elif c == "{":
            depth += 1
            out.append("(?:")
        elif c == "}" and depth:
            depth -= 1
            out.append(")")
        elif c == "," and depth:
            out.append("|")
        else:
            out.append(re.escape(c))
        i += 1
    if depth:
        raise SearchError(f"glob「{pattern}」的大括号没配对。", "glob 写错了")
    return "".join(out)


def matcher(pattern: str):
    """返回 rel_path → bool。没有 / 的模式（*.py）匹配任意深度的文件名，和 rg --glob / .gitignore 一样；
    有 / 的按相对搜索根的整条路径匹配（src/**/*.ts）。"""
    p = pattern.strip()
    while p.startswith("./"):
        p = p[2:]
    p = p.lstrip("/")
    if not p:
        raise SearchError("glob 不能为空。", "glob 为空")
    rx = re.compile(_translate(p) + r"\Z", re.S)
    if "/" in p:
        return lambda rel: rx.match(rel) is not None
    return lambda rel: rx.match(rel.rsplit("/", 1)[-1]) is not None


def check_include(include: str) -> None:
    """include 只收一个正向 glob（deepseek-harness 同规则）：{a,b} 可以，逗号列表、!取反不行。"""
    if include.startswith("!"):
        raise SearchError("include 只能是一个“要包含”的 glob，不支持 ! 取反。", "include 写错了")
    depth = 0
    for ch in include:
        depth += ch == "{"
        depth -= ch == "}" and depth > 0
        if ch == "," and depth == 0:
            raise SearchError("include 只能是一个 glob；要多种后缀写成 *.{py,md}，不要用逗号列表。", "include 写错了")


# ---------- 遍历 ----------
@dataclass
class Walk:
    root: Path                 # 工作区根
    base: Path                 # 搜索起点（目录或单个文件）
    files: list[Path] = field(default_factory=list)
    seen: int = 0
    capped: bool = False       # 文件数 / 时间到顶，没走完
    started: float = field(default_factory=time.monotonic)

    def rel(self, p: Path) -> str:
        return p.relative_to(self.root).as_posix()

    def out_of_time(self) -> bool:
        return time.monotonic() - self.started > TIME_BUDGET


def resolve(ws: str, path: str) -> tuple[Path, Path]:
    root = project_dir(ws).resolve()
    try:
        base = safe_join(root, path or "")
    except ValueError:
        raise SearchError(f"路径「{path}」不在工作区里。", "路径越界") from None
    if not base.exists():
        raise SearchError(f"「{path}」不存在。先用 list_files 或 glob 看看有哪些目录。", "路径不存在")
    return root, base


def walk(ws: str, path: str = "") -> Walk:
    """搜索起点下的所有普通文件（不跟符号链接，不出工作区）。隐藏目录（.git/.jobs/.spill/.home）和依赖目录默认跳过，
    但起点本身已经在它们里面时照常走——模型明确说了要搜那里。"""
    root, base = resolve(ws, path)
    w = Walk(root, base)
    if base.is_file():
        w.files.append(base)
        w.seen = 1
        return w
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in HIDDEN_DIRS and d not in HEAVY_DIRS)
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if p.is_symlink() or not p.is_file():
                continue
            w.seen += 1
            w.files.append(p)
            if w.seen >= FILES_MAX:
                w.capped = True
                return w
        if w.out_of_time():
            w.capped = True
            return w
    return w


def _ago(seconds: float) -> str:
    s = max(0, int(seconds))
    if s < 60:
        return "刚刚"
    if s < 3600:
        return f"{s // 60} 分钟前"
    if s < 86400:
        return f"{s // 3600} 小时前"
    return f"{s // 86400} 天前"


def _size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def _where(path: str) -> str:
    return f"「{path}」里" if path else "工作区里"


def _finish(ws: str, name: str, head: str, lines: list[str], shown: int, total: int, tail: list[str],
            inline: list[str] | None = None, basis: str = "") -> str:
    """内联前 shown 行（受条数 + 字符预算），其余整份落盘给 read_file 分段读（deepseek-harness 的 formatted spill）。
    inline：调用方已挑好的内联页（glob 超上限时的顶层抽样）；落盘的仍是完整 lines。basis：说明内联页怎么挑的。"""
    body, used = [], len(head)
    for line in (inline if inline is not None else lines[:shown]):
        if used + len(line) + 1 > INLINE_CHARS:
            break
        body.append(line)
        used += len(line) + 1
    notes = list(tail)
    if len(body) < len(lines):
        full = "\n".join([head, *lines, *tail])
        what = f"列了 {len(body)} 行（共 {len(lines)} 行，{total} 条）{basis}" if basis else \
            f"只列了前 {len(body)} 行（共 {len(lines)} 行，{total} 条）"
        try:
            where = spill.save(ws, name, full)
            notes.append(f"{what}；完整结果存在 {where}，用 read_file 分段看，或者缩小 path / glob / pattern 重新搜。")
        except OSError:
            notes.append(f"{what}；缩小 path / glob / pattern 重新搜看其余的。")
    return "\n".join([head, *body, *notes])


# ---------- 超上限时的顶层抽样 ----------
# Ported from deepseek-harness/packages/fs/tool-fs-search/src/glob.ts (MIT), modified:
# sampleAcrossTopLevel + topLevelSegment + relativeToSearchRoot；路径分隔符固定 "/"（工作区在 Linux 上），
# 返回 (items, shown, total)。为什么：超上限时只给“最新的前 100 个”，一个刚 pip/npm 装完的大目录会把整页占满，
# 模型看不到别的目录里还有匹配；按顶层目录轮流取，每个顶层目录先各拿一个名额，再轮第二圈。
def _relative_to_root(path: str, root: str) -> str:
    if root == ".":
        return path[2:] if path.startswith("./") else path
    trimmed = root.rstrip("/")
    if not trimmed:
        return path.lstrip("/")
    if path == trimmed:
        return ""
    return path[len(trimmed) + 1:] if path.startswith(trimmed + "/") else path


def _top_level(path: str) -> str:
    trimmed = path.lstrip("/")
    cut = trimmed.find("/")
    return trimmed if cut == -1 else trimmed[:cut]


def sample_across_top_level(paths: list[str], max_items: int, root: str = ".") -> tuple[list[str], int, int]:
    """paths 已按新→旧排好；返回 (内联页 按顶层分组, 内联页覆盖的顶层数, 全部顶层数)。
    组顺序和组内顺序都沿用 paths，所以扁平结果（每个路径自成一组）就是原来的“最新的前 N 个”。"""
    groups: dict[str, list[str]] = {}
    for p in paths:
        groups.setdefault(_top_level(_relative_to_root(p, root)), []).append(p)
    taken: dict[str, list[str]] = {}
    active = [(key, 0) for key in groups]
    count = 0
    while active and count < max_items:
        nxt = []
        for key, index in active:
            if count >= max_items:
                break
            count += 1
            taken.setdefault(key, []).append(groups[key][index])
            if index + 1 < len(groups[key]):
                nxt.append((key, index + 1))
        active = nxt
    return [p for items in taken.values() for p in items], len(taken), len(groups)


# ---------- glob ----------
def glob(ws: str, pattern: str, path: str = "") -> str:
    match = matcher(pattern)
    w = walk(ws, path)
    base_rel = w.rel(w.base) if w.base != w.root else ""
    now = time.time()
    hits = []
    for p in w.files:
        rel = w.rel(p)
        if w.base.is_file():
            sub = p.name
        else:
            sub = rel[len(base_rel) + 1:] if base_rel else rel
        if match(sub):
            try:
                st = p.stat()
            except OSError:
                continue
            hits.append((st.st_mtime, rel, st.st_size))
    hits.sort(key=lambda h: (-h[0], h[1]))  # 新改的在前（两个参考都这样：刚动过的文件最可能是要找的）
    capped = ["（文件太多 / 搜太久，没走完；结果可能不全，缩小 path 再搜）"] if w.capped else []
    if not hits:
        return f"{_where(path)}没有文件名匹配 {pattern} 的文件（看了 {w.seen} 个文件，隐藏目录和 node_modules 这类依赖目录默认不搜）。" \
            + ("".join(capped))
    head = f"{_where(path)}找到 {len(hits)} 个匹配 {pattern} 的文件（新改的在前）："
    line_of = {rel: f"{rel}  ({_size(size)}, {_ago(now - mtime)})" for mtime, rel, size in hits}
    lines = list(line_of.values())
    if len(hits) <= GLOB_MAX:
        return _finish(ws, "glob", head, lines, GLOB_MAX, len(hits), capped)
    items, shown, groups = sample_across_top_level([rel for _, rel, _ in hits], GLOB_MAX, base_rel or ".")
    if groups == len(hits):  # 扁平结果：抽样就是“最新的前 N 个”，照旧说法
        return _finish(ws, "glob", head, lines, GLOB_MAX, len(hits), capped)
    basis = f"，按顶层目录轮流抽样（覆盖 {shown}/{groups} 个顶层目录），不是只取最新的" + \
        ("；想看某个目录就把 path 指过去" if shown < groups else "")
    return _finish(ws, "glob", head, lines, GLOB_MAX, len(hits), capped, [line_of[r] for r in items], basis)


# ---------- rg 预筛（可选加速） ----------
def _rg_bin() -> str | None:
    return shutil.which("rg")


def rg_candidates(w: Walk, pattern: str, ignore_case: bool, fixed: bool) -> list[Path] | None:
    """rg -l 圈出含命中的文件（相对排序后的绝对路径）；None = 用不了 rg，调用方走纯 Python。
    只在搜索起点是目录时用（单文件直接 Python）。排除规则与 walk() 一致：起点以下任意深度的隐藏/依赖目录。"""
    rg = _rg_bin()
    if rg is None or not w.base.is_dir():
        return None
    argv = [rg, "--no-config", "--files-with-matches", "--null", "--no-messages", "--hidden", "--no-ignore",
            f"--max-filesize={FILE_MAX_BYTES}", f"--regexp={pattern}"]
    if ignore_case:
        argv.append("--ignore-case")
    if fixed:
        argv.append("--fixed-strings")
    for name in sorted(HIDDEN_DIRS | HEAVY_DIRS):
        argv += [f"--glob=!**/{name}", f"--glob=!**/{name}/**"]
    argv += ["--", "."]
    try:
        r = subprocess.run(argv, cwd=w.base, capture_output=True, timeout=TIME_BUDGET)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode == 1:
        return []          # 正常结束，没有命中
    if r.returncode != 0:
        return None        # 正则 rg 不认 / 其他错误 → Python 兜底（Python 的报错更好懂）
    names = sorted(n for n in r.stdout.decode("utf-8", "surrogateescape").split("\0") if n)
    return [(w.base / n.removeprefix("./")) for n in names]


# ---------- grep ----------
@dataclass
class Hit:
    rel: str
    no: int
    text: str
    context: list[tuple[int, str]] = field(default_factory=list)


def _clip(line: str) -> str:
    line = line.rstrip("\r\n")
    return line if len(line) <= LINE_MAX else line[:LINE_MAX - 1] + "…"


def compile_pattern(pattern: str, ignore_case: bool, fixed: bool) -> re.Pattern:
    if not pattern:
        raise SearchError("pattern 不能为空。", "pattern 为空")
    try:
        return re.compile(re.escape(pattern) if fixed else pattern, re.I if ignore_case else 0)
    except re.error as e:
        raise SearchError(f"正则「{pattern}」写错了：{e}。只想按字面找就设 fixed=true。", "正则写错了") from None


def _read_text(p: Path) -> str | None:
    try:
        raw = p.read_bytes()
    except OSError:
        return None
    if b"\0" in raw[:4096]:
        return None  # 二进制
    return raw.decode("utf-8", errors="replace")


def grep(ws: str, pattern: str, path: str = "", include: str = "", ignore_case: bool = False,
         fixed: bool = False, context: int = 0) -> str:
    rx = compile_pattern(pattern, ignore_case, fixed)
    include = include.strip()
    if include:
        check_include(include)
    inc = matcher(include) if include else None
    ctx_n = max(0, min(int(context or 0), CONTEXT_MAX))
    root, base = resolve(ws, path)
    pre = rg_candidates(Walk(root, base), pattern, ignore_case, fixed) if base.is_dir() else None
    if pre is not None:
        w = Walk(root, base, files=pre, seen=len(pre))
    else:
        w = walk(ws, path)
    hits: list[Hit] = []
    big = binary = searched = 0
    capped = w.capped
    for p in w.files:
        rel = w.rel(p)
        if inc is not None and not inc(rel):
            continue
        if w.out_of_time():
            capped = True
            break
        try:
            if p.stat().st_size > FILE_MAX_BYTES:
                big += 1
                continue
        except OSError:
            continue
        text = _read_text(p)
        if text is None:
            binary += 1
            continue
        searched += 1
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if rx.search(line[:MATCH_LINE_MAX]):
                h = Hit(rel, i + 1, _clip(line))
                if ctx_n:
                    lo, hi = max(0, i - ctx_n), min(len(lines), i + ctx_n + 1)
                    h.context = [(j + 1, _clip(lines[j])) for j in range(lo, hi) if j != i]
                hits.append(h)
        if len(hits) > GREP_MAX * 20:  # 远超内联上限：再多也只是落盘，停手省时间
            capped = True
            break
    tail = []
    if big:
        tail.append(f"（跳过了 {big} 个超过 {FILE_MAX_BYTES // 1024 // 1024} MB 的文件）")
    if capped:
        tail.append("（文件太多 / 命中太多 / 搜太久，没搜完；结果可能不全，缩小 path 或加 include 再搜）")
    if not hits:
        how = "（忽略大小写）" if ignore_case else ""
        scope = "整个目录都搜过了" if pre is not None else f"搜了 {searched} 个文本文件"
        return f"{_where(path)}没有找到 {pattern}{how}（{scope}" \
            + (f"，跳过 {binary} 个二进制文件" if binary else "") \
            + "；隐藏目录和 node_modules 这类依赖目录默认不搜）。" + "".join(tail)
    files = len({h.rel for h in hits})
    head = f"{_where(path)}找到 {len(hits)} 处 {pattern}，在 {files} 个文件里（路径:行号）："
    lines: list[str] = []
    shown = 0  # 内联到第几行：恰好放完前 GREP_MAX 条命中
    last = None
    for k, h in enumerate(hits):
        if h.rel != last:
            lines.append(f"{h.rel}")
            last = h.rel
        if h.context:
            near = {n: t for n, t in h.context}
            near[h.no] = h.text
            for n in sorted(near):
                mark = ":" if n == h.no else "-"
                lines.append(f"  {n}{mark} {near[n]}")
            lines.append("  --")
        else:
            lines.append(f"  {h.no}: {h.text}")
        if k < GREP_MAX:
            shown = len(lines)
    return _finish(ws, "grep", head, lines, shown, len(hits), tail)
