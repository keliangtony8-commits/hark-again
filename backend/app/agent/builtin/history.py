"""search_history：在过去的对话里找以前说过的话，并能翻开某段对话读原文（v2.09）。
规则全在 app/chat_search.py。只读、可并行——所以不碰 ctx.db（共用的会话不能并发），每次自己开一个短会话。"""
from ... import chat_search
from ...db import SessionLocal
from ..tools import ToolContext, ToolResult, tool


@tool("search_history", "正在翻以前的对话",
      "在用户过去的对话里找字（标题和每条消息，含定时任务的报告），或翻开某段对话读原文。用户提到以前聊过、"
      "定过、发过的东西（“上次那家店”“之前说的方案”“我跟你讲过的…”），上下文和记忆里又没有时先用它，不要猜。"
      "给 query 搜（空格分开的词都要有，整句用引号；可加 after / before 限定时间）；"
      "给 conversation（+ 结果里的 message）读那段原文。",
      {"type": "object", "properties": {
          "query": {"type": "string", "description": "关键词，如：咖啡 推荐；整句用引号"},
          "after": {"type": "string", "description": "只看这之后的，YYYY-MM-DD 或 2026-10-12T14:00（用户时区）"},
          "before": {"type": "string", "description": "只看这之前的（含当天），格式同 after"},
          "scope": {"type": "string", "enum": ["all", "here"],
                    "description": "all = 全部对话（默认）；here = 只在当前项目（主聊天里 = 只在主聊天）"},
          "conversation": {"type": "string", "description": "要读原文的对话编号（搜索结果里给的）"},
          "message": {"type": "string", "description": "从这条消息前后读（搜索结果里给的编号）；不填 = 最后几条"}}},
      parallel=True)
async def search_history(ctx: ToolContext, query: str = "", after: str = "", before: str = "", scope: str = "all",
                         conversation: str = "", message: str = "") -> ToolResult:
    try:
        if conversation.strip():
            async with SessionLocal() as db:
                text = await chat_search.read(db, conversation.strip(), message.strip() or None)
            return ToolResult(text, detail="读原文")
        words = chat_search.terms(query)
        if not words:
            return ToolResult("要给 query（关键词），或给 conversation 读某段对话。", failed="没给关键词")
        lo, hi = chat_search.window(after, before)
        where = chat_search.ALL if scope != "here" else ctx.project_id
        async with SessionLocal() as db:
            asking = await chat_search.asking(db, ctx.conversation_id)
            found = await chat_search.search(db, query, scope=where, after=lo, before=hi, skip=asking,
                                             limit=chat_search.TOOL_LIMIT + 1, order="best",
                                             width=chat_search.TOOL_SNIPPET)
            more = len(found) > chat_search.TOOL_LIMIT
            found = found[:chat_search.TOOL_LIMIT]
            names = await chat_search.project_names(db, {h.conversation.project_id for h in found})
    except chat_search.SearchError as e:
        return ToolResult(f"没搜成：{e}", failed=str(e))
    text = chat_search.for_model(query, found, names, ctx.conversation_id, more)
    return ToolResult(text, detail=f"{' '.join(words)} · {len(found)}{'+' if more else ''} 段")
