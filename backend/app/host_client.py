"""宿主机主机代理（deploy/host-agent/host_agent.py）的客户端。只经 unix socket 说话，不走网络；协议和沙盒 /exec/stream 一样。"""
import json
from collections.abc import AsyncIterator

import httpx

from .config import settings


def _client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=settings.host_agent_socket),
                             base_url="http://host", timeout=httpx.Timeout(timeout),
                             headers={"Authorization": f"Bearer {settings.host_agent_token}"})


async def health() -> dict:
    """机器名、系统、内核、开机时长。连不上抛 httpx.HTTPError / OSError。"""
    async with _client(5) as c:
        r = await c.get("/health")
        r.raise_for_status()
        return r.json()


async def stream(command: str, timeout: int) -> AsyncIterator[dict]:
    """边跑边产出 {"type":"out","data"} …，最后 {"type":"exit", exit_code, timed_out, output, total, omitted}。
    调用方不再读（这一轮被停止）→ 连接关闭 → 代理整组杀掉命令。"""
    async with _client(timeout + 15) as c:
        async with c.stream("POST", "/exec/stream", json={"command": command, "timeout": timeout}) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if line.strip():
                    yield json.loads(line)
