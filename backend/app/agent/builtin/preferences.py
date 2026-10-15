"""set_reply_language（v2.67 BRAIN）：用户说“以后都用英文回答 / 改回跟着我说的语言”时改设置，而不是记成一条可能挑不中的记忆。
规则只在 app/reply_language.py；和 我的 → 偏好设置 是同一个开关。按需工具（不常用，不占每轮的工具段）。"""
from ... import reply_language as L
from ..tools import ToolContext, ToolResult, tool


@tool("set_reply_language", "正在改回复语言",
      "改用户的回复语言设置（和 我的 → 偏好设置 同一个开关）。用户要求以后都用某种语言回答（“以后用英文回我”“改回中文”）"
      "或改回跟随他的语言时调；只是这一句要翻译/换语言时不要调。"
      f"code：{' / '.join(L.CODES)}（auto = 跟随用户这句话的语言）。",
      {"type": "object", "properties": {"code": {"type": "string", "enum": list(L.CODES)}}, "required": ["code"]},
      deferred=True)
async def set_reply_language(ctx: ToolContext, code: str) -> ToolResult:
    try:
        saved = await L.set(ctx.db, code)
    except ValueError as e:
        return ToolResult(str(e), failed="不支持的语言")
    return ToolResult(L.changed_text(saved), detail=L.choice(saved).label)


from ... import identity as I  # noqa: E402  v2.92 §P：称呼与助手名，和 我的 → 点名字 是同一份设置


@tool("set_names", "正在保存称呼",
      "保存用户希望被怎么称呼（display_name）和/或用户给你取的名字（assistant_name），和 我的 → 点名字 是同一份设置。"
      "用户回答初次见面的问题、或以后说“叫我…”“以后你就叫…”时调。只传用户这次说了的那一项；传空字符串 = 清除"
      f"（助手名清除后叫回 {I.APP_NAME}）。每项最多 {I.NAME_MAX} 个字。",
      {"type": "object", "properties": {"display_name": {"type": "string"}, "assistant_name": {"type": "string"}}},
      deferred=True)
async def set_names(ctx: ToolContext, display_name: str | None = None, assistant_name: str | None = None) -> ToolResult:
    kw = {k: v for k, v in (("display_name", display_name), ("assistant_name", assistant_name)) if v is not None}
    if not kw:
        return ToolResult("没有要改的：至少传 display_name 或 assistant_name 之一。", failed="没有要改的")
    try:
        saved = await I.set_names(ctx.db, **kw)
    except ValueError as e:
        return ToolResult(str(e), failed="名字不合适")
    return ToolResult(I.changed_text(saved), detail=saved.display_name or saved.assistant)
