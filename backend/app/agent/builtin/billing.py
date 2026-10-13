"""billing_status（v2.39 BRAIN bc，对标 Hark 公开的 billing_status：查套餐、额度和当前用量）：
用户问“这个月花了多少 / 预算还剩多少 / 哪个对话最费钱 / 磁盘还剩多少”时，助手直接答，而不是叫他去翻用量页。
数和文案规则只在 app/billing_status.py（数据全来自 usage.py / quota.py，和用量页一致）。只读、不花模型额度、可并行。"""
from ... import billing_status as B
from ..tools import ToolContext, ToolResult, tool


@tool("billing_status", "正在查用量",
      "查花费与额度：今天/昨天/本月花了多少、预算、最费钱的对话、某天(day)、磁盘还剩多少(别用df)。"
      "scope=overview 总账（默认）/ day + date 某一天 / conversation 这段对话；磁盘上限是工作区配额，不是 df 看到的整台机器。"
      "总账：今天、昨天、本月至今花了多少、和上月同期比、每月预算用了几成（照这速度月底多少）、"
      "花得最多的模型和对话、自动选模型省了多少。"
      "用户问“这个月花了多少钱”“预算还剩多少”“哪个对话最费钱”“昨天用了多少”“磁盘还剩多少”时调它，别凭印象估。",
      {"type": "object", "properties": {
          "scope": {"type": "string", "enum": list(B.SCOPES)},
          "date": {"type": "string", "description": "scope=day 用：YYYY-MM-DD（用户时区）；“昨天”这类先用 resolve_relative_date 算出日期"}}},
      parallel=True, deferred=True)
async def billing_status(ctx: ToolContext, scope: str = "overview", date: str = "") -> ToolResult:
    scope = (scope or "overview").strip().lower()
    if scope not in B.SCOPES:
        return ToolResult(f"scope 只能是 {' / '.join(B.SCOPES)}。", failed="参数不对")
    if scope == "conversation":
        return ToolResult(await B.conversation(ctx.db, ctx.conversation_id), detail="这段对话的用量")
    if scope == "day":
        try:
            d = B.parse_day(date)
        except ValueError as e:
            return ToolResult(str(e), failed="日期不对")
        return ToolResult(await B.day(ctx.db, d, ctx.conversation_id), detail=f"{d.isoformat()} 的用量")
    return ToolResult(await B.overview(ctx.db, ctx.workspace, ctx.conversation_id), detail="本月用量")
