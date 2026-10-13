"""联网：搜索走自托管 SearXNG（免费、无 Key）；读网页的规则全在 app/web_page.py（防内网、缓存、PDF/JSON），
出网地址检查在 app/web_guard.py。SearXNG 是我们自己配的内部地址，不经 web_guard。"""
import httpx

from ... import web_page
from ...config import settings
from ..tools import ToolContext, ToolResult, tool

SEARCH_MAX = 8
IMAGE_MAX = 8
SNIPPET = 300
RECENT = {"day": "day", "week": "week", "month": "month", "year": "year"}
RECENT_LABEL = {"day": "一天内", "week": "一周内", "month": "一月内", "year": "一年内"}


async def _searx(params: dict) -> list[dict]:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{settings.searxng_url}/search", params={**params, "format": "json"})
        r.raise_for_status()
    return r.json().get("results", []) or []


def _http(v) -> str:
    v = str(v or "").strip()
    if v.startswith("//"):
        v = "https:" + v
    return v if v.lower().startswith(("http://", "https://")) else ""


@tool("web_search", "正在搜索",
      "联网搜索。需要最新信息、事实核查、价格、新闻时使用。返回标题、链接和摘要；摘要只是片段，"
      "要据此给出价格、规则、期限等用户会照着做的结论时，先 web_fetch 原页核实。新闻 / 近况用 recent 限定时间。",
      {"type": "object", "properties": {
          "query": {"type": "string"},
          "recent": {"type": "string", "enum": list(RECENT), "description": "只要这段时间内发布的结果（新闻、近况）"}},
       "required": ["query"]}, parallel=True)
async def web_search(ctx: ToolContext, query: str, recent: str = "") -> ToolResult:
    params = {"q": query}
    if recent in RECENT:
        params["time_range"] = RECENT[recent]
    results = (await _searx(params))[:SEARCH_MAX]
    if not results:
        return ToolResult("没有搜到结果。" + ("可以放宽时间范围再搜。" if recent in RECENT else ""))
    lines = []
    for i, x in enumerate(results):
        date = str(x.get("publishedDate") or "")[:10]
        lines.append(f"{i+1}. {x.get('title','')}{f'（{date}）' if date else ''}\n{x.get('url','')}\n{str(x.get('content',''))[:SNIPPET]}")
    detail = f"{query} · {RECENT_LABEL[recent]}" if recent in RECENT else None
    return ToolResult("\n\n".join(lines), detail=detail)


@tool("image_search", "正在搜图片",
      "搜网络图片，返回图片地址、缩略图、所在网页和来源。用户想看某样东西长什么样、商品卡 / Home 卡需要配图时用；"
      "拿到的图片地址再交给 show_images / show_products。图片要配它所在网页的来源，不要拿别的网站的图冒充。"
      "要给用户看某个网页现在的样子 → 用 browser_screenshot 截图，不是来这里搜。",
      {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}, parallel=True)
async def image_search(ctx: ToolContext, query: str) -> ToolResult:
    seen, rows = set(), []
    for x in await _searx({"q": query, "categories": "images"}):
        img = _http(x.get("img_src"))
        if not img or img in seen:
            continue
        seen.add(img)
        rows.append((x, img))
        if len(rows) >= IMAGE_MAX:
            break
    if not rows:
        return ToolResult("没有搜到图片。换个更具体的说法（品牌 + 型号 / 地名 + 景点）再试。")
    lines = []
    for i, (x, img) in enumerate(rows):
        page, thumb = _http(x.get("url")), _http(x.get("thumbnail_src"))
        src = str(x.get("source") or "").strip() or (page.split("/")[2] if page else "")
        size = str(x.get("resolution") or "").strip()
        meta = " · ".join(v for v in (src, size) if v)
        lines.append(f"{i+1}. {str(x.get('title') or '').strip() or '（无标题）'}{f'（{meta}）' if meta else ''}\n"
                     f"图片：{img}" + (f"\n缩略图：{thumb}" if thumb and thumb != img else "")
                     + (f"\n所在网页：{page}" if page else ""))
    return ToolResult("\n\n".join(lines), detail=f"{query} · {len(rows)} 张")


@tool("web_fetch", "正在读网页",
      "读取一个网址的内容：网页正文、JSON / 纯文本原样、PDF 抽文字（带页码）。搜索摘要不够、需要核实具体内容时用。"
      "同一网址 15 分钟内再读会用缓存；要最新数据（价格、比分）就把 max_age_seconds 设小（0 = 必须现读）。"
      "不能读内网 / 本机地址。需要登录或 JavaScript 的页面用 browser_open。",
      {"type": "object", "properties": {
          "url": {"type": "string"},
          "max_age_seconds": {"type": "integer", "minimum": 0, "description": "能接受多旧的缓存（秒）"}},
       "required": ["url"]}, parallel=True)
async def web_fetch(ctx: ToolContext, url: str, max_age_seconds: int | None = None) -> ToolResult:
    try:
        page = await web_page.fetch(url, max_age=max_age_seconds)
    except web_page.FetchError as e:
        return ToolResult(str(e), failed=str(e))
    return ToolResult(page.for_model(), detail=page.detail(),
                      failed=f"HTTP {page.status}" if page.status >= 400 else "")
