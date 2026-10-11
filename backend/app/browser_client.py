"""云浏览器客户端。后端不运行浏览器，只通过 HTTP 调 browser 服务。
单用户只用一个持久会话 SESSION，登录状态跨对话保留。"""
import httpx

from .config import settings

SESSION = "main"


def _h() -> dict:
    return {"Authorization": f"Bearer {settings.browser_token}"}


async def call(method: str, path: str, json: dict | None = None) -> httpx.Response:
    async with httpx.AsyncClient(base_url=settings.browser_url, timeout=60) as c:
        return await c.request(method, f"/sessions/{SESSION}{path}", headers=_h(), json=json)


async def snapshot_call(method: str, path: str, json: dict | None = None) -> dict:
    r = await call(method, path, json)
    if r.status_code >= 400:
        raise RuntimeError(r.json().get("detail", r.text) if r.headers.get("content-type", "").startswith("application/json") else r.text)
    return r.json()
