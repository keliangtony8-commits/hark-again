"""把工作区里的东西交给用户（v1.22，display_file 工具的唯一实现）。

为什么要“交付”而不是直接指向工作区文件：命令跑出来的图表 / PDF / 表格 / 压缩包常常马上被下一条命令覆盖或删掉，
聊天里那张卡要永远打开的是“交给你那一刻”的版本——所以默认拍一份快照进 uploads/（和聊天附件同一套存储、下载接口、
看图描述缓存），卡片 source=upload。

规则（全在这里）：
- 路径必须在工作区里（safe_join）；隐藏目录（.jobs 完整日志、.spill 长输出）也能交付——用户要“把完整日志发我”时有用。
- 目录：打包成 <目录名>.zip 再交付（跳过 .git/.jobs/.spill、node_modules、__pycache__、.venv 等垃圾）。
- 快照上限 settings.deliver_max_mb：超过时普通文件退回“工作区文件卡”（source=project，之后改动会跟着变，
  隐藏目录里的文件客户端下载不到 → 直接拒绝）；目录打包超限 → 拒绝并建议先挑文件或压缩。
- 空文件、不存在的路径 → DeliverError（模型看到原因，自己改正）。
返回给工具的是 Delivery(block, note)：block = 文件块 dict（blocks.FileBlock 字段），note = 给模型的一句话。"""
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import storage
from .config import settings

MAX_FILES = 10  # 一次最多交付几个（和一条消息最多带的文件数一致）
ZIP_SKIP = frozenset({"node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache", ".cache"})


class DeliverError(Exception):
    pass


@dataclass
class Delivery:
    block: dict
    note: str


def _cap() -> int:
    return settings.deliver_max_mb * 1024 * 1024


def _mb(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB"


def _snapshot(src: Path, name: str) -> dict:
    """拷一份进 uploads/<新 id>/<名字>（大文件也不读进内存）。"""
    uid = uuid.uuid4().hex
    d = storage.UPLOADS / uid
    d.mkdir(parents=True)
    dst = d / (Path(name).name or "file")
    shutil.copyfile(src, dst)
    return {"type": "file", "source": "upload", "id": uid, "name": dst.name, "mime": storage.mime_of(dst.name),
            "size": dst.stat().st_size}


def _zip_dir(src: Path, root: Path) -> Path:
    """目录 → 临时 zip（在 uploads 的临时目录里建，交付后删）。超过上限就中途放弃。"""
    tmp = storage.UPLOADS / f".zip-{uuid.uuid4().hex}"
    tmp.mkdir(parents=True)
    out = tmp / f"{src.name or 'files'}.zip"
    total = 0
    count = 0
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(src.rglob("*")):
                rel = p.relative_to(src)
                if storage.hidden(rel.parts) or ZIP_SKIP.intersection(rel.parts) or not p.is_file():
                    continue
                total += p.stat().st_size
                if total > _cap() * 2:  # 原始体积远超上限，压完也放不下，早点停
                    raise DeliverError(f"目录太大（超过 {_mb(_cap() * 2)} 原始数据），先挑出要给用户的文件或自己压缩后再交付。")
                z.write(p, rel.as_posix())
                count += 1
        if count == 0:
            raise DeliverError(f"{src.relative_to(root)}/ 里没有可交付的文件。")
        if out.stat().st_size > _cap():
            raise DeliverError(f"打包后 {_mb(out.stat().st_size)}，超过交付上限 {settings.deliver_max_mb} MB，"
                               "先挑出要给用户的文件再交付。")
        return out
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def deliver(workspace: str, path: str) -> Delivery:
    root = storage.project_dir(workspace).resolve()
    try:
        p = storage.safe_join(root, path)
    except ValueError:
        raise DeliverError(f"{path} 不在工作区里。")
    if p == root:
        raise DeliverError("不能交付整个工作区，指定一个文件或子目录。")
    rel = p.relative_to(root)
    if p.is_dir():
        z = _zip_dir(p, root)
        try:
            block = _snapshot(z, z.name)
        finally:
            shutil.rmtree(z.parent, ignore_errors=True)
        return Delivery(block, f"{rel}/ 已打包成 {block['name']}（{_mb(block['size'])}）交给用户。")
    if not p.is_file():
        raise DeliverError(f"{path} 不存在（先 list_files 看看实际路径）。")
    size = p.stat().st_size
    if size == 0:
        raise DeliverError(f"{path} 是空文件，检查生成它的命令是否成功。")
    if size <= _cap():
        return Delivery(_snapshot(p, p.name), f"{rel} 已交给用户（{_mb(size)}，聊天里是此刻的版本）。")
    if storage.hidden(rel.parts):
        raise DeliverError(f"{path} 有 {_mb(size)}，超过交付上限 {settings.deliver_max_mb} MB，"
                           "而且在隐藏目录里，用户下载不到——先用命令截取需要的部分另存再交付。")
    block = {"type": "file", "source": "project", "id": rel.as_posix(), "name": p.name, "mime": storage.mime_of(p.name),
             "size": size, "project_id": workspace}
    return Delivery(block, f"{rel} 有 {_mb(size)}，超过快照上限，给用户的是工作区文件卡（之后改动会跟着变，别删它）。")
