"""v2.14 CORE 30：run_command 改了哪些工作区文件 → 并进这一轮的改动卡和整轮撤销。唯一规则在这里。

对标：Hark 的改动卡 / 撤销覆盖助手的所有改动；三家参考里没人做“命令改的文件”——
Codex TurnDiffTracker 只记 apply_patch，Gemini CLI 的检查点（services/gitService.ts 影子 git 仓库）只在
write_file / replace 之前打，deepseek-harness 没有。我们取 Gemini 影子仓库的思路（内容寻址存一份 + 靠
size/mtime 判断没变不重算，同 git index 的 stat 缓存），但不用 git 进程，Python 直接读后端上的工作区：
- 影子库 <工作区>/.turns/shadow/：index.json（相对路径 → [size, mtime_ns, sha|None]）+ obj/<sha>（原字节）。
  只存 ≤ FILE_MAX 的文件，总量 ≤ STORE_MAX，超了的记 sha=None（照样列出，不能撤销 = turn_changes.BIG）。
- before(ws, tracker)：会改东西的前台命令之前调（readonly_command 证明只读的不调）：扫一遍工作区，变了的才重读入库，
  再把这一轮第一次见到的文件状态记进 tracker.seen（setdefault：一轮里第一次见到的才是基线）。
- after(ws, tracker)：命令结束（含到点转后台的那一刻）再扫一遍：和 seen 比 size/mtime 变了 / 不见了 / 新出现的，
  且 write_file 没先记过基线（tracker.base 先到先得），就按 seen 里的版本把基线交给 tracker，标成 command。
  之后 turn_changes.finish 照常出净 diff（改了又改回去的不出）、落撤销记录。
- 扫描：跳过 storage.HIDDEN_DIRS 和依赖目录（workspace_search.HEAVY_DIRS：node_modules、.venv …），不跟符号链接，
  最多 FILES_MAX 个文件 / TIME_BUDGET 秒；扫不完（capped）时不判“新建”和“删除”（没看到 ≠ 没有），只比看到的。
- 一轮里命令期间别的东西（后台任务）改的文件也会算进来：卡片说的是“这一轮期间改了的文件”。
- 出错从不抛：记不了只是卡上少几行、少撤销。
- v2.16 权限位也进 stat 缓存（index 每项第 4 个 = st_mode & 0o777，同 git index 记 mode）：chmod +x 不改 mtime，
  只比 size/mtime 会漏；旧的 3 项 index 当作过期重读。基线权限交给 tracker.modes，撤销时 chmod 回去。
"""
import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import readonly_command, turn_changes
from .storage import HIDDEN_DIRS, project_dir
from .workspace_search import HEAVY_DIRS

SHADOW = "shadow"                       # <工作区>/.turns/shadow/
FILE_MAX = turn_changes.TRACK_MAX       # 单文件超过就不存（2 MB，同 write_file 的基线上限）
STORE_MAX = 32 * 1024 * 1024            # 影子库总量（算进工作区磁盘配额，4G 小机器上别太大）
FILES_MAX = 20000                       # 同 workspace_search
TIME_BUDGET = 3.0                       # 秒/次扫描；两次扫描 + 配额重数，命令后最多多等几秒

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


@dataclass
class Scan:
    files: dict[str, tuple[int, int, int]] = field(default_factory=dict)  # 相对路径 → (size, mtime_ns, 权限位)
    capped: bool = False


def tracks(command: str) -> bool:
    """这条命令要不要盯文件改动：证明只读（ls / cat / git status …，规则在 readonly_command）的不盯。"""
    try:
        return not readonly_command.is_read_only(command)
    except Exception:
        return True


def scan(root: Path) -> Scan:
    s, t0 = Scan(), time.monotonic()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in HIDDEN_DIRS and d not in HEAVY_DIRS]
        base = Path(dirpath)
        for name in filenames:
            p = base / name
            try:
                st = p.lstat()
            except OSError:
                continue
            if not os.path.isfile(p) or os.path.islink(p):
                continue
            s.files[p.relative_to(root).as_posix()] = (st.st_size, st.st_mtime_ns, st.st_mode & turn_changes.PERM)
            if len(s.files) >= FILES_MAX:
                s.capped = True
                return s
        if time.monotonic() - t0 > TIME_BUDGET:
            s.capped = True
            return s
    return s


def _lock(ws: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(ws, threading.Lock())


def _dir(root: Path) -> Path:
    return root / turn_changes.DIR / SHADOW


def _load(d: Path) -> dict[str, list]:
    try:
        data = json.loads((d / "index.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d: Path, index: dict[str, list]) -> None:
    tmp = d / "index.json.tmp"
    tmp.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    tmp.replace(d / "index.json")


def _sync(root: Path, s: Scan, protect: frozenset = frozenset()) -> dict[str, list]:
    """影子库跟上 s：size/mtime 没变且对象还在的不重读；变了的读进来按内容存；不在了的删掉（capped 时只增不删）。
    protect = 这一轮基线还要用的对象（tracker.seen 里的 sha），不清。"""
    d = _dir(root)
    (d / "obj").mkdir(parents=True, exist_ok=True)
    old = _load(d)
    index: dict[str, list] = {}
    stored = 0
    sizes: dict[str, int] = {}

    def keep(rel: str, e: list) -> None:
        nonlocal stored
        index[rel] = e
        if e[2] and e[2] not in sizes:
            sizes[e[2]] = e[0]
            stored += e[0]

    pending = []
    for rel, (size, mtime, mode) in s.files.items():
        e = old.get(rel)
        if e and len(e) == 4 and e[0] == size and e[1] == mtime and (not e[2] or (d / "obj" / e[2]).exists()):
            keep(rel, [size, mtime, e[2], mode])  # 权限变了不用重读内容
        else:
            pending.append((rel, size, mtime, mode))
    if s.capped:  # 没扫到的不当成删了
        for rel, e in old.items():
            if rel not in s.files and len(e) == 4:
                keep(rel, e)
    for rel, size, mtime, mode in pending:
        sha = None
        if size <= FILE_MAX and stored + size <= STORE_MAX:
            try:
                raw = (root / rel).read_bytes()
            except OSError:
                continue
            sha = hashlib.sha256(raw).hexdigest()
            obj = d / "obj" / sha
            if not obj.exists():
                tmp = obj.with_suffix(".tmp")
                tmp.write_bytes(raw)
                tmp.replace(obj)
            size = len(raw)
        keep(rel, [size, mtime, sha, mode])
    for obj in (d / "obj").iterdir():  # 没人引用的对象（旧版本、没写完的 .tmp）清掉
        if obj.name not in sizes and obj.name not in protect:
            obj.unlink(missing_ok=True)
    _save(d, index)
    return index


def before(ws: str, tracker: turn_changes.Tracker) -> None:
    """会改东西的命令之前：影子库跟上现状，这一轮第一次见到的文件记进 tracker.seen。"""
    try:
        root = project_dir(ws).resolve()
        with _lock(ws):
            s = scan(root)
            index = _sync(root, s, frozenset(e[2] for e in tracker.seen.values() if e[2]))
        tracker.root = tracker.root or str(root)
        for rel, e in index.items():
            tracker.seen.setdefault(rel, (e[0], e[1], e[2], e[3]))
        tracker.seen_capped = tracker.seen_capped or s.capped
        tracker.scanned = True
    except Exception:
        tracker.seen_capped = True  # 影子库坏了：这条命令只比还能比的


def after(ws: str, tracker: turn_changes.Tracker) -> list[str]:
    """命令之后：把命令期间变了的文件的基线交给 tracker（write_file 先记过的不动）。返回新记的相对路径。"""
    if not tracker.scanned:
        return []
    try:
        root = project_dir(ws).resolve()
        s = scan(root)
        d = _dir(root) / "obj"
        found = []
        for rel in sorted(set(tracker.seen) | set(s.files)):
            key = str(root / rel)
            if key in tracker.base:
                continue
            first, now = tracker.seen.get(rel), s.files.get(rel)
            if first is None:
                if now is None or tracker.seen_capped:
                    continue  # 之前没扫全：没见过 ≠ 新建
                base = None
            elif now is None:
                if s.capped:
                    continue  # 这次没扫全：没看到 ≠ 删了
                base = _object(d, first, tracker)
            elif (first[0], first[1], first[3]) == now:
                continue
            else:
                base = _object(d, first, tracker)
            tracker.base[key] = base
            tracker.modes[key] = first[3] if first else None
            tracker.rel[key] = rel
            tracker.command.add(key)
            found.append(rel)
        tracker.root = tracker.root or str(root)
        return found
    except Exception:
        return []


def _object(d: Path, first: tuple, tracker: turn_changes.Tracker):
    sha, size = first[2], first[0]
    if not sha or tracker.size + size > turn_changes.TURN_MAX:
        return turn_changes.BIG
    try:
        raw = (d / sha).read_bytes()
    except OSError:
        return turn_changes.BIG  # 同一轮并行命令把旧版本清掉了：照样列出，不能撤销
    tracker.size += len(raw)
    return raw
