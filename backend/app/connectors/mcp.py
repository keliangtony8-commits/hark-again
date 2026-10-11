"""最小 MCP 客户端（Streamable HTTP 传输，JSON-RPC 2.0）：initialize → tools/list / tools/call。
服务器可能回 JSON，也可能回 SSE（text/event-stream），两种都解析。"""
import json
from itertools import count

import httpx

from .. import vault
from ..models import McpServer

PROTOCOL = "2025-06-18"
_ids = count(1)


class McpError(RuntimeError):
    pass


def _parse(r: httpx.Response) -> dict:
    if "text/event-stream" in r.headers.get("content-type", ""):
        for line in r.text.splitlines():
            if line.startswith("data:"):
                msg = json.loads(line[5:].strip())
                if "result" in msg or "error" in msg:
                    return msg
        raise McpError("SSE 响应里没有结果")
    return r.json()


async def _session(server: McpServer) -> httpx.AsyncClient:
    """握手并返回已带会话头的客户端（调用方负责关闭）。"""
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    if server.token_ciphertext:
        headers["Authorization"] = f"Bearer {vault.decrypt(server.token_ciphertext)}"
    client = httpx.AsyncClient(timeout=60, headers=headers)
    r = await client.post(server.url, json={"jsonrpc": "2.0", "id": next(_ids), "method": "initialize", "params": {
        "protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "assistant", "version": "0.6"}}})
    r.raise_for_status()
    if sid := r.headers.get("mcp-session-id"):
        client.headers["Mcp-Session-Id"] = sid
    await client.post(server.url, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    return client


async def _rpc(server: McpServer, method: str, params: dict) -> dict:
    async with await _session(server) as client:
        r = await client.post(server.url, json={"jsonrpc": "2.0", "id": next(_ids), "method": method, "params": params})
        r.raise_for_status()
        msg = _parse(r)
    if "error" in msg:
        raise McpError(msg["error"].get("message", "MCP 错误"))
    return msg["result"]


async def list_tools(server: McpServer) -> list[dict]:
    return (await _rpc(server, "tools/list", {})).get("tools", [])


async def call_tool(server: McpServer, name: str, arguments: dict) -> str:
    res = await _rpc(server, "tools/call", {"name": name, "arguments": arguments})
    parts = [c.get("text", "") if c.get("type") == "text" else f"[{c.get('type')} 内容]" for c in res.get("content", [])]
    out = "\n".join(parts) or json.dumps(res.get("structuredContent", {}), ensure_ascii=False)
    return ("工具报错：" if res.get("isError") else "") + out
