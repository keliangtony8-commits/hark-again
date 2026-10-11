"""展示类工具：让模型输出结构化卡片，而不是把表格硬塞进文字里。"""
from ...blocks import LinksBlock, StatsBlock, TableBlock
from ..tools import ToolContext, ToolResult, tool


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
