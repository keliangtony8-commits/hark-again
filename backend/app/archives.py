"""压缩包不解压就看——唯一的规则：.zip / .tar / .tar.gz(.tgz) / .tar.bz2 / .tar.xz / 单文件 .gz 里有什么、怎么读其中一个。

为什么要有：用户问“这压缩包里有什么 / 最大的多大 / 把里面的 xx 念给我”，以前模型只能 unzip 到工作区再看，
看完不收拾，工作区多出一堆 tmp/（真测 r3）。Hark 公开行为是直接回答，不在用户空间里留东西。
所以 read_file 认出压缩包就列目录（大小带单位、最大的几个、加密的、文件夹数），member=“里面的路径”就在内存里读那一个
（文字 / 图片 / PDF·Office 文档 / 里面再套的压缩包都行），工作区一个字节都不写。

规则：
- 认包：扩展名（KINDS）；Office 文档（.docx/.xlsx…）虽然也是 zip，由 documents.py 先认走，不算压缩包；
- 名字：zip 没标 UTF-8 的非 ASCII 名字按 原始字节 → UTF-8 → GBK → cp437 依次试（Windows 中文包多是 GBK）；
- 列表最多 LIST_MAX 行，按路径排序；member="文件夹/" 只列那个文件夹；
- 找成员：精确 → 去掉开头 ./ 和 / → 忽略大小写 → 唯一同名文件；找不到给最像的几个；
- 读成员上限 MEMBER_MAX（声明大小和实际解出来的都卡，防压缩炸弹）；加了密码的不读，提示用 run_command 带密码解压；
- 压缩过的 tar 要从头解一遍才知道目录：包本身超过 TAR_SCAN_MAX 不列，提示 `tar tzf`；最多扫 SCAN_MAX 个条目。
- 模型还是用 run_command 解压了（真测 z3：tar -xzf … && grep）：extract_note 认出解压命令 + 这条命令新建的文件，
  在结果后补一句“只是为了看的话答完删掉 X，下次 read_file member 不用解压”（用户让解压的就留着，由模型判断）。
"""
import bz2
import gzip
import io
import lzma
import re
import tarfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

from .quota import size_text

KINDS = (  # 长的后缀在前
    (".tar.gz", "tar"), (".tar.bz2", "tar"), (".tar.xz", "tar"), (".tgz", "tar"), (".tbz2", "tar"), (".txz", "tar"),
    (".tar", "tar"), (".zip", "zip"), (".gz", "gz"),
)
OTHER = (".7z", ".rar")
LIST_MAX = 300
SCAN_MAX = 20000
TOP_N = 3
MEMBER_MAX = 50 * 1024 * 1024
TAR_SCAN_MAX = 1024 * 1024 * 1024
UTF8_FLAG = 0x800
CHUNK = 1024 * 1024


class ArchiveError(Exception):
    pass


@dataclass
class Entry:
    name: str
    size: int = 0
    mtime: str = ""
    is_dir: bool = False
    encrypted: bool = False
    ref: object = None  # ZipInfo / TarInfo（读成员用）


@dataclass
class Listing:
    kind: str
    entries: list[Entry] = field(default_factory=list)
    truncated: bool = False  # 条目超过 SCAN_MAX，只扫了前面的


def kind_of(name: str) -> str | None:
    low = (name or "").lower()
    for ext, kind in KINDS:
        if low.endswith(ext):
            return kind
    return None


def is_other(name: str) -> bool:
    """7z / rar：标准库读不了，只能 run_command（7z x / unrar）。"""
    return (name or "").lower().endswith(OTHER)


def _src(src: Path | bytes):
    return io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else src


def _size_of(src: Path | bytes) -> int:
    return len(src) if isinstance(src, (bytes, bytearray)) else Path(src).stat().st_size


def zip_name(info: zipfile.ZipInfo) -> str:
    n = info.filename
    if info.flag_bits & UTF8_FLAG or n.isascii():
        return n
    try:
        raw = n.encode("cp437")
    except UnicodeEncodeError:
        return n
    got = []
    for enc in ("utf-8", "gbk"):
        try:
            got.append(raw.decode(enc))
        except UnicodeDecodeError:
            continue
    # 短的 GBK 名字常常也是“合法 UTF-8”（通知 → ֪ͨ）：选非 ASCII 字全是中文/全角标点的那个，都像就 UTF-8
    for name in got:
        if all(c.isascii() or _cjk(c) for c in name):
            return name
    return got[0] if got else n


def _cjk(c: str) -> bool:
    o = ord(c)
    return 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF


def _gz_inner(name: str) -> str:
    base = PurePosixPath(name or "file.gz").name
    return base[:-3] if base.lower().endswith(".gz") and len(base) > 3 else base + ".out"


def entries(src: Path | bytes, name: str) -> Listing:
    """列出包里的条目。坏包 / 不认识 → ArchiveError（一句能照做的话）。"""
    kind = kind_of(name)
    if kind is None:
        raise ArchiveError(f"{name} 不是认得的压缩包（认 .zip / .tar / .tar.gz / .tgz / .tar.bz2 / .tar.xz / .gz）。")
    try:
        if kind == "zip":
            with zipfile.ZipFile(_src(src)) as z:
                infos = z.infolist()
            out = Listing("zip", truncated=len(infos) > SCAN_MAX)
            for i in infos[:SCAN_MAX]:
                out.entries.append(Entry(zip_name(i).rstrip("/") if i.is_dir() else zip_name(i), i.file_size,
                                         "%04d-%02d-%02d %02d:%02d" % i.date_time[:5], i.is_dir(),
                                         bool(i.flag_bits & 0x1), i))
            return out
        if kind == "gz":
            return Listing("gz", [Entry(_gz_inner(name), _gz_size(src))])
        if _size_of(src) > TAR_SCAN_MAX and not str(name).lower().endswith(".tar"):
            raise ArchiveError(f"{name} 有 {size_text(_size_of(src))}，要从头解一遍才知道里面有什么，太大了："
                               f"用 run_command `tar tvf \"{PurePosixPath(name).name}\" | head -300` 看。")
        out = Listing("tar")
        with tarfile.open(fileobj=_src(src) if isinstance(src, (bytes, bytearray)) else None,
                          name=None if isinstance(src, (bytes, bytearray)) else str(src), mode="r:*") as t:
            for n, m in enumerate(t):
                if n >= SCAN_MAX:
                    out.truncated = True
                    break
                if not (m.isfile() or m.isdir()):
                    continue  # 链接 / 设备：不列也不读
                out.entries.append(Entry(m.name.removeprefix("./").rstrip("/"), m.size,
                                         datetime.fromtimestamp(m.mtime).strftime("%Y-%m-%d %H:%M"), m.isdir(), False, m))
        out.entries = [e for e in out.entries if e.name and e.name != "."]
        return out
    except ArchiveError:
        raise
    except (zipfile.BadZipFile, tarfile.TarError, OSError, EOFError, lzma.LZMAError, ValueError) as e:
        raise ArchiveError(f"{name} 打不开（{e.__class__.__name__}），可能文件不完整或不是真的压缩包。") from e


def _gz_size(src: Path | bytes) -> int:
    """gzip 末尾 4 字节记着原始大小（mod 4 GB）。"""
    if isinstance(src, (bytes, bytearray)):
        tail = bytes(src[-4:])
    else:
        with Path(src).open("rb") as f:
            f.seek(-4, 2)
            tail = f.read(4)
    return int.from_bytes(tail, "little") if len(tail) == 4 else 0


def _dirs(entries: list[Entry]) -> set[str]:
    """显式的文件夹条目 + 文件路径里隐含的文件夹（很多 zip 不单独存文件夹条目）。"""
    out = {e.name for e in entries if e.is_dir}
    for e in entries:
        parts = e.name.split("/")[:-1]
        out.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
    return out


def render(label: str, lst: Listing, under: str = "") -> str:
    """给模型的目录：一行总述（文件数、文件夹数、解压后多大、最大的几个、加密几个）+ 每行 大小 时间 路径。"""
    under = under.strip("/")
    files = [e for e in lst.entries if not e.is_dir and (not under or e.name.startswith(under + "/"))]
    dirs = {d for d in _dirs(lst.entries) if not under or d.startswith(under + "/")}
    where = f"里的“{under}/”" if under else ""
    if not files and not dirs:
        return f"{label}{where}：空的，没有文件。"
    total = sum(e.size for e in files)
    head = f"{label}{where}：压缩包，{len(files)} 个文件"
    head += f"、{len(dirs)} 个文件夹" if dirs else ""
    head += f"，解压后共 {size_text(total)}" if lst.kind != "gz" else f"，解压后约 {size_text(total)}"
    big = sorted(files, key=lambda e: -e.size)[:TOP_N] if len(files) > 1 else []
    if big:
        head += "。最大的：" + "、".join(f"{e.name}（{size_text(e.size)}）" for e in big)
    locked = sum(e.encrypted for e in files)
    if locked:
        head += f"。{locked} 个文件加了密码（列得出名字，读不了内容）"
    if lst.truncated:
        head += f"。条目太多，只扫了前 {SCAN_MAX} 个"
    rows = sorted(files + [Entry(d, is_dir=True) for d in dirs], key=lambda e: e.name)
    lines = [f"{'' if e.is_dir else size_text(e.size):>9}  {e.mtime or ' ' * 16:16}  {e.name}{'/' if e.is_dir else ''}"
             f"{'  [有密码]' if e.encrypted else ''}" for e in rows[:LIST_MAX]]
    if len(rows) > LIST_MAX:
        lines.append(f"…还有 {len(rows) - LIST_MAX} 项没列：用 member=\"某个文件夹/\" 只看那个文件夹。")
    same = "同一个 attachment" if label.startswith("附件") else "同一个 path"
    tail = (f"用户问到包里某个文件的内容，就直接读：read_file {same} 加 member=\"里面的路径\"（不用解压、不用先问）。"
            "用户要把文件拿出来用，才 run_command 解压。")
    return f"{head}。\n\n" + "\n".join(lines) + f"\n\n{tail}"


def _norm(s: str) -> str:
    return re.sub(r"^(\./|/)+", "", (s or "").strip().replace("\\", "/"))


def find(lst: Listing, wanted: str) -> Entry | str:
    """member 指哪个：返回 Entry；是文件夹 → 返回文件夹路径（str，调用方列那个文件夹）；找不到 → ArchiveError。"""
    w = _norm(wanted)
    if not w:
        raise ArchiveError("member 是空的：给包里的路径，如 member=\"资料/答案.txt\"。")
    files = [e for e in lst.entries if not e.is_dir]
    if lst.kind == "gz":
        return files[0]
    for match in (lambda e: e.name == w, lambda e: _norm(e.name) == w, lambda e: _norm(e.name).lower() == w.lower()):
        hit = [e for e in files if match(e)]
        if hit:
            return hit[0]
    d = w.rstrip("/")
    if any(x.lower() == d.lower() for x in _dirs(lst.entries)):
        return next(x for x in _dirs(lst.entries) if x.lower() == d.lower())
    base = PurePosixPath(d).name.lower()
    same = [e for e in files if PurePosixPath(e.name).name.lower() == base]
    if len(same) == 1:
        return same[0]
    near = same or [e for e in files if base and base in e.name.lower()] or files
    names = "、".join(e.name for e in near[:8])
    raise ArchiveError(f"包里没有“{wanted}”{'（同名的有好几个，给完整路径）' if len(same) > 1 else ''}。"
                       f"{'有：' + names if names else '包里没有文件。'}")


def read_member(src: Path | bytes, name: str, lst: Listing, e: Entry) -> bytes:
    """在内存里解出一个成员（不落盘）。太大 / 加密 / 坏 → ArchiveError。"""
    if e.encrypted:
        raise ArchiveError(f"{e.name} 加了密码，读不了：问用户要密码后用 run_command 解压（如 `unzip -P 密码 …`），"
                           "看完把解出来的删掉。")
    if e.size > MEMBER_MAX:
        raise ArchiveError(f"{e.name} 解压后有 {size_text(e.size)}，超过 {size_text(MEMBER_MAX)}，"
                           "不在内存里读：要用就 run_command 只解这一个出来。")
    try:
        if lst.kind == "zip":
            with zipfile.ZipFile(_src(src)) as z, z.open(e.ref) as f:
                return _capped(f, e.name)
        if lst.kind == "gz":
            with gzip.open(_src(src)) as f:
                return _capped(f, e.name)
        with tarfile.open(fileobj=_src(src) if isinstance(src, (bytes, bytearray)) else None,
                          name=None if isinstance(src, (bytes, bytearray)) else str(src), mode="r:*") as t:
            f = t.extractfile(e.ref.name)
            if f is None:
                raise ArchiveError(f"{e.name} 不是普通文件，读不了。")
            return _capped(f, e.name)
    except ArchiveError:
        raise
    except RuntimeError as x:  # zip 加密但标记没标准写
        raise ArchiveError(f"{e.name} 读不了（{x}），可能加了密码。") from x
    except (zipfile.BadZipFile, tarfile.TarError, OSError, EOFError, lzma.LZMAError, ValueError, KeyError,
            NotImplementedError) as x:
        raise ArchiveError(f"{e.name} 解不出来（{x.__class__.__name__}），包可能坏了或用了不支持的压缩方式。") from x


def _capped(f, label: str) -> bytes:
    buf = bytearray()
    while chunk := f.read(CHUNK):
        buf += chunk
        if len(buf) > MEMBER_MAX:  # 声明的大小可能是假的（压缩炸弹）
            raise ArchiveError(f"{label} 解出来超过 {size_text(MEMBER_MAX)}，停了：要用就 run_command 只解这一个出来。")
    return bytes(buf)


def decode_text(body: bytes) -> tuple[str, str] | None:
    """成员是不是文字：没有 NUL 且 UTF-8 解得开 → (文字, "")；GBK 解得开且有中文 → (文字, "按 GBK 解码")；否则 None。"""
    if b"\0" in body[:65536]:
        return None
    for enc, note in (("utf-8-sig", ""), ("gbk", "按 GBK 解码")):
        try:
            text = body.decode(enc)
        except UnicodeDecodeError:
            continue
        if note and not re.search(r"[\u4e00-\u9fff]", text):
            return None
        return text, note
    return None


EXTRACT = re.compile(r"\b(?:unzip(?![^|;&]*\s-[A-Za-z]*[lvZ]\b)|gunzip|bsdtar\s+-?x|7za?\s+[xe]\b|gzip\s+-[A-Za-z]*d"
                     r"|tar\s+(?:-[A-Za-z]*x|x[A-Za-z]*\b|--extract))")
NOTE_NAMES = 5


def extract_note(command: str, created: list[str]) -> str:
    """解压命令在工作区新建了文件 → 一句提醒（列出顶层的几个）；不是解压 / 没新建 → 空串。"""
    if not created or not EXTRACT.search(command or ""):
        return ""
    tops = sorted({c.split("/")[0] + ("/" if "/" in c else "") for c in created})
    names = "、".join(tops[:NOTE_NAMES]) + (f" 等 {len(tops)} 项" if len(tops) > NOTE_NAMES else "")
    return (f"（这次解压在工作区新建了 {len(created)} 个文件：{names}。用户只是想知道里面有什么、没让你解压的话，"
            "答完用 run_command 把这些删掉，别在用户的工作区留东西；下次只是看就用 read_file（member 读包里的文件），不用解压。）")

