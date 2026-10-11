"""联网：搜索走自托管 SearXNG（免费、无 Key），抓取用 trafilatura 提正文。"""
import httpx
import trafilatura

from ...config import settings
from ..tools import ToolContext, ToolResult, tool

MAX_PAGE_CHARS = 8000  # 控制 token 成本


@tool("web_search", "正在搜索",
      "联网搜索。需要最新信息、事实核查、价格、新闻时使用。返回标题、链接和摘要。",
      {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]})
async def web_search(ctx: ToolContext, query: str) -> ToolResult:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{settings.searxng_url}/search", params={"q": query, "format": "json"})
        r.raise_for_status()
    results = r.json().get("results", [])[:8]
    if not results:
        return ToolResult("没有搜到结果。")
    lines = [f"{i+1}. {x.get('title','')}\n{x.get('url','')}\n{x.get('content','')[:300]}" for i, x in enumerate(results)]
    return ToolResult("\n\n".join(lines))


@tool("web_fetch", "正在读网页",
      "读取一个网页的正文。搜索摘要不够、需要核实具体内容时使用。",
      {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]})
async def web_fetch(ctx: ToolContext, url: str) -> ToolResult:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 (assistant)"}) as c:
        r = await c.get(url)
        r.raise_for_status()
    text = trafilatura.extract(r.text, include_links=False) or ""
    if not text:
        return ToolResult("这个页面提取不到正文（可能需要 JavaScript 或登录）。")
    return ToolResult(text[:MAX_PAGE_CHARS] + ("\n…（已截断）" if len(text) > MAX_PAGE_CHARS else ""))
