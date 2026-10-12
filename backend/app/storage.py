"""文件系统的唯一入口：项目工作区、聊天附件、用户技能都在 data_dir 下。
所有路径都必须经过 safe_join，杜绝 ../ 越权。"""
import mimetypes
import uuid
from pathlib import Path

from .config import settings

DATA = Path(settings.data_dir)
PROJECTS = DATA / "projects"
UPLOADS = DATA / "uploads"
SKILLS = DATA / "skills"
CAPTIONS = DATA / "captions"  # 图片描述缓存（vision.py）：captions/<上传 id>.txt
TEXT_EXT = {".txt", ".md", ".csv", ".json", ".py", ".js", ".ts", ".tsx", ".html", ".css", ".yml", ".yaml", ".toml", ".sql", ".sh", ".log"}


def safe_join(root: Path, rel: str) -> Path:
    p = (root / rel.lstrip("/")).resolve()
    if p != root.resolve() and root.resolve() not in p.parents:
        raise ValueError("路径越界")
    return p


def project_dir(pid: str) -> Path:
    d = PROJECTS / pid
    d.mkdir(parents=True, exist_ok=True)
    return d


def project_file_root(pid: str) -> Path:
    return (PROJECTS / pid).resolve()


def project_file(pid: str, rel: str) -> Path | None:
    """项目里真实存在的一个文件（相对路径；越界、目录、.git 里的一律 None）。不创建项目目录。"""
    root = PROJECTS / pid
    if not pid or not rel or not root.is_dir():
        return None
    try:
        p = safe_join(root, rel)
    except ValueError:
        return None
    return p if p.is_file() and ".git" not in p.relative_to(root.resolve()).parts else None


def is_text(name: str) -> bool:
    return Path(name).suffix.lower() in TEXT_EXT


def mime_of(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


# ---- 聊天附件：存为 uploads/<id>/<原文件名> ----
def save_upload(name: str, data: bytes) -> dict:
    uid = uuid.uuid4().hex
    d = UPLOADS / uid
    d.mkdir(parents=True)
    safe_name = Path(name).name or "file"
    (d / safe_name).write_bytes(data)
    return {"id": uid, "name": safe_name, "mime": mime_of(safe_name), "size": len(data)}


def upload_path(uid: str) -> Path | None:
    d = safe_join(UPLOADS, uid)
    files = list(d.iterdir()) if d.is_dir() else []
    return files[0] if files else None


def caption_path(uid: str) -> Path:
    return safe_join(CAPTIONS, f"{uid}.txt")
