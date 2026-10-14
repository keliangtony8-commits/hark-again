"""回复里 Markdown 表格“列数对不齐”就地补齐（唯一入口，v2.71 第十五轮 r5 低优先）。

真机 r5：表头只有“组 | 文件”两列，数据行却写了 3～4 格（一组里有几张重复照片就写几格）。
GFM 规范里多出表头的格子直接丢掉——App / 网页都按规范渲染，用户就看不到“夜景 副本.jpg”“IMG_9001.jpg”，
这比排版难看更糟：答案的一部分凭空消失。三家参考都是终端输出原样打印，不渲染表格，所以自写本地规则。
列数是纯文本结构，不必再问模型：零额外调用。

- fix(reply) → (改好的回复, [(原行, 新行)])；没问题 → (原文, [])。
- 只认标准表格：表头行 + 分隔行（| --- | :--: |），后面连着的带“|”的行是数据行；``` 代码块里的不碰。
- 表头 n 列：
  · 每一行都多出同样的列数 m > n（表头漏写了列名）→ 表头和分隔行补空列，数据原样成列；
  · 否则某行 > n 格 → 第 n 格起合并成一格，用“、”连（英文回复用“, ”）——多出的格子本就是最后一列的“又一个”；
  · 某行 < n 格 → 补空格子；分隔行列数不对 → 按 n 列重写，原有对齐方式保留。
- 只重写有问题的行，其余行一字不动；转义的 \\| 不算分隔。
"""
from __future__ import annotations

import re

_SEP_CELL = re.compile(r"^\s*:?-{1,}:?\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_CJK = re.compile(r"[\u4e00-\u9fff]")


def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", s)]


def _is_sep(line: str) -> bool:
    if "-" not in line:
        return False
    cells = _cells(line)
    return bool(cells) and all(_SEP_CELL.match(c) for c in cells)


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _is_row(line: str) -> bool:
    return "|" in line and bool(line.strip())


def fix(reply: str) -> tuple[str, list[tuple[str, str]]]:
    if not reply or "|" not in reply or "-" not in reply:
        return reply, []
    lines = reply.split("\n")
    joiner = "、" if _CJK.search(reply) else ", "
    changes: list[tuple[str, str]] = []
    fenced, i = False, 0
    while i < len(lines):
        line = lines[i]
        if _FENCE.match(line):
            fenced = not fenced
            i += 1
            continue
        if fenced or not _is_row(line) or i + 1 >= len(lines) or not _is_sep(lines[i + 1]):
            i += 1
            continue
        head, sep = _cells(line), _cells(lines[i + 1])
        j = i + 2
        while j < len(lines) and _is_row(lines[j]) and not _FENCE.match(lines[j]):
            j += 1
        body = [_cells(lines[k]) for k in range(i + 2, j)]
        n = len(head)
        widths = {len(r) for r in body}
        if body and len(widths) == 1 and (m := widths.pop()) > n:
            head, n = head + [""] * (m - n), m
        new: dict[int, str] = {}
        if len(_cells(line)) != n:
            new[i] = _row(head)
        if len(sep) != n:
            new[i + 1] = _row([(sep[k] if k < len(sep) else "---") for k in range(n)])
        for k, r in zip(range(i + 2, j), body):
            if len(r) > n:
                r = r[:n - 1] + [joiner.join(c for c in r[n - 1:] if c)]
            elif len(r) < n:
                r = r + [""] * (n - len(r))
            else:
                continue
            new[k] = _row(r)
        for k, text in sorted(new.items()):
            changes.append((lines[k], text))
            lines[k] = text
        i = j
    return ("\n".join(lines), changes) if changes else (reply, [])
