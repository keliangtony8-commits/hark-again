"""交给用户的 CSV 什么时候加 UTF-8 BOM（v2.65，唯一规则；e2e o8）。

为什么：Windows Excel（以及手机上的 WPS/Excel 部分版本）双击打开没有 BOM 的 UTF-8 CSV 会按本地编码（GBK）解读，
中文全变乱码；加上 EF BB BF 三个字节就认对了。模型几乎从不自己加（pandas to_csv 默认 utf-8 无 BOM），
所以在“交付快照”这一步统一纠正——工作区里的原文件不动（脚本、后续命令读它不受影响）。

规则：
- 只管 .csv / .tsv（Excel 直接打开的表格文本）；别的文本文件不碰。
- 已经有 UTF-8 BOM、或是 UTF-16 BOM 的 → 不碰。
- 全是 ASCII → 不碰（Excel 本来就不会乱码，少改一处是一处）。
- 有非 ASCII 字节，且整篇严格按 UTF-8 解得开 → 加 BOM。解不开（真 GBK 文件）→ 不碰：
  中文 Windows Excel 打开 GBK 本来就正常，硬加 BOM 反而坏。
- 流式检查，大文件不整篇读进内存。"""
import codecs
import shutil
from pathlib import Path
from typing import BinaryIO

SUFFIXES = frozenset({".csv", ".tsv"})
BOM = codecs.BOM_UTF8
CHUNK = 1 << 20


def wants(name: str) -> bool:
    return Path(name).suffix.lower() in SUFFIXES


def needs_bom(f: BinaryIO) -> bool:
    """从当前位置读到尾，按上面的规则判断。调用方负责 seek。"""
    head = f.read(CHUNK)
    if head.startswith(BOM) or head.startswith(codecs.BOM_UTF16_LE) or head.startswith(codecs.BOM_UTF16_BE):
        return False
    dec = codecs.getincrementaldecoder("utf-8")("strict")
    ascii_only = True
    chunk = head
    try:
        while chunk:
            if ascii_only and not chunk.isascii():
                ascii_only = False
            dec.decode(chunk)
            chunk = f.read(CHUNK)
        dec.decode(b"", final=True)
    except UnicodeDecodeError:
        return False
    return not ascii_only


def fix_file(path: Path) -> bool:
    """就地给 path 加 BOM（需要时）。改了返回 True；读写出错原样不动。"""
    if not wants(path.name):
        return False
    tmp = path.with_name(path.name + ".bom")
    try:
        with path.open("rb") as f:
            if not needs_bom(f):
                return False
            f.seek(0)
            with tmp.open("wb") as out:
                out.write(BOM)
                shutil.copyfileobj(f, out, CHUNK)
        tmp.replace(path)
        return True
    except OSError:
        tmp.unlink(missing_ok=True)
        return False


def file_needs(path: Path) -> bool:
    """打包目录时用：这个工作区文件写进 zip 前要不要加 BOM（不改原文件）。"""
    if not wants(path.name):
        return False
    try:
        with path.open("rb") as f:
            return needs_bom(f)
    except OSError:
        return False
