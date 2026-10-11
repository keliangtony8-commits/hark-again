"""Pages：我生成的可分享网页。一个 Page = data/pages/<slug>/index.html + meta.json。
公开地址 /p/<slug>/，响应带 CSP sandbox，页面脚本拿不到 App 的登录信息。
meta = {slug, title, updated, published, source?}：published=False 是“下线”——文件留着、公开地址 404（与不存在同一响应，
不暴露页面存在），随时可重新发布，链接不变。元数据只在这里读写（老 meta 没有 published 视为已发布）。
source = 页面从哪来："conversation:<id>" 是“分享对话”生成的快照（conversation_share.py），智能体做的页面没有。
同一对话再分享 = 改写同一个 slug，链接不变；find_by_source 按它找回。"""
import json
import re
import secrets
import time
from pathlib import Path

from .config import settings
from .storage import DATA, safe_join

PAGES = DATA / "pages"
MAX_HTML = 2 * 1024 * 1024


def _slug(title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:30]
    return f"{base or 'page'}-{secrets.token_hex(3)}"  # 随机后缀：链接不可被猜到


def _dir(slug: str) -> Path:
    if not re.fullmatch(r"[a-z0-9-]{1,48}", slug):
        raise ValueError("bad slug")
    return safe_join(PAGES, slug)


def _read(d: Path) -> dict | None:
    try:
        m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    out = {"slug": m.get("slug", d.name), "title": m.get("title", ""), "updated": m.get("updated", 0),
           "published": m.get("published", True) is not False}
    if m.get("source"):
        out["source"] = m["source"]
    return out


def _write(d: Path, meta: dict) -> dict:
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta


def save(title: str, html: str, slug: str | None = None, *, source: str | None = None,
         publish: bool | None = None) -> dict:
    """生成或改写内容。改写已有页面保留它的发布状态（下线的页面改完仍是下线，由用户决定何时重新发布）；
    publish=True 只给用户亲手点的“分享”用（明确要公开）。source 不传则沿用旧值。"""
    if len(html.encode()) > MAX_HTML:
        raise ValueError("页面太大")
    slug = slug if slug and _dir(slug).is_dir() else _slug(title)
    d = _dir(slug)
    old = _read(d)
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(html, encoding="utf-8")
    meta = {"slug": slug, "title": title, "updated": time.time(),
            "published": publish if publish is not None else (old["published"] if old else True)}
    if source or (old and old.get("source")):
        meta["source"] = source or old["source"]
    return _write(d, meta)


def get(slug: str) -> dict | None:
    try:
        d = _dir(slug)
    except ValueError:
        return None
    return _read(d) if (d / "index.html").is_file() else None


def update(slug: str, title: str | None = None, published: bool | None = None) -> dict | None:
    """改标题 / 下线 / 重新发布。不改内容，所以不动 updated（列表顺序 = 内容新旧）。页面不存在 → None。"""
    meta = get(slug)
    if meta is None:
        return None
    if title is not None:
        title = title.strip()
        if not title:
            raise ValueError("标题不能为空")
        meta["title"] = title[:200]
    if published is not None:
        meta["published"] = published
    return _write(_dir(slug), meta)


def public_html(slug: str) -> Path | None:
    """公开访问用：不存在或已下线都返回 None。"""
    meta = get(slug)
    return _dir(slug) / "index.html" if meta and meta["published"] else None


def list_pages() -> list[dict]:
    if not PAGES.is_dir():
        return []
    metas = [m for d in PAGES.iterdir() if d.is_dir() and (d / "index.html").is_file() and (m := _read(d))]
    return sorted(metas, key=lambda m: -m["updated"])


def find_by_source(source: str) -> dict | None:
    """这个来源最近生成的页面（分享对话用；页面不多，扫目录即可）。"""
    return next((m for m in list_pages() if m.get("source") == source), None)


def wire(m: dict) -> dict:
    """协议形状：id 与其他资源统一，url 由服务器地址拼出。"""
    return {**m, "id": m["slug"], "url": url_of(m["slug"])}


def delete(slug: str) -> None:
    d = _dir(slug)
    for f in d.glob("*"):
        f.unlink()
    if d.is_dir():
        d.rmdir()


def url_of(slug: str) -> str:
    return f"{settings.public_url.rstrip('/')}/p/{slug}/"
