"""分享对话 = 把对话做成一张只读的公开网页快照（Pages 的一种，source="conversation:<id>"）。
唯一入口：load / share / unshare / state，路由 routes/conversations.py 与工具 agent/builtin/pages.py share_conversation 只转发。
- 快照：分享那一刻的内容；对话之后有新消息 → state 里 stale=True，客户端提示“更新分享”，同一链接覆盖。
- 停止分享 = 页面下线（pages_store 的 published=False），链接保留，再分享原链接复活。
- 只放对外安全的东西：文字 / 代码 / 表格 / 链接 / 数字卡 / 草稿 / 摘要文档 / 网络图片 / 生成的网页链接；
  审批卡、云浏览器画面不放，附件只写文件名（附件下载要登录，公开页给不了）。
- 页面是服务端渲染的纯 HTML（不带脚本），Markdown 只认常用子集，先转义再加标签，杜绝注入。"""
import html
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from . import pages_store
from .config import settings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import Conversation, Message


def source_of(cid: str) -> str:
    return f"conversation:{cid}"


# ---------- Markdown 子集 → HTML ----------

_SAFE_URL = re.compile(r"^https?://", re.I)


def _inline(s: str) -> str:
    """单行内：先整体转义，再还原 `code`、**粗**、*斜*、[文字](https://…)。"""
    codes: list[str] = []

    def keep_code(m: re.Match) -> str:
        codes.append(f"<code>{m.group(1)}</code>")
        return f"\x00{len(codes) - 1}\x00"

    s = html.escape(s, quote=True)
    s = re.sub(r"`([^`]+)`", keep_code, s)

    def link(m: re.Match) -> str:
        text, url = m.group(1), html.unescape(m.group(2))
        if not _SAFE_URL.match(url):
            return text
        return f'<a href="{html.escape(url, quote=True)}" rel="noopener nofollow" target="_blank">{text}</a>'

    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?![\*\w])", r"<em>\1</em>", s)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], s)


def markdown(text: str) -> str:
    out: list[str] = []
    lines = text.replace("\r\n", "\n").split("\n")
    i, para, lst = 0, [], None  # lst = ("ul"|"ol", [items])

    def flush():
        nonlocal para, lst
        if para:
            out.append("<p>" + "<br>".join(_inline(p) for p in para) + "</p>")
            para = []
        if lst:
            out.append(f"<{lst[0]}>" + "".join(f"<li>{_inline(x)}</li>" for x in lst[1]) + f"</{lst[0]}>")
            lst = None

    while i < len(lines):
        line = lines[i]
        fence = re.match(r"^\s*```\s*([\w+-]*)", line)
        if fence:
            flush()
            body = []
            i += 1
            while i < len(lines) and not re.match(r"^\s*```", lines[i]):
                body.append(lines[i])
                i += 1
            out.append(_pre("\n".join(body), fence.group(1)))
        elif m := re.match(r"^(#{1,6})\s+(.*)", line):
            flush()
            level = min(max(len(m.group(1)), 2), 4)  # 页面 h1 是对话标题：# 与 ## 都算 h2
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
        elif m := re.match(r"^\s*([-*+]|\d+[.)])\s+(.*)", line):
            if para:
                flush()
            kind = "ol" if m.group(1)[0].isdigit() else "ul"
            if lst and lst[0] != kind:
                flush()
            lst = lst or (kind, [])
            lst[1].append(m.group(2))
        elif m := re.match(r"^>\s?(.*)", line):
            flush()
            out.append(f"<blockquote>{_inline(m.group(1))}</blockquote>")
        elif re.match(r"^\s*(---|\*\*\*)\s*$", line):
            flush()
            out.append("<hr>")
        elif not line.strip():
            flush()
        else:
            if lst:
                flush()
            para.append(line)
        i += 1
    flush()
    return "\n".join(out)


def _pre(source: str, language: str = "") -> str:
    lang = f'<span class="lang">{html.escape(language)}</span>' if language else ""
    return f"<pre>{lang}<code>{html.escape(source)}</code></pre>"


# ---------- 块 → HTML ----------

def block_html(b: dict) -> str:
    t, e = b.get("type"), html.escape
    if t == "text":
        return markdown(b.get("text", ""))
    if t == "code":
        title = f'<div class="cap">{e(b["title"])}</div>' if b.get("title") else ""
        return title + _pre(b.get("source", ""), b.get("language", ""))
    if t == "table":
        head = "".join(f"<th>{e(c)}</th>" for c in b.get("columns", []))
        rows = "".join("<tr>" + "".join(f"<td>{_inline(str(c))}</td>" for c in r) + "</tr>" for r in b.get("rows", []))
        cap = f"<caption>{e(b['title'])}</caption>" if b.get("title") else ""
        note = f'<div class="cap">{e(b["note"])}</div>' if b.get("note") else ""
        return f'<div class="table"><table>{cap}<thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>{note}'
    if t == "links":
        items = [it for it in b.get("items", []) if _SAFE_URL.match(it.get("url", ""))]
        lis = "".join(
            f'<li><a href="{e(it["url"], quote=True)}" rel="noopener nofollow" target="_blank">'
            f'{e(it.get("title") or it.get("label") or it["url"])}</a></li>' for it in items)
        return f'<ul class="links">{lis}</ul>' if lis else ""
    if t == "stats":
        cells = "".join(
            f'<div class="stat"><div class="label">{e(s["label"])}</div><div class="value">{e(s["value"])}</div>'
            + (f'<div class="note">{e(s["note"])}</div>' if s.get("note") else "") + "</div>" for s in b.get("items", []))
        return f'<div class="stats">{cells}</div>'
    if t == "page" and _SAFE_URL.match(b.get("url", "")):
        return (f'<a class="chip" href="{e(b["url"], quote=True)}" rel="noopener" target="_blank">'
                f'网页 · {e(b.get("title", ""))}</a>')
    if t == "file":
        return f'<span class="chip">附件 · {e(b.get("name", ""))}</span>'
    if t == "draft":
        return (f'<div class="draft"><div class="cap">草稿 · {e(b.get("title", ""))}</div>'
                f'<div class="draft-body">{e(b.get("body", ""))}</div></div>')
    if t == "summary":
        sub = f'<div class="cap">{e(b["subtitle"])}</div>' if b.get("subtitle") else ""
        return f'<article class="doc"><h3>{e(b.get("title", ""))}</h3>{sub}{markdown(b.get("markdown", ""))}</article>'
    if t == "images":
        figs = "".join(
            f'<figure><img src="{e(it["url"], quote=True)}" alt="{e(it.get("caption") or "")}" loading="lazy" '
            f'referrerpolicy="no-referrer">' + (f'<figcaption>{e(it["caption"])}</figcaption>' if it.get("caption") else "")
            + "</figure>" for it in b.get("items", []) if _SAFE_URL.match(it.get("url", "")))
        return f'<div class="images">{figs}</div>' if figs else ""
    return ""  # approval / browser / 未知：不公开


def _message_html(m: Message) -> str:
    inner = "".join(block_html(b) for b in (m.blocks or []))
    if not inner.strip():
        return ""
    if m.status == "stopped":
        inner += '<div class="cap">（回复中途停止）</div>'
    return f'<section class="msg {"user" if m.role == "user" else "ai"}">{inner}</section>'


CSS = """
:root{--bg:#faf9f7;--card:#fff;--text:#1c1b1a;--text2:#6b6762;--ink:#22201e;--on-ink:#faf9f7;--line:rgba(28,27,26,.1);
--tile:rgba(28,27,26,.05);--accent:#b94f27;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#131418;--card:#1b1c21;--text:#ebebed;--text2:#a4a3aa;--ink:#ece7df;
--on-ink:#131418;--line:rgba(255,255,255,.1);--tile:rgba(255,255,255,.05);--accent:#ef7a4f}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC",
"HarmonyOS Sans SC","Microsoft YaHei","Noto Sans SC",sans-serif;font-variant-numeric:tabular-nums}
main{max-width:720px;margin:0 auto;padding:48px 20px 64px}
header{margin-bottom:32px}
h1{font:500 28px/1.3 "Noto Serif SC","Source Han Serif SC","Songti SC",Georgia,serif;margin:0 0 8px;letter-spacing:.01em}
.meta{color:var(--text2);font-size:13px}
.msg{margin:0 0 16px;overflow-wrap:anywhere}
.msg.user{margin-left:auto;max-width:85%;width:fit-content;background:var(--ink);color:var(--on-ink);
border-radius:20px 20px 6px 20px;padding:10px 16px}
.msg.user a{color:inherit}
.msg.ai{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:16px 20px}
.msg>:first-child{margin-top:0}.msg>:last-child{margin-bottom:0}
h2,h3,h4{font-weight:600;line-height:1.4;margin:20px 0 8px}h2{font-size:19px}h3{font-size:17px}h4{font-size:16px}
p{margin:0 0 12px}ul,ol{margin:0 0 12px;padding-left:22px}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
blockquote{margin:0 0 12px;padding-left:12px;border-left:3px solid var(--line);color:var(--text2)}
hr{border:0;border-top:1px solid var(--line);margin:16px 0}
code{font:13px/1.6 "JetBrains Mono","SF Mono",ui-monospace,Menlo,monospace;background:var(--tile);border-radius:6px;padding:1px 5px}
pre{position:relative;background:var(--tile);border-radius:12px;padding:14px 16px;overflow-x:auto;margin:0 0 12px}
pre code{background:none;padding:0}
.lang{position:absolute;top:6px;right:12px;font-size:11px;color:var(--text2)}
.table{overflow-x:auto;margin:0 0 12px}
table{border-collapse:collapse;width:100%;font-size:14px}
caption{text-align:left;font-weight:600;padding-bottom:6px}
th,td{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
th{color:var(--text2);font-weight:500}
.cap{color:var(--text2);font-size:13px;margin:0 0 12px}
.links{list-style:none;padding:0}.links li{padding:6px 0;border-bottom:1px solid var(--line)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:0 0 12px}
.stat{background:var(--tile);border-radius:14px;padding:12px 14px}
.stat .label,.stat .note{color:var(--text2);font-size:12px}
.stat .value{font:500 22px/1.3 "Noto Serif SC","Songti SC",Georgia,serif}
.chip{display:inline-block;background:var(--tile);border-radius:999px;padding:4px 12px;font-size:13px;margin:0 6px 12px 0}
.msg.user .chip{background:rgba(255,255,255,.15)}
.draft{background:var(--tile);border-radius:14px;padding:12px 16px;margin:0 0 12px}
.draft .cap{margin-bottom:6px}.draft-body{white-space:pre-wrap}
.doc{border:1px solid var(--line);border-radius:16px;padding:14px 18px;margin:0 0 12px}.doc h3{margin-top:0}
.images{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;margin:0 0 12px}
.images figure{margin:0}.images img{width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:14px;background:var(--tile)}
figcaption{color:var(--text2);font-size:13px;margin-top:4px}
footer{color:var(--text2);font-size:12px;text-align:center;margin-top:40px}
"""


def render(c: Conversation, messages: list[Message], now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    body = "\n".join(h for m in messages if (h := _message_html(m)))
    title = html.escape(c.title or "对话")
    stamp = now.astimezone(ZoneInfo(settings.timezone)).strftime("%Y-%m-%d %H:%M")
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta name="robots" content="noindex"><title>{title}</title><style>{CSS}</style></head>'
        f'<body><main><header><h1>{title}</h1><div class="meta">对话快照 · {stamp}</div></header>'
        f'{body or "<p class=cap>这个对话还没有内容。</p>"}'
        '<footer>只读快照，由我的助手生成</footer></main></body></html>')


# ---------- 对外入口 ----------

async def load(db: AsyncSession, cid: str) -> Conversation | None:
    """带消息读出对话（快照要全部消息）。不存在 → None。"""
    return await db.scalar(select(Conversation).where(Conversation.id == cid)
                           .options(selectinload(Conversation.messages)))


def _last_change(c: Conversation, messages: list[Message]) -> float:
    times = [m.created_at for m in messages if m.created_at] + ([c.updated_at] if c.updated_at else [])
    if not times:
        return 0
    t = max(x if x.tzinfo else x.replace(tzinfo=timezone.utc) for x in times)
    return t.timestamp()


def state(c: Conversation, messages: list[Message]) -> dict:
    """{shared: False} 或页面 wire + stale（对话在快照之后又变了）。"""
    page = pages_store.find_by_source(source_of(c.id))
    if not page:
        return {"shared": False}
    return {**pages_store.wire(page), "shared": page["published"], "stale": _last_change(c, messages) > page["updated"]}


def share(c: Conversation, messages: list[Message]) -> dict:
    """生成或刷新快照并公开（用户亲手点的，所以下线过的也重新发布）。链接不变。"""
    old = pages_store.find_by_source(source_of(c.id))
    page = pages_store.save(c.title or "对话", render(c, messages), old["slug"] if old else None,
                            source=source_of(c.id), publish=True)
    return {**pages_store.wire(page), "shared": True, "stale": False}


def unshare(c: Conversation, messages: list[Message]) -> dict:
    page = pages_store.find_by_source(source_of(c.id))
    if page and page["published"]:
        pages_store.update(page["slug"], published=False)
    return state(c, messages)
