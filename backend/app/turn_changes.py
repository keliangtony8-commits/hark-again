# Ported from openai/codex codex-rs/core/src/turn_diff_tracker.rs (Apache-2.0), modified:
# 同一套“每个路径第一次被碰时记下基线，回合结束按 基线 → 现状 出净改动，基线 = 现状就不出”的规则；
# 改成 Python、按工作区落盘基线以支持整轮撤销，现状在收尾时从磁盘读（Codex 只记补丁内容、不重读文件系统）。
"""一轮回复里助手改过的工作区文件：净改动卡（ChangesBlock）+ 整轮撤销。唯一规则在这里。

对标 Hark / Codex / Gemini CLI：Codex 每轮给一份汇总 diff（TurnDiffTracker），Gemini 在改文件前打检查点、/restore 回退。
我们取两者：
- Tracker（每轮一个，挂在 ToolContext.changes；并行副本、子助手共用同一个）：write_file / edit_file 写之前调
  before(root, p)，同一路径只记第一次（Codex baseline_by_path 规则）：不存在 → None；超过 TRACK_MAX 或
  这一轮累计超过 TURN_MAX → BIG（照样列出、不能撤销）。
- finish(tracker, workspace)：收尾（正常说完和被停下都走）从磁盘读现状；基线 = 现状 → 不出（改了又改回去）；
  其余每个文件用 file_edit.change 出净 diff（同一套打码、截断规则；像密钥的文件只给 +N −M）。
  可撤销的文件把基线写进 <工作区>/.turns/<token>/（隐藏目录），manifest 记每个文件收尾时的 sha256。
- undo(workspace, token)：先全部核对（Gemini restore 不核对，我们更保守）：现状 sha 和收尾时不同 = 之后又被改过
  → Conflict(路径)，一个都不动；全对上才恢复：基线 None → 删掉（这一轮新建的），否则写回原字节；然后删记录。
- 只管 write_file / edit_file；run_command 改的文件不在卡上（卡片和给模型的历史里都这么说）。
- 记录保留 KEEP_DAYS 天，每次 finish 顺手清理过期的。
"""
import hashlib
import json
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import file_edit
from .storage import project_dir

DIR = ".turns"
TRACK_MAX = 2 * 1024 * 1024    # 单个文件基线上限（字节）：更大的照样列出，但不能撤销
TURN_MAX = 16 * 1024 * 1024    # 一轮基线累计上限
FILES_MAX = 30                 # 卡上最多列几个文件（撤销仍覆盖全部）
KEEP_DAYS = 30
BIG = object()                 # 基线太大没记


class UndoError(Exception):
    """撤销不了（记录过期 / 已撤销）：消息给用户看。"""


class Conflict(UndoError):
    def __init__(self, paths: list[str]):
        super().__init__("这些文件之后又被改过，撤销会冲掉新的改动：" + "、".join(paths))
        self.paths = paths


@dataclass
class Tracker:
    base: dict[str, object] = field(default_factory=dict)   # 绝对路径 → bytes | None | BIG
    rel: dict[str, str] = field(default_factory=dict)       # 绝对路径 → 相对工作区的显示路径
    root: str | None = None
    size: int = 0

    def before(self, root: Path, p: Path) -> None:
        """写 p 之前调：第一次碰这个路径时记下基线。从不抛异常（记不了就当 BIG）。"""
        key = str(p)
        if key in self.base:
            return
        try:
            self.root = self.root or str(root)
            self.rel[key] = p.relative_to(root).as_posix()
            if not p.exists():
                self.base[key] = None
                return
            n = p.stat().st_size
            if not p.is_file() or n > TRACK_MAX or self.size + n > TURN_MAX:
                self.base[key] = BIG
                return
            self.base[key] = p.read_bytes()
            self.size += n
        except (OSError, ValueError):
            self.base[key] = BIG
            self.rel.setdefault(key, p.name)

    @property
    def touched(self) -> bool:
        return bool(self.base)


def _read(p: Path) -> bytes | None:
    try:
        return p.read_bytes() if p.is_file() else None
    except OSError:
        return None


def _text(b: bytes | None) -> str | None:
    if b is None:
        return None
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return ""  # 二进制：diff 只算新的一侧（同 workspace._old_text）


def _sha(b: bytes | None) -> str | None:
    return None if b is None else hashlib.sha256(b).hexdigest()


def _sweep(d: Path) -> None:
    cutoff = time.time() - KEEP_DAYS * 86400
    try:
        for x in d.iterdir():
            if x.is_dir() and x.stat().st_mtime < cutoff:
                shutil.rmtree(x, ignore_errors=True)
    except OSError:
        pass


def finish(tracker: Tracker | None, workspace: str) -> dict | None:
    """收尾：出净改动卡（没有净改动 → None）并落盘撤销记录。出错只少撤销，不影响回复落库。"""
    if tracker is None or not tracker.touched:
        return None
    root = project_dir(workspace)
    files, saved = [], []
    for key in sorted(tracker.base, key=lambda k: tracker.rel.get(k, k)):
        rel, base = tracker.rel.get(key, key), tracker.base[key]
        now = _read(Path(key))
        if base is not BIG and base == now:
            continue  # 改了又改回去：没有净改动（Codex left == right → None）
        if base is BIG:
            c = file_edit.change(rel, "", _text(now) or "")
            c = {"path": rel, "added": c["added"], "removed": 0, "diff": "", "big": True}
        elif now is None:
            old = _text(base) or ""
            c = {"path": rel, "added": 0, "removed": len(old.splitlines()), "diff": "", "deleted": True}
        else:
            c = file_edit.change(rel, _text(base), _text(now) or "")
        files.append(c)
        if base is not BIG:
            saved.append((rel, base, _sha(now)))
    if not files:
        return None
    token = ""
    if saved:
        token = uuid.uuid4().hex[:16]
        d = root / DIR / token
        try:
            d.mkdir(parents=True, exist_ok=True)
            manifest = []
            for i, (rel, base, after) in enumerate(saved):
                blob = None
                if base is not None:
                    blob = f"{i}.bin"
                    (d / blob).write_bytes(base)
                manifest.append({"path": rel, "before": blob, "after": after})
            (d / "manifest.json").write_text(json.dumps({"files": manifest}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            shutil.rmtree(d, ignore_errors=True)
            token = ""
        _sweep(root / DIR)
    block = {"type": "changes", "token": token, "files": files[:FILES_MAX]}
    if len(files) > FILES_MAX:
        block["more"] = len(files) - FILES_MAX
    return block


def _manifest(workspace: str, token: str) -> tuple[Path, Path, list[dict]]:
    if not token or not token.isalnum():
        raise UndoError("这一轮的改动没有留撤销记录")
    root = project_dir(workspace)
    d = root / DIR / token
    try:
        files = json.loads((d / "manifest.json").read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError):
        raise UndoError(f"撤销记录已过期（只保留 {KEEP_DAYS} 天）或已撤销过") from None
    return root, d, files


def conflicts(workspace: str, token: str) -> list[str]:
    """哪些文件在这一轮之后又被改过（撤销会冲掉它们）。"""
    root, _, files = _manifest(workspace, token)
    return [f["path"] for f in files if _sha(_read((root / f["path"]).resolve())) != f["after"]]


def undo(workspace: str, token: str) -> list[str]:
    """把这一轮改过的文件恢复到这一轮之前；返回恢复了的路径。有冲突 → Conflict，一个都不动。"""
    root, d, files = _manifest(workspace, token)
    if bad := conflicts(workspace, token):
        raise Conflict(bad)
    done = []
    for f in files:
        p = (root / f["path"]).resolve()
        if p != root.resolve() and root.resolve() not in p.parents:
            continue  # 记录被改坏也不出工作区
        if f["before"] is None:
            if p.is_file():
                p.unlink()
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes((d / f["before"]).read_bytes())
        done.append(f["path"])
    shutil.rmtree(d, ignore_errors=True)
    return done


def history_text(b: dict) -> str:
    """给模型的历史：这一轮改了哪些文件；用户撤销过就说清楚文件已回到这一轮之前。"""
    def one(f: dict) -> str:
        if f.get("big"):
            return f"{f['path']}（大文件）"
        if f.get("deleted"):
            return f"{f['path']}（已不在）"
        return f"{f['path']}（{'新建 ' if f.get('created') else ''}{file_edit.stat(f)}）"
    names = "、".join(one(f) for f in b.get("files") or [])
    more = f" 等 {len(b['files']) + b['more']} 个文件" if b.get("more") else ""
    line = f"[这一轮用 write_file / edit_file 改了文件：{names}{more}"
    if b.get("undone"):
        line += "——用户已撤销这些改动，文件已回到这一轮之前的样子；之前读到的内容已过期，要改先重读"
    return line + "]"
