"""最小 MCP 客户端（Streamable HTTP 传输，JSON-RPC 2.0）：initialize → tools/list / tools/call。
服务器可能回 JSON，也可能回 SSE（text/event-stream），两种都解析。

连不上 / 令牌被拒（Unreachable）是只有用户能修的事：经 guarded() 在主页放一张“需要你亲自处理”的系统提醒
（主体 mcp:<服务器 id>，去处连接器页），下次调通自动收起；工具自己报的错（McpError）不算。"""
import json
from collections.abc import Awaitable
from itertools import count
from typing import TypeVar

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from .. import system_alerts, vault
from ..models import McpServer

T = TypeVar("T")

PROTOCOL = "2025-06-18"
_ids = count(1)


class McpError(RuntimeError):
    pass


class Unreachable(McpError):
    """服务器本身不通：auth=True 是令牌被拒（401/403），否则是连不上 / 超时 / 服务器出错。"""
    def __init__(self, reason: str, auth: bool = False):
        super().__init__(reason)
        self.auth = auth


def _unreachable(e: httpx.HTTPError) -> Unreachable:
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code in (401, 403):
            return Unreachable(f"令牌被拒绝（{code}）", auth=True)
        return Unreachable(f"服务器返回 {code}")
    if isinstance(e, httpx.TimeoutException):
        return Unreachable("连接超时")
    return Unreachable("连不上服务器")


def _parse(r: httpx.Response) -> dict:
    if "text/event-stream" in r.headers.get("content-type", ""):
        for line in r.text.splitlines():
            if line.startswith("data:"):
                msg = json.loads(line[5:].strip())
                if "result" in msg or "error" in msg:
                    return msg
        raise McpError("SSE 响应里没有结果")
    return r.json()


def _client(server: McpServer) -> httpx.AsyncClient:
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    if server.token_ciphertext:
        headers["Authorization"] = f"Bearer {vault.decrypt(server.token_ciphertext)}"
    return httpx.AsyncClient(timeout=60, headers=headers)


async def _handshake(client: httpx.AsyncClient, server: McpServer) -> None:
    """initialize + initialized；服务器给了会话号就带上。"""
    r = await client.post(server.url, json={"jsonrpc": "2.0", "id": next(_ids), "method": "initialize", "params": {
        "protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "assistant", "version": "0.6"}}})
    r.raise_for_status()
    if sid := r.headers.get("mcp-session-id"):
        client.headers["Mcp-Session-Id"] = sid
    await client.post(server.url, json={"jsonrpc": "2.0", "method": "notifications/initialized"})


async def _rpc(server: McpServer, method: str, params: dict) -> dict:
    # 客户端只能 open 一次：先 async with 再握手（v0.97 前先握手再 async with，真服务器上第二步就报错）
    try:
        async with _client(server) as client:
            await _handshake(client, server)
            r = await client.post(server.url, json={"jsonrpc": "2.0", "id": next(_ids), "method": method, "params": params})
            r.raise_for_status()
            msg = _parse(r)
    except httpx.HTTPError as e:
        raise _unreachable(e) from e
    except ValueError as e:  # 回的不是 JSON：地址多半指到了别的网页
        raise Unreachable("回应不是 MCP 格式") from e
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


# ---- 健康：连不上 → 主页提醒；调通 → 收起 ----
def _subject(server: McpServer) -> str:
    return f"mcp:{server.id}"


async def problem(db: AsyncSession, server: McpServer) -> str | None:
    """这个服务器还没恢复的问题："auth"（令牌被拒）| "down"（连不上）| None。连接器页列表用。"""
    found = await system_alerts.active(db, _subject(server))
    return "auth" if "auth" in found else "down" if "down" in found else None


async def guarded(db: AsyncSession, server: McpServer, call: Awaitable[T]) -> T:
    """跑一次对服务器的调用：Unreachable → 放提醒（同一个问题只一次）并提交后原样抛出；
    服务器回了话（成功，或工具自己报 McpError）且之前有问题 → 收起并提交。"""
    try:
        result = await call
    except Unreachable as e:
        await _report(db, server, e)
        raise
    except McpError:
        await _healthy(db, server)
        raise
    await _healthy(db, server)
    return result


async def _report(db: AsyncSession, server: McpServer, e: Unreachable) -> None:
    kind = "auth" if e.auth else "down"
    text = (f"{e}。助手暂时用不了「{server.name}」上的工具。\n\n"
            + ("去连接器页删掉它，用新的令牌重新添加。" if e.auth
               else "确认服务器开着、地址没变（" + server.url[:80] + "）；修好后助手下次调通，这张卡自动收起。"))
    await system_alerts.post(db, subject=_subject(server), once=kind, open="connectors",
                             title=f"MCP「{server.name}」" + ("令牌被拒绝" if e.auth else "连不上"), text=text)
    await db.commit()


async def _healthy(db: AsyncSession, server: McpServer) -> None:
    if await system_alerts.active(db, _subject(server)):  # 平时只多一次查询
        await system_alerts.clear(db, _subject(server))
        await db.commit()


async def forget(db: AsyncSession, server: McpServer) -> None:
    """删掉服务器，连同它的提醒。"""
    await db.delete(server)
    await system_alerts.clear(db, _subject(server))
    await db.commit()


def tool_message(server: McpServer, e: Unreachable) -> str:
    """给模型看的：别再重试，告诉用户。"""
    return (f"MCP 服务器「{server.name}」{e}，现在用不了；已经在主页放了提醒（去连接器页处理）。"
            "请告诉用户，这一轮别再重试它。")
