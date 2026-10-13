# Copyright 2025 Google LLC
# SPDX-License-Identifier: Apache-2.0
#
# Ported from google-gemini/gemini-cli packages/core/src/tools/omissionPlaceholderDetector.ts (Apache-2.0), modified:
# - 注释外壳不止 //：# -- ; * /* */ <!-- --> {/* */}，括号多了 [] （） 【】；省略号认 ... 和 … / ……；
# - 英文短语从固定 7 个扩成「rest of / unchanged|existing|remaining|previous|other|original + 名词」+ 尾巴
#   （unchanged / remains the same / omitted …）；“... existing code ...” 这种前后都带省略号的也算；
# - 加中文占位（“// 其余代码不变”“（此处省略……）”）；散文文件（.md/.txt…）更严：只认带省略号的英文、
#   以及“其余/原有…不变”一类，不认光秃秃的“此处省略”（小说里的“此处省略一万字”是正文）；
# - 判定改成“新出现的占位”：之前的文件里本来就有同样的行（同样多次）不算，write_file / edit_file / apply_patch 共用。
"""写文件前查“省略占位行”的唯一规则（core-gaps #2）。

模型整篇重写或替换一段时偷懒写成 “// rest of code ...” “# 其余代码不变”，写进去就把原来的代码换成了这行字。
只认“整行就是占位”：嵌在代码里、字符串里、行尾注释里的都不算。"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

LINE_MAX = 200          # 比这长的行不可能是占位，直接跳过（大文件也快）
SHOWN = 3               # 报错时最多列几行

PROSE_SUFFIXES = {".md", ".markdown", ".txt", ".rst", ".adoc", ".org", ".tex"}

_ELLIPSIS = re.compile(r"(?:\.{3,}|…+)")
_WRAPS = (("/*", "*/"), ("<!--", "-->"), ("{/*", "*/}"), ("(", ")"), ("[", "]"), ("（", "）"), ("【", "】"))
_LEADS = ("//", "--", "#", ";", "*")

NOUNS = {
    "code", "method", "methods", "file", "class", "classes", "function", "functions", "implementation",
    "content", "contents", "lines", "config", "configuration", "styles", "css", "html", "markup",
    "component", "components", "imports", "tests", "logic", "body", "text", "section", "sections",
    "fields", "properties", "props", "document", "page", "script", "steps", "rules", "items", "cases", "query", "queries", "data", "routes", "handlers",
}
_EN_HEAD = re.compile(r"^(?:rest of(?: (\w+))?|(?:unchanged|existing|remaining|previous|other|original|same) (\w+)"
                      r"|keep existing (\w+)|same as before)$")
_EN_TAILS = ("remains unchanged", "remain unchanged", "stays unchanged", "stay unchanged", "is unchanged",
             "are unchanged", "remains the same", "remain the same", "stays the same", "stay the same",
             "same as before", "as before", "unchanged", "omitted")
_EN_SOFT = ("goes here", "here")   # 只剥掉，不能单凭它认定（“# other methods here” 可能是正常的分节注释）

_CN_LEAD = r"(?:此处|这里|以下|以上|下面|上面|中间|后面|前面|后续|下同)?"
_CN_WHO = r"(?:其余|其他|其它|剩余|剩下|原有|原来|之前|已有|未改动|没改动|没改|未修改|未变)"
_CN_WHAT = r"(?:代码|内容|方法|函数|部分|实现|逻辑|字段|配置|样式|行|段落|章节|文件)"
_CN_KEEP = r"(?:保持|均|都|一律|仍|依旧|仍然)?(?:不变|未变|没变|不动|照旧|同上|同前|与原文相同|和原来一样|与之前相同|与原来相同)"
_CN_OMIT = r"(?:已)?(?:省略|略去|从略|略)"
_CN = re.compile(rf"^(?P<lead>{_CN_LEAD})(?P<who>{_CN_WHO})?的?(?P<what>{_CN_WHAT})?(?P<keep>{_CN_KEEP})?(?P<omit>{_CN_OMIT})?$")


@dataclass(frozen=True)
class Hit:
    line: int       # 1 起
    text: str       # 原行（去掉首尾空白，最多 80 字）
    token: str      # 规范化后的占位，拿来比“之前有没有”


def _unwrap(s: str) -> tuple[str, bool]:
    """去掉注释外壳 / 括号；返回 (里面的字, 是不是注释或括号行)。"""
    shell = False
    for _ in range(3):
        s = s.strip()
        hit = False
        for a, b in _WRAPS:
            if s.startswith(a) and s.endswith(b) and len(s) >= len(a) + len(b):
                s, hit = s[len(a):len(s) - len(b)], True
                break
        if not hit:
            for a in _LEADS:
                if s.startswith(a):
                    s, hit = s.lstrip(a[0]) if a in ("#", ";", "*") else s[len(a):], True
                    break
        if not hit:
            break
        shell = True
    return s.strip(), shell


def _ellipsis(s: str) -> tuple[str, bool]:
    """省略号只许在开头 / 结尾（Gemini：后面只能跟点）；中间夹着的不算占位。"""
    t = s.strip()
    found = False
    m = _ELLIPSIS.match(t)
    if m:
        t, found = t[m.end():].strip(), True
    m = re.search(rf"{_ELLIPSIS.pattern}$", t)
    if m:
        t, found = t[:m.start()].strip(), True
    if _ELLIPSIS.search(t):        # 省略号夹在中间：“rest ... of code”、“loading...done” 都不是占位
        return "", False
    return t, found


def _english(core: str, dots: bool, prose: bool) -> str | None:
    s = re.sub(r"\s+", " ", core.lower()).strip(" :,.")
    s = re.sub(r"\bthe ", "", s)
    s = re.sub(r"^(?:\.\.\.|…)\s*", "", s)
    tail = False
    for t in _EN_TAILS:
        if s.endswith(" " + t):
            s, tail = s[:-len(t) - 1].strip(" ,"), True
            break
    for t in _EN_SOFT:
        if s.endswith(" " + t):
            s = s[:-len(t) - 1].strip(" ,")
            break
    if not (dots or (tail and not prose)):
        return None
    m = _EN_HEAD.match(s)
    if not m:
        return None
    noun = next((g for g in m.groups() if g), None)
    return s if noun is None or noun in NOUNS else None


def _chinese(core: str, dots: bool, prose: bool) -> str | None:
    s = re.sub(r"[\s，,。：:、]+", "", core)
    if not s or not re.search(r"[\u4e00-\u9fff]", s):
        return None
    m = _CN.match(s)
    if not m:
        return None
    lead, who, what, keep, omit = (m.group(k) for k in ("lead", "who", "what", "keep", "omit"))
    if not (lead or who or what):      # 光一个“同上”“保持不变”“省略”可能是正常注释
        return None
    if keep:
        return s
    if omit:
        return s if (who or what) or not prose else None   # 散文里“此处省略……”是正文修辞
    return s if dots and who else None


def _placeholder(raw: str, prose: bool) -> str | None:
    line = raw.strip()
    if not line or len(line) > LINE_MAX:
        return None
    inner, shell = _unwrap(line)
    core, dots = _ellipsis(inner)
    if not core:
        return None
    en = _english(core, dots, prose)
    if en is not None:
        return f"{en} ..."
    if not (shell or dots):         # 中文占位要么在注释 / 括号里，要么带省略号；裸的一行字是正文
        return None
    cn = _chinese(core, dots, prose)
    return f"{cn} ..." if cn else None


def is_prose(path: str) -> bool:
    p = path.lower()
    return any(p.endswith(s) for s in PROSE_SUFFIXES)


def detect(text: str, path: str = "") -> list[Hit]:
    """整篇里的占位行（按出现顺序）。"""
    if not text:
        return []
    prose = is_prose(path)
    hits = []
    for i, raw in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        if len(raw) > LINE_MAX:
            continue
        tok = _placeholder(raw, prose)
        if tok:
            hits.append(Hit(i, raw.strip()[:80], tok))
    return hits


def introduced(before: str | None, after: str, path: str = "") -> list[Hit]:
    """这次写入新带进来的占位：after 里的占位比 before 里同样的多出来的那几处（之前就有的不算）。"""
    hits = detect(after, path)
    if not hits:
        return []
    old = Counter(h.token for h in detect(before or "", path))
    out = []
    for h in hits:
        if old[h.token] > 0:
            old[h.token] -= 1
        else:
            out.append(h)
    return out


def refusal(path: str, hits: list[Hit], tool: str = "write_file") -> str:
    """给模型的话：哪几行、为什么不写、怎么改。"""
    shown = "；".join(f"第 {h.line} 行「{h.text}」" for h in hits[:SHOWN])
    more = f" 等 {len(hits)} 处" if len(hits) > SHOWN else ""
    how = ("把整篇每一行都写出来；只改一部分就用 edit_file / apply_patch 只换那一段"
           if tool == "write_file" else "new_string / 补丁里写出要放进文件的完整原文，不要用占位代替没改的部分")
    return (f"没有写入 {path}：内容里有省略占位（{shown}{more}），写进去会把原来的内容换成这行字、把文件写坏。"
            f"请给出完整内容：{how}。")


SHORT = "内容有省略占位"
