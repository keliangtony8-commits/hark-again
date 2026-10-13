"""把一段字节原子地写进工作区文件（唯一规则）：配额 → 这一轮改动基线 → 临时文件 + os.replace → file_seen → 清配额缓存。

render_document（doc_render）和浏览器截图存文件（browser_shot）共用；附件转存（attachment_save）是流式复制，
走自己的循环但步骤一样。失败抛 quota.QuotaError（调用方换成自己的中文错误）。
"""
import os
import uuid
from pathlib import Path

from . import file_seen, quota
from .storage import project_dir


def put(workspace: str, p: Path, data: bytes, tracker=None, owner: str | None = None) -> bool:
    """写入 p；返回是否覆盖了已有文件。tracker = 这一轮的 turn_changes.Tracker（可 None）。"""
    existed = p.is_file()
    grow = len(data) - (p.stat().st_size if existed else 0)
    quota.check(workspace, max(grow, 0))
    if tracker is not None:
        tracker.before(project_dir(workspace), p)  # 这一轮第一次碰：记基线（整轮撤销能还原 / 删掉）
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{uuid.uuid4().hex[:8]}.part")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)
    file_seen.observe(owner, p)
    quota.forget(workspace)
    return existed
