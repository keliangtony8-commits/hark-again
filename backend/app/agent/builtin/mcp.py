"""调用用户自己的 MCP 服务器。先 mcp_tools 看有什么，再 mcp_call。
工具声明了 readOnlyHint 才免审批，其余一律先问你——外部工具做什么我们无法预知。
mcp_servers（v2.49，对标 Hark 公开的 mcp_servers）：列出 / 添加 / 删除服务器；登记规则只在 app/mcp_servers.py。
要令牌时弹表单卡（purpose=token），令牌直接加密存进这台服务器的记录，模型从头到尾看不到。"""
import json

from sqlalchemy import select

from ... import mcp_servers as MS
from ...connectors import mcp
from ...models import McpServer
from ..approvals import FormReply
from ..tools import ToolContext, ToolResult, nobody, tool

_readonly: dict[tuple[str, str], bool] = {}  # (服务器, 工具) -> 是否只读，mcp_tools 时记下


async def _server(ctx: ToolContext, name: str) -> McpServer | None:
    return await ctx.db.scalar(select(McpServer).where(McpServer.name == name))


@tool("mcp_tools", "正在查看 MCP 工具", "列出某个 MCP 服务器提供的工具及参数。",
      {"type": "object", "properties": {"server": {"type": "string"}}, "required": ["server"]})
async def mcp_tools(ctx: ToolContext, server: str) -> ToolResult:
    s = await _server(ctx, server)
    if not s:
        return ToolResult("没有这个 MCP 服务器。")
    try:
        tools = await mcp.guarded(ctx.db, s, mcp.list_tools(s))
    except mcp.Unreachable as e:
        return ToolResult(mcp.tool_message(s, e))
    for t in tools:
        _readonly[(server, t["name"])] = bool((t.get("annotations") or {}).get("readOnlyHint"))
    return ToolResult("\n\n".join(
        f"{t['name']}：{t.get('description', '')}\n参数：{json.dumps(t.get('inputSchema', {}), ensure_ascii=False)[:800]}"
        for t in tools) or "（没有工具）")


def _risk(args: dict, ctx=None) -> str | None:
    if _readonly.get((args.get("server", ""), args.get("tool", ""))):
        return None
    return f"调用外部工具 {args.get('server')} / {args.get('tool')}"


@tool("mcp_call", "正在调用 MCP 工具", "调用 MCP 服务器上的一个工具。先用 mcp_tools 确认工具名和参数。",
      {"type": "object", "properties": {"server": {"type": "string"}, "tool": {"type": "string"},
                                        "arguments": {"type": "object"}},
       "required": ["server", "tool"]}, risk=_risk)
async def mcp_call(ctx: ToolContext, server: str, tool: str, arguments: dict | None = None) -> ToolResult:
    s = await _server(ctx, server)
    if not s:
        return ToolResult("没有这个 MCP 服务器。")
    try:
        out = await mcp.guarded(ctx.db, s, mcp.call_tool(s, tool, arguments or {}))
    except mcp.Unreachable as e:
        return ToolResult(mcp.tool_message(s, e))
    except mcp.McpError as e:
        return ToolResult(f"工具报错：{e}")
    return ToolResult(out[:12000])


# ---- 登记服务器（v2.49） ----
ACTIONS = ("list", "add", "remove")
TOKEN_FIELD = "token"


def token_card(name: str, url: str, reason: str) -> dict:
    """要令牌的表单卡（blocks.FormBlock，不含 id/state）：值不进卡片、不进历史，只交给这次 add。"""
    from urllib.parse import urlsplit
    note = (reason or "").strip()[:120] or "在服务商的设置 / 开发者页面里生成的访问令牌（API token）"
    return {"type": "form", "purpose": "token", "title": f"添加 MCP「{name}」需要令牌",
            "site": urlsplit(url).hostname or None, "note": note, "action": "连接",
            "fields": [{"name": TOKEN_FIELD, "label": "访问令牌", "kind": "password", "min_length": 4}]}


async def _form(ctx: ToolContext, args: dict) -> dict | None:
    if args.get("action") != "add" or not args.get("needs_token") or ctx.ask is nobody:
        return None
    try:
        url = MS.check_url(args.get("url") or "")
        name = MS.clean_name(args.get("name") or "", url)
    except MS.AddError:
        return None  # run 里再报
    return token_card(name, url, args.get("reason") or "")


def _remove_risk(args: dict, ctx=None) -> str | None:
    if args.get("action") != "remove":
        return None
    return f"删除 MCP 服务器「{(args.get('name') or '')[:40]}」（之后助手用不了它的工具，要用得重新添加）"


@tool("mcp_servers", "正在管理 MCP 服务器",
      "管理用户自己的 MCP 服务器（Streamable HTTP）。list：有哪几台、有没有令牌、上次是否连不上；"
      "add：用户给了 MCP 地址让你接上时用（name 选填，没给就按域名起；先连一次确认能用才保存）。"
      "服务器要令牌时带 needs_token=true，会弹卡让用户亲手填，你看不到令牌——绝不让用户把令牌发在聊天里；"
      "第一次不带令牌被拒，就带 needs_token=true 再调一次。remove：只在用户明确要求删除时用（会先弹卡让用户批准）。"
      "加好后用 mcp_tools / mcp_call 调它的工具。",
      {"type": "object", "properties": {
          "action": {"type": "string", "enum": list(ACTIONS)},
          "name": {"type": "string", "description": "add 选填 / remove 必填：服务器名字"},
          "url": {"type": "string", "description": "add 必填：MCP 地址，如 https://mcp.example.com/mcp"},
          "needs_token": {"type": "boolean", "description": "add：服务器要访问令牌时 true（弹卡让用户填）"},
          "reason": {"type": "string", "description": "needs_token 时一句话：令牌去哪儿弄，显示在卡上"}},
       "required": ["action"]}, risk=_remove_risk, form=_form, deferred=True)
async def mcp_servers(ctx: ToolContext, action: str = "list", name: str = "", url: str = "",
                      needs_token: bool = False, reason: str = "", form: FormReply | None = None) -> ToolResult:
    if action not in ACTIONS:
        return ToolResult(f"action 只能是 {' / '.join(ACTIONS)}。", failed="参数不对")
    if action == "list":
        return ToolResult(await MS.listing(ctx.db), detail="查看 MCP 服务器")
    if action == "remove":
        s = await MS.find(ctx.db, name)
        if s is None:
            return ToolResult(f"没有叫「{name[:40]}」的 MCP 服务器。\n" + await MS.listing(ctx.db),
                              failed="没有这台服务器")
        gone = s.name
        await MS.remove(ctx.db, s)
        return ToolResult(f"已删除 MCP 服务器「{gone}」。", detail=f"删除 {gone}")
    # add
    if not (url or "").strip():
        return ToolResult("add 要带 url（MCP 服务器地址）。没有地址就问用户要，别自己编。", failed="没填地址")
    if needs_token and form is None:
        return ToolResult("现在是后台运行，没人能填令牌。告诉用户到 连接器 → MCP 服务器 里带令牌添加；"
                          "别让用户把令牌发在聊天里。", failed="没人能填令牌")
    token = form.values.get(TOKEN_FIELD, "") if form is not None else ""
    try:
        a = await MS.add(ctx.db, name, url, token, by="agent")
    except MS.AddError as e:
        hint = {"auth": ("用户填的令牌不对：问用户要不要再试一次（再调 add needs_token=true），别反复弹卡。" if token
                         else "带 needs_token=true 再调一次 add，让用户在卡上填令牌。"),
                "dupe": "不用再加。", "blocked": "如实告诉用户，别换地址绕过。",
                "down": "如实告诉用户，别反复重试。"}.get(e.kind, "改好参数再调。")
        return ToolResult(f"没加成：{e} {hint}", failed={"auth": "要令牌", "dupe": "", "blocked": "内网地址",
                                                        "down": "连不上"}.get(e.kind, "参数不对"),
                          detail=(name or url)[:40])
    return ToolResult(MS.added_text(a), detail=f"添加 {a.server.name}")
