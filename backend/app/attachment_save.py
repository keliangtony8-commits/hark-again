"""把聊天里的附件存进工作区（对标 Hark 的 download_artifact：把对话里的文件存进工作区再用命令处理）。唯一规则在这里。

为什么要有：read_file attachment 只能“读”附件；用户发来压缩包、视频、表格要解压 / 转码 / 跑脚本时，
命令在沙盒里只看得见工作区，附件在 uploads/<编号>/ 里，进不去。三家参考（Codex / Gemini CLI / deepseek-harness）
都跑在用户本机，附件本来就是本机文件，没有这一步；规则按 Hark 公开行为自己定：
- target(root, name, path)：path 空 → uploads/<原名>；以 / 结尾或是已有目录 → 放进去用原名；否则就是文件名。
  逃出工作区 / 进隐藏目录（storage.HIDDEN_DIRS）→ SaveError。
- 从不覆盖：目标已有同样内容 → 直接用（reused，不复制）；内容不同 → “名字 (2).后缀”，一直到 (NAME_MAX)。
- 写前查配额（quota.check）；写入走临时文件 + os.replace（不会留半个文件）；
  记进这一轮的改动（turn_changes 基线 = 不存在，整轮撤销会删掉它）；file_seen.observe（之后可以直接覆盖）。
- hint(blocks)：给模型的历史里，一条消息带了附件就补一句编号 + 怎么存（context._render 调用）。
"""
import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import file_seen, quota
from .storage import hidden, project_dir, safe_join, upload_path

DIR = "uploads"     # 默认放进工作区的哪个目录
NAME_MAX = 99       # 重名时最多试到 “名字 (99)”
TOOL = "save_attachment"


class SaveError(Exception):
    """存不了：消息给模型看（中文、能照做）。"""


@dataclass
class Saved:
    name: str      # 附件原名
    rel: str       # 工作区里的相对路径
    size: int
    reused: bool   # 目标已有同样内容，没复制
    renamed: bool  # 因为重名换了名字


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def numbered(p: Path, n: int) -> Path:
    return p.with_name(f"{p.stem} ({n}){p.suffix}")


def target(root: Path, name: str, path: str = "") -> Path:
    """附件该放到哪（还没处理重名）。"""
    path = (path or "").strip().replace("\\", "/")
    if path == "/workspace" or path.startswith("/workspace/"):
        rel = path.removeprefix("/workspace").lstrip("/")  # 沙盒里的绝对路径 → 相对；只给根 → 默认目录
    elif path.startswith("/"):
        raise SaveError(f"{path} 在工作区外面，存不了；给相对工作区的路径（比如 {DIR}/{name}）。")
    else:
        rel = path
    if not rel or rel in (".", "./"):
        rel = f"{DIR}/{name}"
    elif rel.endswith("/"):
        rel = rel + name
    try:
        p = safe_join(root, rel)
    except ValueError:
        raise SaveError(f"{path} 在工作区外面，存不了；给相对工作区的路径（比如 {DIR}/{name}）。") from None
    if p.is_dir():
        p = p / name
    if p == root:
        raise SaveError("要给文件名或目录，不能是工作区根本身。")
    parts = p.relative_to(root).parts
    if hidden(parts):
        raise SaveError(f"{path} 在隐藏目录里（{'、'.join(sorted({x for x in parts if hidden([x])}))}），换个地方放。")
    return p


def save(workspace: str, uid: str, path: str = "", tracker=None, owner: str | None = None) -> Saved:
    """把附件 uid 复制进工作区。tracker = 这一轮的 turn_changes.Tracker（可 None）。"""
    try:
        src = upload_path((uid or "").strip())
    except ValueError:
        src = None
    if src is None or not src.is_file():
        raise SaveError("没有这个附件（编号不对，或已经删了）。附件编号在消息里“附件编号”那一句。")
    root = project_dir(workspace)
    first = p = target(root, src.name, path)
    size = src.stat().st_size
    digest = None
    for n in range(2, NAME_MAX + 2):
        if p.is_dir():
            p = numbered(first, n)
            continue
        if not p.exists():
            break
        if p.is_file() and p.stat().st_size == size:
            digest = digest or _sha(src)
            if _sha(p) == digest:
                return Saved(src.name, p.relative_to(root).as_posix(), size, True, p != first)
        p = numbered(first, n)
    else:
        raise SaveError(f"{first.relative_to(root).as_posix()} 重名的太多了，换个名字或目录。")
    try:
        quota.check(workspace, size)
    except quota.QuotaError as e:
        raise SaveError(f"没有存：{e}") from None
    if tracker is not None:
        tracker.before(root, p)  # 这一轮第一次碰：基线 = 不存在（整轮撤销会删掉它）
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{uuid.uuid4().hex[:8]}.part")
    try:
        with src.open("rb") as r, tmp.open("wb") as w:
            for chunk in iter(lambda: r.read(1 << 20), b""):
                w.write(chunk)
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)
    file_seen.observe(owner, p)
    quota.forget(workspace)
    return Saved(src.name, p.relative_to(root).as_posix(), size, False, p != first)


def for_model(s: Saved) -> str:
    where = f"/workspace/{s.rel}"
    if s.reused:
        head = f"工作区里已经有一模一样的 {s.rel}，没再复制。"
    else:
        head = f"已把附件 {s.name} 存到 {s.rel}（{quota.size_text(s.size)}）" + ("，原名已被占用，换了名字。" if s.renamed else "。")
    return f"{head}命令里用 {where}（工作目录就是 /workspace，也可以写相对路径）。"


def detail(s: Saved) -> str:
    return s.rel


def hint(blocks: list[dict]) -> str:
    """消息里用户发来的附件（upload）→ 一句编号 + 用法；没有 → 空串。图片、文档、二进制一样给。"""
    ups = [b for b in blocks if b.get("type") == "file" and b.get("source") == "upload" and b.get("id")]
    if not ups:
        return ""
    ids = "、".join(f"{b.get('name') or '附件'} = {b['id']}" for b in ups)
    return f"（附件编号：{ids}。要在命令里处理（解压、转码、跑脚本…）先用 {TOOL} 存进工作区。）"
