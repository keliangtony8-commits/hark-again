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
