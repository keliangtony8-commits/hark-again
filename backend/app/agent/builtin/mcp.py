"""调用用户自己的 MCP 服务器。先 mcp_tools 看有什么，再 mcp_call。
工具声明了 readOnlyHint 才免审批，其余一律先问你——外部工具做什么我们无法预知。"""
import json

from sqlalchemy import select

from ...connectors import mcp
from ...models import McpServer
from ..tools import ToolContext, ToolResult, tool

_readonly: dict[tuple[str, str], bool] = {}  # (服务器, 工具) -> 是否只读，mcp_tools 时记下


async def _server(ctx: ToolContext, name: str) -> McpServer | None:
    return await ctx.db.scalar(select(McpServer).where(McpServer.name == name))


@tool("mcp_tools", "正在查看 MCP 工具", "列出某个 MCP 服务器提供的工具及参数。",
      {"type": "object", "properties": {"server": {"type": "string"}}, "required": ["server"]})
async def mcp_tools(ctx: ToolContext, server: str) -> ToolResult:
    s = await _server(ctx, server)
    if not s:
        return ToolResult("没有这个 MCP 服务器。")
    tools = await mcp.list_tools(s)
    for t in tools:
        _readonly[(server, t["name"])] = bool((t.get("annotations") or {}).get("readOnlyHint"))
    return ToolResult("\n\n".join(
        f"{t['name']}：{t.get('description', '')}\n参数：{json.dumps(t.get('inputSchema', {}), ensure_ascii=False)[:800]}"
        for t in tools) or "（没有工具）")


def _risk(args: dict) -> str | None:
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
    return ToolResult((await mcp.call_tool(s, tool, arguments or {}))[:12000])
