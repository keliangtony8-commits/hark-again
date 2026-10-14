"""“哪些文件内容完全一样”的唯一规则（v2.72，修 B38）。工具壳 find_duplicates 在 agent/builtin/workspace.py。

为什么要专门的工具：真跑 r5 / t1（e2e §42 §44）里模型 run_command 算 md5/sha256，自己读输出分组，
三个哈希相同的文件只列了两个（漏了 IMG_9001.jpg）——让模型数自己命令输出里的长哈希，本来就容易漏行。
分组是纯计算，交给代码做：结果直接是“第 N 组：K 个”加每个路径，模型只要照抄，不用比对哈希；
也省 token（不用把每个文件的哈希都塞进上下文）。消费级对标：手机“文件管理 → 重复文件”、相册“重复照片”。
参考：Codex / Gemini CLI / deepseek-harness 都没有这类工具（开发者工具，靠 shell）→ 自写。

规则：
- 遍历沿用 workspace_search.walk（隐藏目录、node_modules 这类依赖目录默认不进，path 明确指进去才进；不跟符号链接）；
  include 是一个 glob（如 *.{jpg,png}），和 grep 同一套。
- 先按大小分桶（大小不同绝不可能相同）→ 桶里先比前 HEAD_BYTES 的 SHA-256 → 还撞的再比整个文件的 SHA-256。
  只看内容：文件名、修改时间、扩展名都不算。空文件（0 字节）不算重复，单独计数说一句。
- 上限：HASH_BYTES_MAX 总共读这么多字节、HASH_BUDGET 秒；到顶如实说“没比完”，已比完的组照给。
- 输出：按“删掉多余的能省多少”从大到小排组；组里按“像原件”的排前（名字不带 副本 / (1) / copy / -1 这类标记、
  名字短的在前），但不替用户决定删哪个。末尾一句：回答时每组每个文件都写出来；删之前先问用户。
"""
import hashlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import workspace_search as ws_search

HEAD_BYTES = 64 * 1024              # 第一轮只比开头这么多
CHUNK = 1024 * 1024
HASH_BYTES_MAX = 4 * 1024 ** 3      # 一次最多读 4 GB（4G 内存 VPS 上流式读，不占内存，只花时间）
HASH_BUDGET = 30.0                  # 秒
_COPY_MARK = re.compile(r"(副本|拷贝|复制|备份|copy|\(\d+\)|（\d+）|[-_ ]\d{1,2}$|\bcopy\b)", re.I)


@dataclass
class Result:
    groups: list[list[str]] = field(default_factory=list)   # 每组 ≥2 个相对路径，已排好
    sizes: list[int] = field(default_factory=list)          # 每组单个文件大小
    seen: int = 0                                           # 看了多少个文件
    empty: int = 0                                          # 0 字节文件个数
    walk_capped: bool = False
    hash_capped: bool = False                               # 字节 / 时间到顶，有的桶没比完
    unreadable: int = 0


def _digest(p: Path, limit: int | None, budget: list) -> str | None:
    """budget = [剩余字节, 截止时间]；读不了 → None。"""
    h = hashlib.sha256()
    left = limit
    try:
        with p.open("rb") as f:
            while True:
                n = CHUNK if left is None else min(CHUNK, left)
                if n <= 0:
                    break
                b = f.read(n)
                if not b:
                    break
                h.update(b)
                budget[0] -= len(b)
                if left is not None:
                    left -= len(b)
    except OSError:
        return None
    return h.hexdigest()


def _original_first(rel: str) -> tuple:
    stem = rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return (bool(_COPY_MARK.search(stem)), len(stem), rel)


def find(ws: str, path: str = "", include: str = "") -> Result:
    if include:
        ws_search.check_include(include)
        match = ws_search.matcher(include)
    else:
        match = None
    w = ws_search.walk(ws, path)
    base_rel = w.rel(w.base) if w.base != w.root else ""
    res = Result(seen=0, walk_capped=w.capped)
    by_size: dict[int, list[Path]] = {}
    for p in w.files:
        rel = w.rel(p)
        sub = p.name if w.base.is_file() else (rel[len(base_rel) + 1:] if base_rel else rel)
        if match and not match(sub):
            continue
        try:
            size = p.stat().st_size
        except OSError:
            res.unreadable += 1
            continue
        res.seen += 1
        if size == 0:
            res.empty += 1
            continue
        by_size.setdefault(size, []).append(p)
    budget = [HASH_BYTES_MAX, time.monotonic() + HASH_BUDGET]
    found: list[tuple[int, list[str]]] = []
    # 小文件先比：同样的预算能比完更多组；大文件到顶了如实说
    for size in sorted(s for s, ps in by_size.items() if len(ps) > 1):
        paths = by_size[size]
        if budget[0] < size * len(paths) or time.monotonic() > budget[1]:
            res.hash_capped = True
            continue
        heads: dict[str, list[Path]] = {}
        for p in paths:
            d = _digest(p, HEAD_BYTES, budget)
            if d is None:
                res.unreadable += 1
                continue
            heads.setdefault(d, []).append(p)
        for same_head in heads.values():
            if len(same_head) < 2:
                continue
            if size <= HEAD_BYTES:
                fulls = {"": same_head}
            else:
                fulls = {}
                for p in same_head:
                    d = _digest(p, None, budget)
                    if d is None:
                        res.unreadable += 1
                        continue
                    fulls.setdefault(d, []).append(p)
            for g in fulls.values():
                if len(g) > 1:
                    found.append((size, sorted((w.rel(p) for p in g), key=_original_first)))
    found.sort(key=lambda t: (-(t[0] * (len(t[1]) - 1)), t[1][0]))
    res.groups = [g for _, g in found]
    res.sizes = [s for s, _ in found]
    return res


def _where(path: str) -> str:
    return f"「{path}」里" if path else "工作区里"


def render(ws: str, path: str, include: str, r: Result) -> str:
    """给模型看的文字：组号 + 个数 + 每个路径一行（照抄就不会漏）。"""
    what = f"匹配 {include} 的" if include else ""
    notes = []
    if r.walk_capped:
        notes.append("（文件太多 / 走太久，没看完所有文件；缩小 path 或用 include 再找）")
    if r.hash_capped:
        notes.append(f"（读文件到了上限（{ws_search._size(HASH_BYTES_MAX)} / {int(HASH_BUDGET)} 秒），"
                     "有些较大的同尺寸文件没比完；缩小 path 或 include 再找一次）")
    if r.unreadable:
        notes.append(f"（{r.unreadable} 个文件读不了，没算进去）")
    if r.empty:
        notes.append(f"（另有 {r.empty} 个空文件（0 字节），不算重复）")
    if not r.groups:
        return f"{_where(path)}共 {r.seen} 个{what}文件，没有内容完全相同的（按 SHA-256 比对内容）。" + "".join(notes)
    files = sum(len(g) for g in r.groups)
    saved = sum(s * (len(g) - 1) for s, g in zip(r.sizes, r.groups))
    head = (f"{_where(path)}共 {r.seen} 个{what}文件，其中有 {len(r.groups)} 组内容完全相同的文件，共 {files} 个"
            f"（每组只留一个可省 {ws_search._size(saved)}）：")
    lines = []
    for i, (g, s) in enumerate(zip(r.groups, r.sizes), 1):
        lines.append(f"第 {i} 组：{len(g)} 个，每个 {ws_search._size(s)}")
        lines.extend(f"  - {rel}" for rel in g)
    tail = [*notes, "按 SHA-256 比对内容（文件名、修改时间不算）；每组里看着像原件的排在前面。"
            "回答时每组的每个文件都要写出来，别合并、别省略；删除或移动前先问用户留哪个。"]
    return ws_search._finish(ws, "duplicates", head, lines, len(lines), files, tail)
