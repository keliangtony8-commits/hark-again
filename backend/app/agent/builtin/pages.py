"""生成可分享的网页（行程、邀请函、菜单、作品集……）。"""
from ... import pages_store
from ..tools import ToolContext, ToolResult, tool

GUIDE = ("完整的单文件 HTML：内联 CSS，移动端优先（viewport meta），中文字体用系统字体栈，"
         "排版要有设计感（留白、层次、配色统一），不要外链脚本；图片只用确实存在的 https 地址。")


@tool("publish_page", "正在生成网页",
      f"把内容做成一个可分享链接的网页。{GUIDE} 修改已有网页时传入原 slug。",
      {"type": "object", "properties": {
          "title": {"type": "string"}, "html": {"type": "string"},
          "slug": {"type": "string", "description": "更新已有网页时填"}},
       "required": ["title", "html"]})
async def publish_page(ctx: ToolContext, title: str, html: str, slug: str | None = None) -> ToolResult:
    meta = pages_store.save(title, html, slug)
    url = pages_store.url_of(meta["slug"])
    if not meta["published"]:  # 用户下线过：只改内容，不替他重新公开
        return ToolResult(f"内容已更新，但这个网页目前是下线状态，链接打不开（slug: {meta['slug']}）。"
                          "告诉用户：要公开请在 Pages 里点“重新发布”。",
                          [{"type": "page", "slug": meta["slug"], "title": title, "url": url}])
    return ToolResult(f"已发布：{url}（slug: {meta['slug']}）",
                      [{"type": "page", "slug": meta["slug"], "title": title, "url": url}])
