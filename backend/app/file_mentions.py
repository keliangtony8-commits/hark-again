# Copyright 2025 Google LLC
# SPDX-License-Identifier: Apache-2.0
#
# Ported from gemini-cli/packages/cli/src/ui/hooks/atCommandProcessor.ts and
# gemini-cli/packages/core/src/utils/atCommandUtils.ts (Apache-2.0), modified:
# 只取“解析 @路径 + 解析到工作区文件 + 找不到时按名字模糊找”这一段；读文件交给已有的项目文件引用
# （context._project_ref 每轮按磁盘内联），所以这里只产出相对路径。
"""消息里的 `@路径`（学 Gemini CLI 的 @ 命令）：用户在输入框写 `@notes/plan.md` 或只写 `@plan`，
发出时把它解析成这段对话工作区里的真实文件，作为“引用工作区文件”附在消息上（ws._project_files，规则只一处）。

唯一规则在这里：
- parse(text)：找出所有 @ 引用。@ 前面不能是 ASCII 字母数字/下划线/点/反斜杠/@（邮箱 a@b.com 不算），中文紧挨着可以；
  代码块 ``` 和行内 `code` 里的不算；路径可以用双引号包（带空格的文件名），反斜杠转义空格；
  遇到空白、半角/全角标点停（Gemini 的分隔符 + 全角 ，。；：！？、（）【】《》“”‘’「」）；句末的点不算路径。
- resolve(root, token)：先原样找（相对工作区根；越界、目录、隐藏目录不认），再去掉行号后缀（:10、:10-20、#L10-L20），
  再在 ASCII/非 ASCII 交界处截短（“@main.py然后” → main.py）；都找不到再按 Gemini 的 `**/*名字*` 模糊找，
  多个命中取最近修改的那个。目录不附（Gemini 也只给目录路径、不读内容；模型自己会 list_files）。
- paths(text, root)：按出现顺序去重，最多 MENTIONS_MAX 个。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from . import agent_mentions
from .storage import hidden

MENTIONS_MAX = 10      # 一条消息最多解析几个 @（再多就是在贴日志了）
GLOB_PATH_MAX = 255    # Gemini MAX_GLOB_SEARCH_PATH_LENGTH
SCAN_MAX = 5000        # 模糊找时最多看多少个文件（大工作区不卡住发消息）

# Gemini AT_COMMAND_PATH_REGEX_SOURCE + 全角标点；@ 前面的限制是我们加的（中文里没有空格分词，邮箱要排除）
_STOP = " \t\n\r,;!?()\\[\\]{}.\"'`，。；：！？、（）【】《》“”‘’「」"  # 路径里不能出现（点另算）
_PATH = (r'(?:(?:"[^"\n\r]*")|(?:\\.|[^' + _STOP + r']|\.(?!$|[ \t\n\r，。；：！？、]))+)')
MENTION_RE = re.compile(r'(?<![A-Za-z0-9_.\\@])@(' + _PATH + ')')
_CODE_RE = re.compile(r"```.*?(?:```|$)|`[^`\n]*`", re.S)
# Gemini LINE_NUMBER_SUFFIX_REGEX
_LINE_RE = re.compile(r"^(.+?)(?::\d+(?::\d+)?(?:-\d+(?::\d+)?)?:?|#L?\d+(?:-(?:#?L)?\d+)?)$", re.I)
_GLOB_BAD = re.compile(r"[\r\n\t\0{}*?\[\]]")


def _unescape(p: str) -> str:
    """Gemini unescapePath（非 Windows）+ 引号包着的整段去引号。"""
    if len(p) >= 2 and p[0] == '"' and p[-1] == '"':
        return p[1:-1]
    return re.sub(r"\\(.)", r"\1", p)


def parse(text: str | None) -> list[str]:
    if not isinstance(text, str) or "@" not in text:
        return []
    clean = _CODE_RE.sub(lambda m: " " * len(m.group(0)), text)  # 代码里的 @scope/pkg、装饰器不算
    clean = agent_mentions.blank(clean)  # @子助手 先按子助手认，不再当文件找（Gemini：代理优先）
    out: list[str] = []
    for m in MENTION_RE.finditer(clean):
        p = _unescape(m.group(1)).strip()
        if p and p not in out:
            out.append(p)
        if len(out) >= MENTIONS_MAX:
            break
    return out


def strip_line_suffix(p: str) -> str | None:
    m = _LINE_RE.match(p)
    return m.group(1) if m and m.group(1) else None


def _boundaries(p: str) -> list[str]:
    """“main.py然后” → ["main.py"]：在 ASCII 和非 ASCII 交界处截出的前缀，长的在前（不含原串）。"""
    out = []
    for i in range(len(p) - 1, 0, -1):
        if (p[i - 1].isascii()) != (p[i].isascii()):
            pre = p[:i].rstrip(".-_")
            if pre and pre not in out:
                out.append(pre)
    return out


def _candidates(token: str) -> list[str]:
    out: list[str] = []
    for c in [token, strip_line_suffix(token), *_boundaries(token)]:
        if c and c not in out:
            out.append(c)
        s = strip_line_suffix(c) if c else None
        if s and s not in out:
            out.append(s)
    return out


def _exact(root: Path, rel: str) -> str | None:
    rel = rel.lstrip("/")
    if not rel or rel.startswith("~"):
        return None
    try:
        p = (root / rel).resolve()
        rr = root.resolve()
    except (OSError, RuntimeError):
        return None
    if p == rr or rr not in p.parents:
        return None
    parts = p.relative_to(rr).parts
    if hidden(parts) or not p.is_file():
        return None
    return "/".join(parts)


def _glob_ok(name: str) -> bool:
    """Gemini isPathSuitableForGlob。"""
    return 0 < len(name) <= GLOB_PATH_MAX and not os.path.isabs(name) and ".." not in name and not _GLOB_BAD.search(name)


def _glob(root: Path, name: str) -> str | None:
    """Gemini 的 `**/*名字*`：名字里没有 / → 文件名包含它；有 / → 最后一段落在文件名里、整段落在路径里。
    多个命中取最近修改的（Gemini glob 工具按新旧排序后取第一个），同时间按路径。"""
    if not _glob_ok(name):
        return None
    low = name.lower()
    tail = low.rsplit("/", 1)[-1]
    best: tuple[float, str] | None = None
    seen = 0
    try:
        rr = root.resolve()
        for dirpath, dirnames, filenames in os.walk(rr):
            rel_dir = Path(dirpath).relative_to(rr)
            dirnames[:] = sorted(d for d in dirnames if not hidden((*rel_dir.parts, d)))
            for f in sorted(filenames):
                seen += 1
                if seen > SCAN_MAX:
                    return best[1] if best else None
                rel = "/".join((*rel_dir.parts, f))
                if tail not in f.lower() or low not in rel.lower():
                    continue
                p = Path(dirpath) / f
                if not p.is_file():
                    continue
                key = (p.stat().st_mtime, rel)
                if best is None or key[0] > best[0] or (key[0] == best[0] and rel < best[1]):
                    best = key
    except OSError:
        return best[1] if best else None
    return best[1] if best else None


def resolve(root: Path, token: str) -> str | None:
    cands = _candidates(token)
    for c in cands:
        if hit := _exact(root, c):
            return hit
    for c in cands:
        if hit := _glob(root, c):
            return hit
    return None


def paths(text: str | None, root: Path) -> list[str]:
    if not root.is_dir():
        return []
    out: list[str] = []
    for token in parse(text):
        rel = resolve(root, token)
        if rel and rel not in out:
            out.append(rel)
    return out
