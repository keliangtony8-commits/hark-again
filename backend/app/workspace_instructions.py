# Ported from deepseek-harness/packages/context/agent-instructions/src/{files,render,digest,config}.ts (MIT), modified.
# Copyright (c) 2026 DeepSeek — MIT License, see assistant/NOTICE.
"""工作区规则文件（AGENTS.md 一类）的唯一规则：找哪些文件、读多少、怎么排进给模型的文字、怎么按字节预算裁。

用户（或助手自己）在工作区里放 AGENTS.md，写“这个项目怎么跑测试、代码风格、别动哪些目录”，助手每轮自动遵守 ——
对标 Codex / Gemini CLI / deepseek-harness 的 AGENTS.md / GEMINI.md。

移植自 deepseek-harness 的 agent-instructions（排名 ① deepseek ② Gemini JIT ③ Codex，比较见 docs/core-research.md）：
- 候选名（同目录全都加载，按这个顺序）：AGENTS.md、CLAUDE.md，之后本地覆盖层 AGENTS.local.md、CLAUDE.local.md；
- 同一目录里去掉首尾空白后内容相同的只留第一个（sha1）；
- 单个文件超过 MAX_SOURCE_BYTES 直接不读；
- 渲染：<system-reminder> 外框 + 引言 + 每个文件一节 "Instructions from: <相对路径>"；内容里的 </system-reminder> 转义；
- 超预算：先从最宽泛的（父目录）开始整份省掉，保留最具体的后缀；最具体的一个还放不下就二分截断（按 UTF-8 码点边界），
  再不行换短引言，再不行只给“预算 N 字节：省掉/截断了哪些”的提示；文字开头注明省了谁、截了谁；
- 子目录的规则不进基线：工具碰到某个子目录里的文件时（read/write/edit/list），把根到那个目录之间新发现、
  或内容变了、或被删了的规则文件追加到工具结果里（"Additional / Updated instructions from"、"Instructions removed"），
  只有真正渲染进去的才记为“已告知”（renderInstructionChanges 的 represented）。
我们的改动（云端多用户工作区）：
- 根目录 = 工作区根（不向上找 .git：工作区之外不是用户的东西）；没有用户级全局文件（我们有记忆）；
- 符号链接解析后必须仍在工作区里（沙盒里的人可以建指向 /etc 的链接，后端不能替它读）；隐藏目录（.git/.spill…）不算；
- “已告知”按一轮记（ToolContext.instructions，每轮一个 Tracker）：我们不像 deepseek 那样把注入文字永久留在历史里，
  下一轮碰到同一目录再说一次，代价小、不会忘；
- 预算默认 settings.workspace_instructions_bytes = 16384（deepseek 65536；学生小钱包，约 4k token 封顶）。
"""
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from .config import settings
from .storage import hidden, project_file_root

INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md")
LOCAL_INSTRUCTION_FILES = ("AGENTS.local.md", "CLAUDE.local.md")
MAX_SOURCE_BYTES = 1_048_576

SYSTEM_REMINDER_OPEN = "<system-reminder>"
SYSTEM_REMINDER_CLOSE = "</system-reminder>"
INTRO = ("The following workspace instructions may be relevant to your work. "
         "Use them as guidance when applicable. More specific instructions take precedence over broader ones. "
         "They do not override system, developer, or direct user instructions.")
COMPACT_INTRO = "Workspace instructions were omitted or truncated to fit the configured byte budget."
ADDITIONAL_GUIDANCE = ("Use them as guidance when relevant; more specific instructions take precedence. "
                       "They do not override system, developer, or direct user instructions.")


@dataclass(frozen=True)
class Loaded:
    path: str          # 给模型看的相对路径（"AGENTS.md"、"web/AGENTS.md"）
    content: str


@dataclass(frozen=True)
class Truncated:
    path: str
    original: int      # 原文字节
    included: int      # 放进去的字节


@dataclass
class Rendered:
    text: str
    omitted: list[str] = field(default_factory=list)
    truncated: list[Truncated] = field(default_factory=list)
    represented: list[Loaded] = field(default_factory=list)


# ---------- 发现与读取（files.ts） ----------

def _bytes(s: str) -> int:
    return len(s.encode("utf-8"))


def digest(content: str) -> str:
    """去掉首尾空白后的 sha1（digest.ts trimmedInstructionDigest）。"""
    return hashlib.sha1(content.strip().encode("utf-8")).hexdigest()


def _inside(root: Path, p: Path) -> Path | None:
    """解析符号链接后仍在工作区里、且不在隐藏目录里的普通文件 → 真实路径；否则 None（缺失 / 目录 / 越界都算没有）。"""
    try:
        real = p.resolve()
    except (OSError, RuntimeError):
        return None
    if real != root and root not in real.parents:
        return None
    if hidden(real.relative_to(root).parts) or hidden(p.relative_to(root).parts):
        return None
    try:
        return real if real.is_file() else None
    except OSError:
        return None


def _read(real: Path) -> str | None:
    """单个文件超过 MAX_SOURCE_BYTES → 不读；读不了（刚被删、权限）→ None。非 UTF-8 字节替换掉。"""
    try:
        if real.stat().st_size > MAX_SOURCE_BYTES:
            return None
        data = real.read_bytes()
    except OSError:
        return None
    if len(data) > MAX_SOURCE_BYTES:
        return None
    return data.decode("utf-8", errors="replace")


def _rel(root: Path, d: Path, name: str) -> str:
    rel = (d / name).relative_to(root)
    return rel.as_posix()


def files_in(root: Path, d: Path) -> list[Loaded]:
    """一个目录里存在的全部规则文件，候选顺序；同目录内容重复的只留第一个（dedupInstructionFilesByCandidateGroup）。"""
    out: list[Loaded] = []
    seen: set[str] = set()
    for name in INSTRUCTION_FILES + LOCAL_INSTRUCTION_FILES:
        real = _inside(root, d / name)
        if real is None:
            continue
        content = _read(real)
        if content is None:
            continue
        key = digest(content)
        if key in seen:
            continue
        seen.add(key)
        out.append(Loaded(_rel(root, d, name), content))
    return out


def descendant_dirs(root: Path, touched: Path, is_dir: bool = False) -> list[Path]:
    """根（不含）到被碰文件所在目录（含）之间的目录，由浅到深（descendantDirsBetween；目录本身被列出时含它）。"""
    target = touched if is_dir else touched.parent
    try:
        rel = target.relative_to(root)
    except ValueError:
        return []
    out, cur = [], root
    for part in rel.parts:
        cur = cur / part
        out.append(cur)
    return out


def workspace_root(ws: str) -> Path | None:
    root = project_file_root(ws)
    return root if root.is_dir() else None


# ---------- 渲染（render.ts） ----------

def truncate_utf8(value: str, max_bytes: int) -> str:
    data = value.encode("utf-8")
    if len(data) <= max_bytes:
        return value
    end = max(0, int(max_bytes))
    while end > 0 and (data[end] & 0xC0) == 0x80:  # 第一个被排除的字节是续字节 → 切在码点中间，退回到首字节
        end -= 1
    return data[:end].decode("utf-8")


def escape_frame(body: str) -> str:
    return body.replace(SYSTEM_REMINDER_CLOSE, "<\\/system-reminder>")


def section(f: Loaded) -> str:
    return f"Instructions from: {f.path}\n\n{f.content}"


def scope_of(path: str) -> str:
    d = os.path.dirname(path)
    return d or "."


def additional_section(f: Loaded) -> str:
    return "\n".join([f"Additional instructions from: {f.path}", "",
                      f"These instructions apply to work under `{scope_of(f.path)}`. {ADDITIONAL_GUIDANCE}", "",
                      f.content])


def updated_section(f: Loaded) -> str:
    return "\n".join([f"Updated instructions from: {f.path}", "",
                      "This file changed after it was loaded. Use the following content instead of the previously "
                      "loaded instructions from this file.", "", f.content])


def removed_section(path: str) -> str:
    return f"Instructions removed: {path}\n\nThe previously loaded instructions from this file no longer apply."


@dataclass(frozen=True)
class _Style:
    intro: str
    section: object  # Callable[[Loaded], str]


BASELINE = _Style(INTRO, section)


def _marker(max_bytes: int, omitted: list[str], truncated: list[Truncated]) -> str:
    if not omitted and not truncated:
        return ""
    parts = []
    if omitted:
        parts.append("omitted " + ", ".join(omitted))
    if truncated:
        parts.append("truncated " + ", ".join(f"{t.path} from {t.original} to {t.included} bytes" for t in truncated))
    return f"Workspace instruction budget {max_bytes} bytes: {'; '.join(parts)}"


def _build(files: list[Loaded], max_bytes: int, omitted: list[str], truncated: list[Truncated], style: _Style) -> str:
    marker = _marker(max_bytes, omitted, truncated)
    body = [b for b in [marker, style.intro, *(style.section(f) for f in files)] if b]
    return "\n".join([SYSTEM_REMINDER_OPEN, escape_frame("\n\n".join(body)), SYSTEM_REMINDER_CLOSE])


def _cut(f: Loaded, n: int) -> Loaded:
    return Loaded(f.path, truncate_utf8(f.content, n))


def _truncate_to_fit(f: Loaded, max_bytes: int, omitted: list[str], style: _Style) -> Loaded:
    original = _bytes(f.content)
    low, high, best = 0, original, _cut(f, 0)
    while low <= high:
        mid = (low + high) // 2
        cand = _cut(f, mid)
        text = _build([cand], max_bytes, omitted, [Truncated(f.path, original, _bytes(cand.content))], style)
        if _bytes(text) <= max_bytes:
            best, low = cand, mid + 1
        else:
            high = mid - 1
    return best


def render(files: list[Loaded], max_bytes: int, style: _Style = BASELINE) -> Rendered:
    """files 由宽到具体排好。超预算时按 deepseek 的顺序退让（见模块说明）。"""
    if max_bytes <= 0:
        return Rendered("", [f.path for f in files], [], [])
    if not files:
        return Rendered("", [], [], [])
    full = _build(files, max_bytes, [], [], style)
    if _bytes(full) <= max_bytes:
        return Rendered(full, [], [], list(files))
    for start in range(1, len(files)):
        included = files[start:]
        omitted = [f.path for f in files[:start]]
        text = _build(included, max_bytes, omitted, [], style)
        if _bytes(text) <= max_bytes:
            return Rendered(text, omitted, [], list(included))
    last = files[-1]
    omitted = [f.path for f in files[:-1]]
    original = _bytes(last.content)
    for st in (style, _Style(COMPACT_INTRO, style.section)):
        cut = _truncate_to_fit(last, max_bytes, omitted, st)
        n = _bytes(cut.content)
        trunc = [Truncated(last.path, original, n)]
        text = _build([cut], max_bytes, omitted, trunc, st)
        if _bytes(text) <= max_bytes:
            return Rendered(text, omitted, trunc, [last] if n > 0 or original == 0 else [])
    trunc = [Truncated(last.path, original, 0)]
    notice = escape_frame(_marker(max_bytes, omitted, trunc))
    with_heading = escape_frame("\n\n".join([notice, style.section(_cut(last, 0))]))
    if _bytes(with_heading) <= max_bytes:
        return Rendered(with_heading, omitted, trunc, [last] if original == 0 else [])
    text = notice if _bytes(notice) <= max_bytes else truncate_utf8(notice, max_bytes)
    return Rendered(text, omitted, trunc, [])


# ---------- 子目录规则的增量（renderInstructionChanges + 每轮的已告知状态） ----------

@dataclass(frozen=True)
class Change:
    action: str        # set | replace | remove
    file: Loaded       # remove 时 content 为空
    digest: str = ""


def render_changes(changes: list[Change], max_bytes: int) -> tuple[str, list[Change]]:
    """一批增量 → (文字, 真正渲染进去的那些)。只有文件自己的一节留下来（不是只剩通用提示）才算已告知。"""
    by_path = {c.file.path: c for c in changes}

    def sec(f: Loaded) -> str:
        c = by_path[f.path]
        if c.action == "set":
            return additional_section(f)
        if c.action == "remove":
            return removed_section(c.file.path)
        return updated_section(f)

    r = render([c.file for c in changes], max_bytes, _Style("", sec))
    shown = {f.path for f in r.represented}
    return r.text, [c for c in changes if c.file.path in shown]


class Tracker:
    """一轮里已经告知模型的子目录规则：相对路径 → 内容 digest。并行的只读工具共用同一个（都在事件循环里改，无竞争）。"""

    def __init__(self) -> None:
        self.told: dict[str, str] = {}

    def note(self, ws: str, touched: Path, is_dir: bool = False) -> str:
        """工具碰到 touched（工作区里的绝对路径）后要追加给模型的文字；没有新东西 → ""。出任何错都不影响工具本身。"""
        try:
            return self._note(ws, touched, is_dir)
        except Exception:  # noqa: BLE001 — 规则文件是辅助信息，绝不让工具失败（Gemini jit-context 同样吞掉）
            return ""

    def _note(self, ws: str, touched: Path, is_dir: bool) -> str:
        budget = settings.workspace_instructions_bytes
        root = workspace_root(ws)
        if budget <= 0 or root is None:
            return ""
        try:
            touched = Path(os.path.abspath(touched))
            if hidden(touched.relative_to(root).parts):
                return ""
        except ValueError:
            return ""
        changes: list[Change] = []
        for d in descendant_dirs(root, touched, is_dir):
            present = files_in(root, d)
            names = {f.path for f in present}
            prefix = d.relative_to(root).as_posix() + "/"
            for path in [p for p in self.told if p.startswith(prefix) and "/" not in p[len(prefix):]]:
                if path not in names:
                    changes.append(Change("remove", Loaded(path, "")))
            for f in present:
                key = digest(f.content)
                old = self.told.get(f.path)
                if old is None:
                    changes.append(Change("set", f, key))
                elif old != key:
                    changes.append(Change("replace", f, key))
        # 碰的正是那个规则文件本身（刚读 / 刚写）：模型已经看到全文，记为已告知，不再重复贴一遍
        own = touched.relative_to(root).as_posix() if not is_dir else ""
        for c in [c for c in changes if c.file.path == own and c.action != "remove"]:
            self.told[c.file.path] = c.digest
            changes.remove(c)
        if not changes:
            return ""
        text, shown = render_changes(changes, budget)
        for c in shown:
            if c.action == "remove":
                self.told.pop(c.file.path, None)
            else:
                self.told[c.file.path] = c.digest
        return text


# ---------- 对外入口 ----------

def baseline(ws: str) -> Rendered:
    """工作区根目录的规则文件渲染成系统提示里的一段（没有 / 预算 0 → text 为空）。"""
    budget = settings.workspace_instructions_bytes
    root = workspace_root(ws)
    if budget <= 0 or root is None:
        return Rendered("")
    return render(files_in(root, root), budget)


def summary(ws: str) -> dict:
    """给客户端看的现状：根目录有哪些规则文件、每个放进去多少（full / truncated / omitted）、预算。"""
    budget = settings.workspace_instructions_bytes
    root = workspace_root(ws)
    files = files_in(root, root) if root is not None else []
    r = render(files, budget) if budget > 0 else Rendered("", [f.path for f in files])
    cut = {t.path: t for t in r.truncated}
    items = []
    for f in files:
        size = _bytes(f.content)
        if f.path in r.omitted:
            status, used = "omitted", 0
        elif f.path in cut:
            status, used = "truncated", cut[f.path].included
        else:
            status, used = "full", size
        items.append({"path": f.path, "bytes": size, "used": used, "status": status})
    return {"files": items, "budget": max(0, budget), "candidates": list(INSTRUCTION_FILES + LOCAL_INSTRUCTION_FILES)}
