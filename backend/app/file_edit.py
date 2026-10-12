"""精确改文件（edit_file）与文件改动摘要（diff）的唯一规则。

对标：Hark / Claude 式 edit_file（old_string → new_string，必须唯一，replace_all 全换）。
参考了三份开源实现取长补短（对比写在 docs/core-research.md 第 11 项）：
- Gemini CLI tools/edit.ts：先精确匹配，再“逐行去首尾空白”的宽松匹配并按原缩进重排；CRLF 文件先归一成 \\n 再匹配、
  写回时恢复原换行；三种失败（没找到 / 不唯一 / 新旧相同）各给模型一句能照着改的话。
- Codex apply-patch seek_sequence.rs：宽松匹配分档（原样 → 去行尾空白 → 去首尾空白 → Unicode 标点归一），越往后越宽；
  宽松档只在“恰好一处”时才用，免得改错地方。
- deepseek-harness str_replace_editor：不唯一就不改，并提示“多带几行上下文”；我们再报出每处在第几行，模型一步就能补准。
不做 Gemini 的“让模型修补 old_string”（多一次模型调用，费 token）。

改动摘要 change = {"path", "added", "removed", "diff"[, "created"][, "hidden"]}：随活动时间线那一步落库（activity.py），
两端在时间线里显示 “+3 −1”，点开看 diff。diff 是 unified diff 去掉 ---/+++ 头，最多 DIFF_LINES 行 / DIFF_CHARS 字；
像密钥的文件（.env、*.pem、名字带 secret/token…）diff 为空 + hidden，其余文件里 “api_key = …” 这类行值打码。
"""
import difflib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

DIFF_LINES = 120
DIFF_CHARS = 6000
CONTEXT = 2  # diff 每处改动前后带几行上下文

# 时间线会跟着消息落库、换设备回看：像密钥文件的不带 diff（只给 +N −M），其他文件里 “key = 值” 这类行把值打码。
SECRET_FILE = re.compile(r"(^\.env(\..*)?$|\.(pem|key|p12|pfx|keystore|jks)$|^id_(rsa|ed25519|ecdsa)|secret|credential|token|password)", re.I)
SECRET_LINE = re.compile(r"((?:api[_-]?key|secret|token|passw(?:or)?d|pwd|private[_-]?key|access[_-]?key)[\w-]*[\"']?\s*[:=]\s*).+", re.I)
MASK = "••••"


class EditError(Exception):
    """没改成：消息直接给模型（说清怎么补救）。short 给时间线那一步当原因。"""

    def __init__(self, message: str, short: str):
        super().__init__(message)
        self.short = short


@dataclass
class Edit:
    text: str        # 改完的全文（换行已恢复成文件原来的）
    count: int       # 换了几处
    loose: bool      # 是否靠宽松匹配（空白/缩进不同）找到的


def _lines_at(text: str, needle: str) -> list[int]:
    """needle 每次出现所在的行号（1 起）。"""
    out, i = [], text.find(needle)
    while i >= 0:
        out.append(text.count("\n", 0, i) + 1)
        i = text.find(needle, i + max(1, len(needle)))
    return out


def _where(lines: list[int]) -> str:
    shown = "、".join(str(n) for n in lines[:8])
    return f"第 {shown} 行" + (f" 等 {len(lines)} 处" if len(lines) > 8 else "")


# Ported from openai/codex codex-rs/apply-patch/src/seek_sequence.rs (Apache-2.0), modified:
# 最宽的一档——把常见 Unicode 标点归一成 ASCII 再比（模型常把文件里的 “—” ‘’ “” 不换行空格写成 - ' " 空格）。
_PUNCT = str.maketrans({
    **dict.fromkeys("\u2010\u2011\u2012\u2013\u2014\u2015\u2212", "-"),
    **dict.fromkeys("\u2018\u2019\u201A\u201B", "'"),
    **dict.fromkeys("\u201C\u201D\u201E\u201F", '"'),
    **dict.fromkeys("\u00A0\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200A\u202F\u205F\u3000", " "),
})


def normalise(s: str) -> str:
    """Codex seek_sequence normalise：先 trim 再换标点。"""
    return s.strip().translate(_PUNCT)


def seek_sequence(lines: list[str], pattern: list[str], start: int = 0, eof: bool = False) -> int | None:
    """Codex seek_sequence 原样：从 start 起找第一处（精确 → 去行尾空白 → 去首尾空白 → 标点归一）。
    eof=True 先从文件结尾那一窗找。空 pattern → start；pattern 比文件长 → None。只用于移植的单测对照。"""
    if not pattern:
        return start
    if len(pattern) > len(lines):
        return None
    begin = max(len(lines) - len(pattern), start) if eof else start
    for norm in (None, str.rstrip, str.strip, normalise):
        for i in range(begin, len(lines) - len(pattern) + 1):
            if all((a if norm is None else norm(a)) == (b if norm is None else norm(b))
                   for a, b in zip(lines[i:i + len(pattern)], pattern)):
                return i
    return None


def _loose_windows(lines: list[str], pattern: list[str]) -> list[int]:
    """Codex seek_sequence 的宽松分档（去行尾空白 → 去首尾空白 → 标点归一），但要的是所有命中：
    返回第一档有结果时的全部起始行（0 起），由调用方判唯一（Codex 只取第一处，会悄悄改错地方）。"""
    n = len(pattern)
    for norm in (str.rstrip, str.strip, normalise):
        pat = [norm(p) for p in pattern]
        hits = [i for i in range(len(lines) - n + 1) if [norm(x) for x in lines[i:i + n]] == pat]
        if hits:
            return hits
    return []


def _reindent(new_lines: list[str], old_first: str, pat_first: str) -> list[str]:
    """宽松命中时按文件里那段的缩进重排新内容（Gemini applyIndentation 的思路：缩进差补到每一行）。"""
    have = old_first[: len(old_first) - len(old_first.lstrip())]
    gave = pat_first[: len(pat_first) - len(pat_first.lstrip())]
    if have == gave:
        return new_lines
    out = []
    for ln in new_lines:
        if ln.strip() and ln.startswith(gave):
            ln = have + ln[len(gave):]
        elif ln.strip() and not gave:
            ln = have + ln
        out.append(ln)
    return out


def apply(text: str, old: str, new: str, replace_all: bool = False) -> Edit:
    if old == "":
        raise EditError("old_string 不能为空：要新建或整篇重写用 write_file。", "没给要换的原文")
    crlf = "\r\n" in text
    body = text.replace("\r\n", "\n")
    old_n, new_n = old.replace("\r\n", "\n"), new.replace("\r\n", "\n")
    if old_n == new_n:
        raise EditError("old_string 和 new_string 一样，没有要改的。", "新旧内容相同")

    count, loose = body.count(old_n), False
    if count > 1 and not replace_all:
        raise EditError(f"old_string 在文件里出现了 {count} 处（{_where(_lines_at(body, old_n))}），没有改。"
                        "多带几行上下文让它只匹配一处；确实要全部替换就设 replace_all=true。", f"匹配到 {count} 处，不唯一")
    if count:
        out = body.replace(old_n, new_n) if replace_all else body.replace(old_n, new_n, 1)
    else:
        lines, pattern = body.split("\n"), old_n.split("\n")
        while len(pattern) > 1 and pattern[-1].strip() == "":
            pattern.pop()  # 结尾多带的空行不算
        hits = _loose_windows(lines, pattern)
        # 宽松命中的窗口互相重叠时只取不重叠的
        picked: list[int] = []
        for h in hits:
            if not picked or h >= picked[-1] + len(pattern):
                picked.append(h)
        if not picked:
            raise EditError("没在文件里找到 old_string（连空白/缩进、中英文标点放宽后也没有）。文件可能已经变了，"
                            "先用 read_file 看一下要改的那几行，再用一字不差的原文重试。", "没找到要换的原文")
        if len(picked) > 1 and not replace_all:
            raise EditError(f"old_string 忽略空白后在文件里匹配到 {len(picked)} 处（{_where([p + 1 for p in picked])}），没有改。"
                            "多带几行上下文让它只匹配一处；确实要全部替换就设 replace_all=true。", f"匹配到 {len(picked)} 处，不唯一")
        new_lines = new_n.split("\n")
        if new_lines and new_lines[-1] == "" and len(new_lines) > 1 and old_n.endswith("\n"):
            new_lines.pop()
        for h in reversed(picked):
            repl = _reindent(new_lines, lines[h], pattern[0]) if new_n else []
            lines[h:h + len(pattern)] = repl
        out, count, loose = "\n".join(lines), len(picked), True
    if crlf:
        out = out.replace("\n", "\r\n")
    return Edit(out, count, loose)


def change(path: str, before: str | None, after: str) -> dict:
    """一次写入的改动摘要。before=None 表示新建文件。"""
    a = [] if before is None else before.replace("\r\n", "\n").splitlines()
    b = after.replace("\r\n", "\n").splitlines()
    added = removed = 0
    rows: list[str] = []
    for ln in difflib.unified_diff(a, b, lineterm="", n=CONTEXT):
        if ln.startswith(("---", "+++")):
            continue
        if ln.startswith("+"):
            added += 1
        elif ln.startswith("-"):
            removed += 1
        rows.append(ln)
    diff, size, cut = [], 0, False
    for ln in rows:
        if len(diff) >= DIFF_LINES or size + len(ln) > DIFF_CHARS:
            cut = True
            break
        diff.append(ln)
        size += len(ln) + 1
    text = "\n".join(SECRET_LINE.sub(lambda m: m.group(1) + MASK, ln) for ln in diff)
    text += f"\n… 还有 {len(rows) - len(diff)} 行改动没显示" if cut else ""
    out = {"path": path, "added": added, "removed": removed, "diff": text}
    if SECRET_FILE.search(PurePosixPath(path).name):
        out["diff"], out["hidden"] = "", True
    if before is None:
        out["created"] = True
    return out


def stat(c: dict) -> str:
    """“+3 −1”：给模型的结果里也带一句。"""
    return f"+{c['added']} −{c['removed']}"
