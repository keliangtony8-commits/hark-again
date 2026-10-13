"""把云浏览器当前画面存成工作区里的图片文件、交给用户（唯一规则在这里）。

为什么要有（本地 E2E B5）：用户说“截个图给我”，模型只有 browser_look（截给自己看、不落文件），
于是去 image_search 搜“example.com 截图”冒充。Hark 的做法是截图 = 工作区文件 + 文件卡交付。三家参考
（Codex / Gemini CLI / deepseek-harness）没有托管浏览器，规则自己定：
- target(root, site, path)：path 空 → screenshots/<网站>.png；以 / 结尾或是已有目录 → 里面放 <网站>.png；
  没后缀 → 加 .png；后缀只能 .png / .jpg / .jpeg（格式跟后缀走）；逃出工作区 / 隐藏目录 → ShotError
  （路径解析复用 attachment_save.target，同一套说法）。
- 从不覆盖：重名 → “名字 (2).png”（同一页面多截几张都留着）。
- 写入走 workspace_write.put（配额、整轮撤销、原子写）。
- full_page：整页长图，高过 MAX_H 只留最上面（浏览器服务裁，X-Shot-Cut）。
"""
from dataclasses import dataclass
from pathlib import Path

from . import attachment_save, quota, workspace_write
from .storage import project_dir, sandbox_rel

DIR = "screenshots"
FORMATS = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg"}
JPEG_QUALITY = 85
MAX_H = 16_384  # 和 browser/service.py RENDER_PNG_MAX_H 一致
NAME_MAX = attachment_save.NAME_MAX


class ShotError(Exception):
    """存不了：消息给模型看（中文、能照做）。"""


@dataclass
class Shot:
    rel: str
    size: int
    fmt: str             # png | jpeg
    width: int | None
    height: int | None
    full_page: bool
    cut: bool            # 整页太长，只留了最上面 MAX_H 像素
    renamed: bool        # 重名换了名字


def _stem(site: str) -> str:
    s = "".join(c if c.isalnum() or c in "-_." else "-" for c in (site or "").strip()).strip("-.")
    return s[:60] or "page"


def target(root: Path, site: str, path: str = "") -> tuple[Path, str]:
    """截图该放到哪 + 格式（还没处理重名）。"""
    raw = (path or "").strip().replace("\\", "/")
    name = f"{_stem(site)}.png"
    rel = raw if (inner := sandbox_rel(raw)) is None else inner
    if not rel or rel in (".", "./"):
        raw = f"{DIR}/"
    try:
        p = attachment_save.target(root, name, raw)
    except attachment_save.SaveError as e:
        raise ShotError(str(e).replace("存不了", "截图存不了")) from None
    ext = p.suffix.lower()
    if not ext:
        p = p.with_name(p.name + ".png")
        ext = ".png"
    if ext not in FORMATS:
        raise ShotError(f"截图只能存成 .png / .jpg，{p.name} 不行。")
    return p, FORMATS[ext]


def free(p: Path) -> Path:
    """不覆盖：已有同名（文件或目录）→ 名字 (2)、(3)……"""
    q = p
    for n in range(2, NAME_MAX + 2):
        if not q.exists():
            return q
        q = attachment_save.numbered(p, n)
    raise ShotError(f"{p.name} 重名的太多了，换个名字或目录。")


def dims(data: bytes) -> tuple[int | None, int | None]:
    """PNG / JPEG 头里的宽高；认不出 → (None, None)。"""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            length = int.from_bytes(data[i + 2:i + 4], "big")
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
            i += 2 + length
    return None, None


def save(workspace: str, p: Path, data: bytes, fmt: str, full_page: bool, cut: bool,
         tracker=None, owner: str | None = None, first: Path | None = None) -> Shot:
    """把截图字节写进 p（已经过 free）。配额不够 → ShotError。"""
    if not data:
        raise ShotError("浏览器没给回截图（空的），过一会儿再试或先 browser_read 看看页面还在不在。")
    try:
        workspace_write.put(workspace, p, data, tracker, owner)
    except quota.QuotaError as e:
        raise ShotError(f"没有存：{e}") from None
    w, h = dims(data)
    rel = p.relative_to(project_dir(workspace)).as_posix()
    return Shot(rel, len(data), fmt, w, h, full_page, cut, first is not None and p != first)


def detail(s: Shot) -> str:
    size = f" · {s.width}×{s.height}" if s.width and s.height else ""
    return s.rel + size


def for_model(s: Shot, shown: bool) -> str:
    what = "整页长图" if s.full_page else "当前画面"
    size = f"，{s.width}×{s.height}" if s.width and s.height else ""
    lines = [f"已把{what}截图存到 {s.rel}（{quota.size_text(s.size)}{size}）"
             + ("，原名已被占用，换了名字。" if s.renamed else "。")]
    if s.cut:
        lines.append(f"页面太长，只截了最上面 {MAX_H} 像素。")
    lines.append("已经作为文件卡交给用户了，回复里不用再贴图或找图。" if shown
                 else f"没有交给用户（show=false）；要看内容用 read_file {s.rel}。")
    return "\n".join(lines)
