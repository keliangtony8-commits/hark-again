"""云浏览器客户端。后端不运行浏览器，只通过 HTTP 调 browser 服务。
会话按站点命名（规则在 app/browser_sessions.py），每个调用都带会话名；登录状态在服务端按会话名存档、跨对话保留。"""
import httpx

from .config import settings


def _h() -> dict:
    return {"Authorization": f"Bearer {settings.browser_token}"}


async def call(session: str, method: str, path: str, json: dict | None = None) -> httpx.Response:
    async with httpx.AsyncClient(base_url=settings.browser_url, timeout=60) as c:
        return await c.request(method, f"/sessions/{session}{path}", headers=_h(), json=json)


def _detail(r: httpx.Response) -> str:
    if r.headers.get("content-type", "").startswith("application/json"):
        return str(r.json().get("detail", r.text))
    return r.text


async def snapshot_call(session: str, method: str, path: str, json: dict | None = None) -> dict:
    r = await call(session, method, path, json)
    if r.status_code >= 400:
        raise RuntimeError(_detail(r))
    return r.json()


async def sessions() -> dict:
    """{sessions: [{name, open, saved, last_used(unix), cookies, domains}], max_open}；连不上 → RuntimeError。"""
    try:
        async with httpx.AsyncClient(base_url=settings.browser_url, timeout=15) as c:
            r = await c.get("/sessions", headers=_h())
    except httpx.HTTPError as e:
        raise RuntimeError(f"云浏览器没连上：{e}") from e
    if r.status_code >= 400:
        raise RuntimeError(_detail(r))
    return r.json()


async def close(session: str, forget: bool = False) -> None:
    """关掉会话（默认存好登录状态）；forget=True = 连登录存档一起删。连不上 → RuntimeError。"""
    try:
        async with httpx.AsyncClient(base_url=settings.browser_url, timeout=30) as c:
            r = await c.delete(f"/sessions/{session}", headers=_h(), params={"forget": "1"} if forget else None)
    except httpx.HTTPError as e:
        raise RuntimeError(f"云浏览器没连上：{e}") from e
    if r.status_code >= 400:
        raise RuntimeError(_detail(r))
