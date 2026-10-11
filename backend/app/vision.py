"""图片 → 模型的唯一入口：聊天里上传的图片怎么让模型“看见”。

两条路，按成本选：
- 原图：当前这一问里的图片，且这轮的模型能看图（VISION_MODELS）→ 缩到 IMAGE_MAX_SIDE 以内，作为 image_url 发给模型。
- 描述：更早轮次的图片、或这轮模型不能看图 → 用看图模型（VISION_MODEL）把图写成一段文字描述，
  按上传 id 缓存在磁盘（storage.caption_path），每张图一辈子只描述一次；之后每轮只花几十个字的 token。
这样长对话里不会每轮都重复发整张图，换到不能看图的模型也照样知道图里是什么。

工具返回的图（项目里的图片文件、云浏览器截图）也走这里：for_tool() 按同样的规则，
能看图的模型 → 在工具结果之后补一条带原图的消息（只活在这一轮的工具循环里，不进历史）；
不能看图 → 描述写进工具结果（按图片内容哈希缓存）。"""
import asyncio
import base64
import hashlib
import io
import logging
from pathlib import Path

from . import llm
from .config import settings
from .storage import caption_path, upload_path

IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
RAW_MAX_BYTES = 4 * 1024 * 1024  # 没装 Pillow 时，超过这个大小的图不发原图（改走描述）
CAPTION_CHARS = 600              # 描述最多保留多少字
MAX_CAPTIONS_PER_TURN = 6        # 一轮最多新描述几张（其余先给名字，下轮再补），防止一次性烧钱
MAX_TOOL_IMAGES = 3              # 一步工具调用最多给模型看几张图（多的只给名字）
TOOL_IMAGE_MAX_BYTES = 10 * 1024 * 1024  # 工具读到的图超过这个大小不看
CAPTION_PROMPT = (
    "请客观描述这张图片，供看不到图的助手参考：先一句话说是什么，再写关键细节（人物/物体/场景/布局/颜色/数量）；"
    "图里有文字就尽量原样抄录（表格按行列写）。只输出描述，中文，不超过 300 字。"
)

log = logging.getLogger(__name__)


def is_image(block: dict) -> bool:
    """聊天附件里模型能看的图（项目文件不算：那些用文件工具读）。"""
    return block.get("type") == "file" and block.get("source", "upload") == "upload" and block.get("mime") in IMAGE_MIMES


def accepts_images(alias: str) -> bool:
    return alias in settings.vision_models


def cached_caption(block: dict) -> str | None:
    p = caption_path(block["id"])
    return p.read_text(encoding="utf-8") if p.is_file() else None


def placeholder(block: dict) -> str:
    """图片在文字历史里的样子：有描述带描述，没有就只给名字。"""
    cap = cached_caption(block)
    return f"[图片 {block['name']}：{cap}]" if cap else f"[图片 {block['name']}]"


def data_url(path: Path) -> str | None:
    """缩图并转成 data URL；读不了/太大又没法缩 → None（调用方改走描述）。"""
    return data_url_of(path.read_bytes(), path.suffix)


def data_url_of(raw: bytes, suffix: str = ".jpg") -> str | None:
    try:
        from PIL import Image, ImageOps
    except ImportError:  # 没装 Pillow：小图原样发
        if len(raw) > RAW_MAX_BYTES:
            return None
        mime = {".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}.get(suffix.lower(), "image/jpeg")
        return f"data:{mime};base64,{base64.b64encode(raw).decode()}"
    try:
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
        im.thumbnail((settings.image_max_side, settings.image_max_side))
        if im.mode not in ("RGB", "L"):  # 透明底铺白，统一转 JPEG（体积小，供应商都认）
            bg = Image.new("RGB", im.size, "white")
            bg.paste(im.convert("RGBA"), mask=im.convert("RGBA").getchannel("A"))
            im = bg
        out = io.BytesIO()
        im.convert("RGB").save(out, "JPEG", quality=85)
        return f"data:image/jpeg;base64,{base64.b64encode(out.getvalue()).decode()}"
    except Exception as e:  # noqa: BLE001 — 坏图不该拖垮这一轮
        log.warning("image unreadable: %s", e)
        return None


def image_part(block: dict) -> dict | None:
    path = upload_path(block["id"])
    url = data_url(path) if path else None
    return {"type": "image_url", "image_url": {"url": url}} if url else None


async def describe(block: dict) -> str | None:
    """用看图模型写描述并缓存；失败返回 None（下一轮再试），不抛。"""
    if (cap := cached_caption(block)) is not None:
        return cap
    return await _caption(block["id"], image_part(block), block.get("name", ""))


async def _caption(key: str, part: dict | None, name: str) -> str | None:
    """描述一张图并按 key 缓存（上传 id 或内容哈希）。"""
    p = caption_path(key)
    if p.is_file():
        return p.read_text(encoding="utf-8")
    if part is None:
        return None
    try:
        text = await llm.complete([{"role": "user", "content": [{"type": "text", "text": CAPTION_PROMPT}, part]}],
                                  model=settings.vision_model, kind="vision")
    except Exception as e:  # noqa: BLE001
        log.warning("describe %s failed: %s", name, e)
        return None
    text = " ".join(text.split())[:CAPTION_CHARS]
    if not text:
        return None
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return text


async def describe_missing(blocks: list[dict]) -> None:
    """给还没有描述的图补描述（并发，单轮有上限）。"""
    todo = [b for b in blocks if is_image(b) and cached_caption(b) is None][:MAX_CAPTIONS_PER_TURN]
    if todo:
        await asyncio.gather(*(describe(b) for b in todo))


def content_with_images(text: str, blocks: list[dict]) -> str | list[dict]:
    """当前这一问：文字 + 原图。一张都发不出去就退回纯文字。"""
    parts = [p for b in blocks if is_image(b) and (p := image_part(b))]
    return [{"type": "text", "text": text}, *parts] if parts else text


def text_of(content: str | list | None) -> str:
    """消息内容里的文字部分（多模态内容取 text 片段）。"""
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return content or ""


# ---- 工具返回的图 ----

def _part_of(img) -> dict | None:
    url = data_url_of(img.data, Path(img.name).suffix) if len(img.data) <= TOOL_IMAGE_MAX_BYTES else None
    return {"type": "image_url", "image_url": {"url": url}} if url else None


async def for_tool(images: list, alias: str) -> tuple[str, dict | None]:
    """一步工具调用里收集到的图 → (追加到工具结果的文字, 要补在工具结果之后的消息或 None)。
    images 是 ToolImage(name, data) 列表。能看图 → 原图消息；否则 → 描述文字（按内容哈希缓存）。
    看不了的图（坏图/太大/超过本步上限）只报名字，不抛。"""
    if not images:
        return "", None
    shown, skipped = images[:MAX_TOOL_IMAGES], [i.name for i in images[MAX_TOOL_IMAGES:]]
    parts = [(img, _part_of(img)) for img in shown]
    bad = [img.name for img, part in parts if part is None]
    ok = [(img, part) for img, part in parts if part is not None]
    notes = []
    msg = None
    if ok and accepts_images(alias):
        names = "、".join(img.name for img, _ in ok)
        msg = {"role": "user", "content": [
            {"type": "text", "text": f"（这是刚才工具返回的图片：{names}。这条不是用户说的话，看完继续完成任务。）"},
            *(part for _, part in ok)]}
        notes.append(f"图片 {names} 已附在下一条消息里。")
    elif ok:
        caps = await asyncio.gather(*(
            _caption("sha-" + hashlib.sha256(img.data).hexdigest()[:32], part, img.name) for img, part in ok))
        notes += [f"[图片 {img.name}：{cap}]" if cap else f"[图片 {img.name}：暂时看不了内容]" for (img, _), cap in zip(ok, caps)]
    if bad:
        notes.append(f"这些图打不开或太大：{'、'.join(bad)}。")
    if skipped:
        notes.append(f"一次最多看 {MAX_TOOL_IMAGES} 张，没看的：{'、'.join(skipped)}。")
    return "\n".join(notes), msg
