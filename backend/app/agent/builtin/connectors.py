"""connector_accounts（v2.36 BRAIN bb，对标 Hark 公开的 connector_accounts）：助手看连接器状态、给用户发连接卡、
按用户要求断开。状态与文案规则只在 app/connector_accounts.py；授权流程只在 connectors/oauth.py。"""
from sqlalchemy import select

from ... import connector_accounts as CA
from ...connectors import oauth
from ...models import Connection
from ..tools import ToolContext, ToolResult, nobody, tool

ACTIONS = ("list", "connect", "disconnect")


def _risk(args: dict, ctx=None) -> str | None:
    if args.get("action") != "disconnect" or not (p := CA.find(str(args.get("provider") or ""))):
        return None
    return CA.disconnect_reason(p)


@tool("connector_accounts", "正在查看连接器",
      "管理用户的账户连接器（参数 action + provider=连接器 id；Google 的 Gmail/日历/云端硬盘、GitHub…）。MCP 服务器用 mcp_servers。"
      "list：每个连接器的状态（已连接 / 授权失效 / 可以连接 / 服务器没配）和账户；"
      "connect：要用某个还没连（或失效、想换号）的账户时，在聊天里给用户一张连接卡，用户点了去服务商页面授权——"
      "别再叫用户自己去设置里找；"
      "disconnect：只在用户明确要求断开时用（会先弹卡让用户批准）。",
      {"type": "object", "properties": {
          "action": {"type": "string", "enum": list(ACTIONS)},
          "provider": {"type": "string", "description": "connect / disconnect 必填：连接器 id，如 google、github（list 里有）"},
          "reason": {"type": "string", "description": "connect 用：一句话说连上要做什么，显示在卡上（如：读你的日历排明天的事）"}},
       "required": ["action"]}, risk=_risk, deferred=True)
async def connector_accounts(ctx: ToolContext, action: str = "list", provider: str = "", reason: str = "") -> ToolResult:
    if action not in ACTIONS:
        return ToolResult(f"action 只能是 {' / '.join(ACTIONS)}。", failed="参数不对")
    if action == "list":
        return ToolResult(await CA.listing(ctx.db), detail="查看连接器")
    if not (provider or "").strip():
        return ToolResult("没填 provider：带上连接器 id 再调一次（如 action=connect, provider=github）。"
                          "先别下结论。可选的 id：\n" + await CA.listing(ctx.db), failed="没填 provider")
    p = CA.find(provider)
    if p is None:
        return ToolResult(f"没有叫「{provider}」的连接器（provider 填下面括号里的 id）。\n" + await CA.listing(ctx.db),
                          failed=f"没有「{provider[:20]}」这个连接器", detail=provider[:40] or None)
    a = await CA.one(ctx.db, p)
    if action == "connect":
        if why := CA.refuse_connect(a):
            return ToolResult(why, failed="服务器没配这个应用")
        if ctx.ask is nobody:  # 定时任务 / 后台：没人点卡
            return ToolResult(f"现在是后台运行，没人能点连接卡。用 schedule_task action=report_wall wall=needs_connector:{p.id} 记下来，"
                              f"用户连好 {p.name} 后这个任务会自动重跑。", failed="没人能连接")
        return ToolResult(CA.connect_text(a), [CA.card(a, reason)], detail=f"连接 {p.name}")
    # disconnect（已过审批）
    conn = await ctx.db.scalar(select(Connection).where(Connection.provider == p.id))
    if conn is None:
        return ToolResult(f"{p.name} 本来就没连，不用断开。", detail=f"断开 {p.name}")
    await oauth.forget(ctx.db, conn)
    return ToolResult(f"已断开 {p.name}（{a.account}）。之后要用得重新连接。", detail=f"断开 {p.name}")
