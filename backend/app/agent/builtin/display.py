"""展示类工具：让模型输出结构化卡片，而不是把表格硬塞进文字里。
卡片分工（和客户端 blocks/ 一一对应）：对比 → 表格；要点开的页面 → 链接；一眼要看的数 → 数字卡；
用户拿去发的字 → 草稿卡；用户自己读的长文 → 摘要卡；想看样子 → 图片卡。"""
import asyncio

import httpx

from ...blocks import DraftBlock, ImagesBlock, LinksBlock, StatsBlock, SummaryBlock, TableBlock
from ..tools import ToolContext, ToolResult, tool

MAX_IMAGES = 6
IMAGE_PROBE_TIMEOUT = 6.0


@tool("show_table", "正在整理表格",
      "向用户展示一个对比表（3 列以上、多行同类信息时用）。表格会作为卡片显示，文字里不要再重复表格内容。",
      {"type": "object", "properties": {
          "title": {"type": "string"},
          "columns": {"type": "array", "items": {"type": "string"}},
          "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
          "note": {"type": "string", "description": "一句话结论或推荐"}},
       "required": ["columns", "rows"]})
async def show_table(ctx: ToolContext, columns: list[str], rows: list[list[str]], title: str | None = None,
                     note: str | None = None) -> ToolResult:
    block = TableBlock(title=title, columns=columns, rows=[[str(c) for c in r] for r in rows], note=note)
    return ToolResult("表格已展示给用户。", [block.model_dump()])


@tool("show_links", "正在整理链接",
      "向用户展示 1-3 个他接下来要点开的页面（预订、购买、官网），作为链接卡片显示。",
      {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
          "url": {"type": "string"}, "title": {"type": "string"}, "label": {"type": "string"}}, "required": ["url"]}}},
       "required": ["items"]})
async def show_links(ctx: ToolContext, items: list[dict]) -> ToolResult:
    return ToolResult("链接已展示给用户。", [LinksBlock(items=items).model_dump()])


@tool("show_stats", "正在整理关键数字",
      "展示 1-6 个关键数字（标签 + 数值 + 可选一句变化），每个显示成一块醒目的小卡片。"
      "适合面板和简报里一眼要看的数：气温、日落时间、花费、待办数、价格。数值原样带单位；文字里不要再重复这些数。",
      {"type": "object", "properties": {"items": {"type": "array", "maxItems": 6, "items": {"type": "object", "properties": {
          "label": {"type": "string"}, "value": {"type": "string"}, "note": {"type": "string"}}, "required": ["label", "value"]}}},
       "required": ["items"]})
async def show_stats(ctx: ToolContext, items: list[dict]) -> ToolResult:
    return ToolResult("关键数字已展示给用户。", [StatsBlock(items=items[:6]).model_dump()])


@tool("show_draft", "正在写草稿",
      "把用户要以自己名义发出去的文字（邮件连 Subject 行、微信/短信、帖子、请假条、给别的 AI 的提示词）作为草稿卡展示，"
      "用户可一键复制或分享。正文原样显示，不要用 Markdown；文字里只说草稿之外的事，不要重复正文。",
      {"type": "object", "properties": {
          "title": {"type": "string", "description": "是什么、发给谁，几个字：给房东的邮件"},
          "body": {"type": "string", "description": "完整正文，邮件第一行写 Subject: …"}},
       "required": ["title", "body"]})
async def show_draft(ctx: ToolContext, title: str, body: str) -> ToolResult:
    if not body.strip():
        return ToolResult("草稿正文是空的，没有展示。")
    return ToolResult("草稿已展示给用户。", [DraftBlock(title=title.strip() or "草稿", body=body.strip()).model_dump()])


@tool("show_summary", "正在整理成文",
      "把用户会自己读的长内容（计划、行程、简报、清单、文章摘要）作为一份带标题的文档卡展示，正文用 Markdown（小标题、列表）。"
      "文字里只用一两句说重点，不要重复文档内容。",
      {"type": "object", "properties": {
          "title": {"type": "string", "description": "文档标题：杭州两日行程"},
          "subtitle": {"type": "string", "description": "可选：来源或范围，如 10 月 18–19 日、来自 xx.com"},
          "markdown": {"type": "string"}},
       "required": ["title", "markdown"]})
async def show_summary(ctx: ToolContext, title: str, markdown: str, subtitle: str | None = None) -> ToolResult:
    if not markdown.strip():
        return ToolResult("正文是空的，没有展示。")
    block = SummaryBlock(title=title.strip() or "摘要", subtitle=(subtitle or "").strip() or None, markdown=markdown.strip())
    return ToolResult("文档已展示给用户。", [block.model_dump()])


async def probe_image(client: httpx.AsyncClient, url: str) -> bool:
    """这张图真的能打开吗：状态 < 400 且是图片类型。只读响应头，不下载整张图。"""
    try:
        async with client.stream("GET", url) as r:
            return r.status_code < 400 and r.headers.get("content-type", "").lower().startswith("image/")
    except (httpx.HTTPError, ValueError):
        return False


@tool("show_images", "正在找图",
      "用户想看某样东西长什么样时，展示 1-6 张网络图片（默认 2 张；用户说了几张就几张）。"
      "图片地址必须来自搜索结果或打开过的网页，绝不能自己拼或编；打不开的图会被丢掉。每张配几个字的说明。",
      {"type": "object", "properties": {"items": {"type": "array", "maxItems": MAX_IMAGES, "items": {"type": "object", "properties": {
          "url": {"type": "string"}, "caption": {"type": "string"}}, "required": ["url"]}}},
       "required": ["items"]})
async def show_images(ctx: ToolContext, items: list[dict]) -> ToolResult:
    wanted = [i for i in items if str(i.get("url", "")).lower().startswith(("http://", "https://"))][:MAX_IMAGES]
    if not wanted:
        return ToolResult("没有可用的图片地址（要 http(s) 开头、来自网页的真实地址），没有展示。")
    async with httpx.AsyncClient(timeout=IMAGE_PROBE_TIMEOUT, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 (assistant image check)"}) as client:
        ok = await asyncio.gather(*(probe_image(client, i["url"]) for i in wanted))
    good = [{"url": i["url"], "caption": (i.get("caption") or "").strip() or None} for i, y in zip(wanted, ok) if y]
    bad = len(wanted) - len(good)
    if not good:
        return ToolResult("这些图片地址都打不开（或不是图片），没有展示。换搜索结果里的真实图片地址再试，或者直接给链接。")
    note = f"，另有 {bad} 张打不开已丢掉" if bad else ""
    return ToolResult(f"{len(good)} 张图片已展示给用户{note}。", [ImagesBlock(items=good).model_dump()])
