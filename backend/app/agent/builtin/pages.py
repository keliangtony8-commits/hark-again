"""生成可分享的网页（行程、邀请函、菜单、作品集……）。"""
from ... import conversation_share, pages_store
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


# ---------- 分享当前对话（逻辑全在 conversation_share，与客户端“分享为网页”同一份快照、同一个链接） ----------

def _page_block(state: dict) -> list[dict]:
    return [{"type": "page", "slug": state["slug"], "title": state["title"], "url": state["url"]}]


@tool("share_conversation", "正在分享对话",
      "把当前这段对话做成只读的公开网页快照并给出链接（和用户在菜单里点“分享为网页”是同一个链接）。"
      "只在用户明确要分享 / 要链接 / 要停止分享这段对话时用——页面任何拿到链接的人都能看。"
      "action=share 生成或更新快照（已分享过则原链接覆盖为最新）；unshare 停止分享（链接失效，以后再分享原链接恢复）；"
      "status 查看是否已分享。快照只包含到用户这条消息为止，你正在写的这条回复不在里面。"
      "审批卡、云浏览器画面不会出现，附件只显示文件名。",
      {"type": "object", "properties": {
          "action": {"type": "string", "enum": ["share", "unshare", "status"]}},
       "required": ["action"]},
      scope="conversation")
async def share_conversation(ctx: ToolContext, action: str) -> ToolResult:
    c = await conversation_share.load(ctx.db, ctx.conversation_id) if ctx.conversation_id else None
    if c is None:
        return ToolResult("这里没有可分享的对话。")
    if action == "status":
        st = conversation_share.state(c, c.messages)
        if not st["shared"]:
            return ToolResult("这段对话目前没有公开分享" + ("（以前分享过，已停止）。" if st.get("slug") else "。"))
        return ToolResult(f"已分享：{st['url']}" + ("；快照之后对话又有新内容，需要的话可以 share 更新。" if st["stale"] else "，是最新的。"))
    if action == "unshare":
        st = conversation_share.unshare(c, c.messages)
        if not st.get("slug"):
            return ToolResult("这段对话本来就没有分享过。")
        return ToolResult("已停止分享，原链接现在打不开了；以后再分享会恢复同一个链接。")
    if action != "share":
        return ToolResult("action 只能是 share / unshare / status。")
    st = conversation_share.share(c, c.messages)
    return ToolResult(f"已分享为网页：{st['url']}（只读快照，到用户这条消息为止）。", _page_block(st))
