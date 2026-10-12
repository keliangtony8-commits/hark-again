"""“本对话全部文件”的唯一规则（v1.33，对标 Manus“查看本任务全部文件”、Hark 每段对话的文件都能找回）。

一段对话里文件散在各处：你发的附件、引用的工作区文件、助手交付的成果（display_file 快照）、浏览器从网页下载存进
工作区的、传到网页上的、助手用 write_file 写出来的中间文件。这里把它们按“来源”收拢成一张清单，最新的在前，
并能把还在的文件一次打成 zip。

一项 = {"key", "name", "mime", "size", "source", "id", "project_id", "origin", "message_id", "at", "gone"}：
- source/id/project_id 和 FileBlock 同义（upload → 上传 id；project → 工作区相对路径 + 工作区 id），客户端用同一条
  打开规则（uploads 下载 / workspaceFilePath）；
- origin：sent 你发的 | delivered 助手交给你的 | downloaded 网页下载的 | to_web 传到网页的 | written 助手写的；
- gone：文件已经不在（工作区里被删/挪走，或上传存储被清掉）——清单照样列出（知道有过），但打不开、不进 zip；
- 工作区文件的 size 读磁盘当前值（文件会变）；上传快照不变，用块里的值。
同一个文件出现多次（写了又传到网页）只留最近那次。写文件只认“完成”的 write_file 步骤（activity.py 的 detail
就是 path）；run_command 生成的文件不知道名字，不猜——要给用户就 display_file，那时会作为“交给你的”出现。
"""
import shutil
import uuid
import zipfile
from pathlib import Path

from . import storage, workspaces
from .wire_time import iso

ORIGINS = ("sent", "delivered", "downloaded", "to_web", "written")
LIST_MAX = 200  # 一段对话列这么多已经够翻；再多是循环脚本刷出来的
ZIP_MAX_MB = 200  # 打包总大小上限（4GB VPS 的磁盘和内存都要省）


class BundleError(Exception):
    pass


def _upload_file(uid: str) -> Path | None:
    try:
        return storage.upload_path(uid)
    except ValueError:
        return None


WRITERS = ("write_file", "edit_file")  # 时间线里“写了文件”的工具：detail 就是路径


def _locate(item: dict) -> Path | None:
    if item["source"] == "upload":
        return _upload_file(item["id"])
    return storage.project_file(item["project_id"] or "", item["id"])


def _item(source: str, fid: str, name: str, ws: str | None, origin: str, msg, mime: str = "", size: int = 0) -> dict:
    return {"key": f"{source}:{ws or ''}:{fid}", "name": name or Path(fid).name or "file",
            "mime": mime or storage.mime_of(name or fid), "size": size, "source": source, "id": fid,
            "project_id": ws if source == "project" else None, "origin": origin, "message_id": msg.id,
            "at": iso(msg.created_at) if msg.created_at else None}


def _from_message(msg, ws: str) -> list[dict]:
    """一条消息里出现的文件，按发生顺序。"""
    out: list[dict] = []
    user = msg.role == "user"
    # 先步骤（过程：写了哪些文件）再块（结果：交付的卡）——写在交之前，倒序后“交给你的”排在“写的”上面
    for s in msg.steps or []:
        if not isinstance(s, dict) or s.get("state") != "done":
            continue
        files = s.get("changes") or ([s["change"]] if isinstance(s.get("change"), dict) else [])
        if files:  # 带改动摘要的步骤（v1.34 起的 write/edit_file、v1.69 apply_patch）：路径以摘要为准，删掉的不列
            for c in files:
                if isinstance(c, dict) and c.get("path") and not c.get("deleted"):
                    path = str(c["path"]).lstrip("/")
                    out.append(_item("project", path, Path(path).name, ws, "written", msg))
            continue
        if s.get("tool") in WRITERS and s.get("detail"):
            path = str(s["detail"]).lstrip("/")
            if not path.endswith("…"):  # 摘要被截断的长路径认不出是哪个文件，不列
                out.append(_item("project", path, Path(path).name, ws, "written", msg))
    for b in msg.blocks or []:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "file" and b.get("id"):
            src = "project" if b.get("source") == "project" else "upload"
            out.append(_item(src, str(b["id"]), str(b.get("name") or ""), b.get("project_id") or ws,
                             "sent" if user else "delivered", msg, str(b.get("mime") or ""), int(b.get("size") or 0)))
        elif b.get("type") == "browser":
            bws = b.get("workspace") or ws
            for f in b.get("files") or []:
                if isinstance(f, dict) and f.get("path"):
                    origin = "downloaded" if f.get("kind") == "download" else "to_web"
                    out.append(_item("project", str(f["path"]), str(f.get("name") or ""), bws, origin, msg))
    return out


def collect(conversation, messages) -> list[dict]:
    """conversation：Conversation 行（取 project_id 定工作区）；messages：按时间正序。返回最新在前。"""
    ws = workspaces.of(conversation.project_id)
    seen: dict[str, dict] = {}
    for msg in messages:
        for it in _from_message(msg, ws):
            seen.pop(it["key"], None)  # 同一文件再次出现 → 挪到最新位置、用最新来源
            seen[it["key"]] = it
    items = list(reversed(seen.values()))[:LIST_MAX]
    for it in items:
        p = _locate(it)
        it["gone"] = p is None
        if p is not None and it["source"] == "project":
            it["size"] = p.stat().st_size
    return items


def summary(items: list[dict]) -> dict:
    live = [i for i in items if not i["gone"]]
    return {"count": len(items), "available": len(live), "size": sum(i["size"] for i in live),
            "zip_max": ZIP_MAX_MB * 1024 * 1024}  # 客户端据此决定“打包下载”能不能点


def _free(name: str, used: set[str]) -> str:
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        stem, ext = name, ""
    cand, n = name, 2
    while cand in used:
        cand = f"{stem} ({n}).{ext}" if ext else f"{stem} ({n})"
        n += 1
    used.add(cand)
    return cand


def bundle(items: list[dict], title: str) -> tuple[Path, Path]:
    """还在的文件打成一个 zip（扁平，重名加 (2)）。返回 (zip 路径, 要清理的临时目录)。
    一个都没有 → BundleError；总大小超过 ZIP_MAX_MB → BundleError（提示挑着下载）。"""
    files = [(i, p) for i in items if not i["gone"] and (p := _locate(i)) is not None]
    if not files:
        raise BundleError("这个对话里没有还在的文件")
    total = sum(p.stat().st_size for _, p in files)
    if total > ZIP_MAX_MB * 1024 * 1024:
        raise BundleError(f"文件一共 {total / 1024 / 1024:.0f} MB，超过打包上限 {ZIP_MAX_MB} MB，请挑着单个下载")
    tmp = storage.UPLOADS / f".zip-{uuid.uuid4().hex}"
    tmp.mkdir(parents=True)
    safe = "".join(ch for ch in (title or "") if ch not in '\\/:*?"<>|' and ord(ch) >= 32).strip()[:40] or "对话文件"
    out = tmp / f"{safe}.zip"
    used: set[str] = set()
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for it, p in files:
                z.write(p, _free(Path(it["name"]).name or p.name, used))
    except OSError as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise BundleError(f"打包失败：{e}") from e
    return out, tmp
