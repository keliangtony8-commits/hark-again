"""沙盒执行器客户端。后端不接触 Docker，只通过 HTTP 请求独立的 sandbox 服务。"""
import json
from collections.abc import AsyncIterator

import httpx

from .config import settings

STDIN_MAX = 64 * 1024  # 与 sandbox/runner.py 相同


async def stream(project_id: str, command: str, timeout: int = 60, stdin: str | None = None,
                 env: dict[str, str] | None = None) -> AsyncIterator[dict]:
    """前台执行，边跑边产出：{"type":"out","data"} …，最后 {"type":"exit", exit_code, timed_out, output, …}
    或 {"type":"error"}。调用方中途不再读（这一轮被停止）→ 连接关闭 → 沙盒整组杀掉命令。"""
    body = {"project_id": project_id, "command": command, "timeout": timeout}
    if stdin is not None:
        body["stdin"] = stdin
    if env:  # 用户的命令环境变量（app/command_env.py）
        body["env"] = env
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout + 15)) as c:
        async with c.stream("POST", f"{settings.sandbox_url}/exec/stream", json=body,
                            headers={"Authorization": f"Bearer {settings.sandbox_token}"}) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if line.strip():
                    yield json.loads(line)


async def remove(project_id: str) -> None:
    """删除项目时回收它的容器。沙盒服务不在线也不阻塞删除。"""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            await c.delete(f"{settings.sandbox_url}/sandboxes/{project_id}",
                           headers={"Authorization": f"Bearer {settings.sandbox_token}"})
    except httpx.HTTPError:
        pass


async def status(project_id: str) -> dict:
    """容器现状（sandbox/runner.py /sandboxes/{id}/status），只看不启动。连不上抛 httpx.HTTPError。"""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{settings.sandbox_url}/sandboxes/{project_id}/status",
                        headers={"Authorization": f"Bearer {settings.sandbox_token}"})
        r.raise_for_status()
        return r.json()


async def restart(project_id: str) -> None:
    """删掉容器（下次用到自动按最新镜像重建）。和 remove() 不同：失败要抛出来，让用户知道没重启成。"""
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.delete(f"{settings.sandbox_url}/sandboxes/{project_id}",
                           headers={"Authorization": f"Bearer {settings.sandbox_token}"})
        r.raise_for_status()


async def cleanup(project_id: str) -> int:
    """清容器 /tmp 里的下载缓存（不开机），返回腾出的字节。连不上抛 httpx.HTTPError。"""
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{settings.sandbox_url}/sandboxes/{project_id}/cleanup",
                         headers={"Authorization": f"Bearer {settings.sandbox_token}"})
        r.raise_for_status()
        return int(r.json().get("freed") or 0)


async def _job(action: str, project_id: str, job_id: str, env: dict[str, str] | None = None) -> dict:
    body = {"project_id": project_id, "job_id": job_id}
    if env:
        body["env"] = env
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{settings.sandbox_url}/jobs/{action}",
                         headers={"Authorization": f"Bearer {settings.sandbox_token}"}, json=body)
        r.raise_for_status()
        return r.json()


async def start_job(project_id: str, job_id: str, env: dict[str, str] | None = None) -> None:
    """脚本已由 jobs.py 写进工作区 .jobs/<id>/run.sh；这里只叫沙盒脱离启动它。env：每次启动现取（改了变量，重启生效）。"""
    await _job("start", project_id, job_id, env)


async def cancel_job(project_id: str, job_id: str) -> None:
    await _job("cancel", project_id, job_id)


async def job_alive(project_id: str, job_id: str) -> bool:
    return bool((await _job("alive", project_id, job_id)).get("alive"))


async def ports(project_id: str) -> dict:
    """容器里在监听的端口 {state: running|off, ports:[{port, loopback, pid, command}]}，只看不开机。连不上抛 httpx.HTTPError。"""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{settings.sandbox_url}/sandboxes/{project_id}/ports",
                        headers={"Authorization": f"Bearer {settings.sandbox_token}"})
        r.raise_for_status()
        return r.json()


_preview = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=5))


async def preview_send(project_id: str, port: int, method: str, path: str, query: bytes,
                       headers: list[tuple[str, str]], body: bytes) -> httpx.Response:
    """把一次预览请求交给沙盒转进容器（sandbox/runner.py /preview）。返回还没读正文的响应：调用方边读边回，读完 aclose()。
    连不上沙盒抛 httpx.HTTPError；响应头 x-sandbox-preview 缺失 = 是沙盒自己拒的（休眠 503 / 端口上没人 502）。"""
    url = httpx.URL(f"{settings.sandbox_url}/preview/{project_id}/{port}/{path}" + (f"?{query.decode()}" if query else ""))
    req = _preview.build_request(method, url, content=body or None,
                                 headers=[*headers, ("authorization", f"Bearer {settings.sandbox_token}")])
    return await _preview.send(req, stream=True)


async def preview_ws(project_id: str, port: int, path: str, query: str, headers: list[tuple[str, str]],
                     protocols: list[str]):
    """和沙盒的预览 WebSocket 握手（sandbox/runner.py /preview 的 websocket 路由），返回 websockets 连接。
    沙盒拒了（休眠 / 端口上没人）或连不上都抛异常。"""
    import websockets
    base = settings.sandbox_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    uri = f"{base}/preview/{project_id}/{port}/{path}" + (f"?{query}" if query else "")
    return await websockets.connect(uri, subprotocols=protocols or None, open_timeout=15, ping_interval=None,
                                    max_size=16 * 1024 * 1024, proxy=None,
                                    additional_headers=[*headers, ("Authorization", f"Bearer {settings.sandbox_token}")])
