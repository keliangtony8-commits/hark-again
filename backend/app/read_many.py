"""一次读多个文本文件 —— “多文件一起读”的唯一规则（思路来自 Gemini CLI tools/read-many-files.ts，Apache-2.0；自己的实现）。

为什么要有：模型想看 3~10 个小文件（配置 + 脚本 + README）时，一个个 read_file 要好几轮，每轮都重发整段上下文。
这里一次给齐，用 Gemini 同款分隔行 “--- 路径 ---” 隔开。

规则：
- paths 每项是一个工作区相对路径或一个 glob（含 * ? [ {）；glob 从工作区根匹配，隐藏目录 / 依赖目录不搜（同 glob 工具）。
- 去重，保持给出的顺序（glob 内按路径排序）；最多 FILES_MAX 个，多出来的列进“没读”。
- 只读文字：图片、PDF/Office 文档、二进制都不读，告诉模型改用 read_file（Gemini 也是不点名就跳过素材文件）。
- 总预算 TOTAL_CHARS（低于 loop 的 tool_result_max，不被二次截断），平均分给每个文件，每份至少 SHARE_MIN；
  读不完的那份末尾带“下一段用 offset=…”（file_read.page 原样），用 read_file 接着读；预算用完的文件列进“没读”。
- 没读的原因最多列 SKIP_SHOW 条，其余只给个数（Gemini 是 5 条；我们给 10 条，手机上也短）。
"""
from dataclasses import dataclass, field
from pathlib import Path

from . import documents, file_read, vision, workspace_search
from .storage import hidden, looks_text, mime_of, project_dir, safe_join

FILES_MAX = 20
TOTAL_CHARS = 14000
SHARE_MIN = 1200
SKIP_SHOW = 10
SEP = "--- {} ---"
GLOB_CHARS = set("*?[{")


@dataclass
class Batch:
    text: str
    detail: str
    read: list[Path] = field(default_factory=list)  # 读过的文件（调用方记 file_seen）
    failed: str | None = None


def _is_glob(s: str) -> bool:
    return any(c in GLOB_CHARS for c in s)


def expand(ws: str, paths: list[str]) -> tuple[list[tuple[str, Path]], list[tuple[str, str]]]:
    """→ ([(相对路径, 文件)], [(写法, 没读的原因)])。不读内容。"""
    root = project_dir(ws).resolve()
    picked: dict[str, Path] = {}
    skipped: list[tuple[str, str]] = []
    walked = None
    for raw in paths:
        item = (raw or "").strip()
        while item.startswith("./"):
            item = item[2:]
        if not item:
            continue
        if _is_glob(item):
            try:
                match = workspace_search.matcher(item)
                walked = walked or workspace_search.walk(ws, "")
            except workspace_search.SearchError as e:
                skipped.append((item, str(e)))
                continue
            hits = sorted(w for w in (walked.rel(p) for p in walked.files) if match(w))
            if not hits:
                skipped.append((item, "没有匹配的文件"))
            for rel in hits:
                picked.setdefault(rel, root / rel)
            continue
        try:
            p = safe_join(root, item)
        except ValueError:
            skipped.append((item, "不在工作区里"))
            continue
        rel = p.relative_to(root).as_posix() if p != root else ""
        if p.is_dir():
            skipped.append((item, f"是目录，读里面的文件写成 {item.rstrip('/')}/** 这样的模式"))
        elif not p.is_file():
            skipped.append((item, "不存在"))
        elif hidden(Path(rel).parts) and not item.startswith("."):
            skipped.append((item, "在隐藏目录里"))
        else:
            picked.setdefault(rel, p)
    return list(picked.items()), skipped


def _kind(p: Path) -> str | None:
    """不能当文字读的 → 原因；能读 → None。"""
    if mime_of(p.name) in vision.IMAGE_MIMES:
        return "是图片，用 read_file 单独看"
    with p.open("rb") as f:
        head = f.read(8)
    if documents.kind_of(p.name, head) is not None or documents.is_old(p.name):
        return "是文档（PDF/Office），用 read_file 读（可以选页）"
    if not looks_text(p):
        return "不是文本文件"
    return None


def read(ws: str, paths: list[str]) -> Batch:
    if not isinstance(paths, list) or not any(isinstance(x, str) and x.strip() for x in paths):
        return Batch("paths 给一个列表，每项是文件路径或 glob（如 [\"README.md\", \"src/*.py\"]）。", "", failed="参数不对")
    files, skipped = expand(ws, [x for x in paths if isinstance(x, str)])
    texts: list[tuple[str, Path]] = []
    for rel, p in files:
        if (why := _kind(p)) is not None:
            skipped.append((rel, why))
        else:
            texts.append((rel, p))
    over = texts[FILES_MAX:]
    texts = texts[:FILES_MAX]
    skipped += [(rel, f"一次最多读 {FILES_MAX} 个") for rel, _ in over]
    parts: list[str] = []
    done: list[Path] = []
    budget = TOTAL_CHARS
    share = max(SHARE_MIN, TOTAL_CHARS // max(1, len(texts)))
    for i, (rel, p) in enumerate(texts):
        if budget < SHARE_MIN:
            skipped += [(r, "这次的字数预算用完了，用 read_file 单独读") for r, _ in texts[i:]]
            break
        try:
            body, _ = file_read.read(p, "chars", 0, min(share, budget))
        except (file_read.ReadError, OSError) as e:
            skipped.append((rel, f"读不了：{e}"))
            continue
        parts.append(f"{SEP.format(rel)}\n{body}")
        done.append(p)
        budget -= len(body)
    lines = []
    if parts:
        lines.append(f"读了 {len(parts)} 个文件：")
        lines.append("\n\n".join(parts))
    else:
        lines.append("一个文件都没读到。")
    if skipped:
        shown = [f"- {w}：{why}" for w, why in skipped[:SKIP_SHOW]]
        more = [f"- …还有 {len(skipped) - SKIP_SHOW} 个"] if len(skipped) > SKIP_SHOW else []
        lines.append("\n".join([f"没读的 {len(skipped)} 个："] + shown + more))
    detail = f"{len(parts)} 个文件" + (f"，{len(skipped)} 个没读" if skipped else "")
    return Batch("\n\n".join(lines), detail, done, None if parts else "没读到文件")
