"""云浏览器客户端。后端不运行浏览器，只通过 HTTP 调 browser 服务。
会话按站点命名（规则在 app/browser_sessions.py），每个调用都带会话名；登录状态在服务端按会话名存档、跨对话保留。"""
import httpx

from .config import settings


def _h() -> dict:
    return {"Authorization": f"Bearer {settings.browser_token}"}


class BrowserDown(RuntimeError):
    """浏览器服务本身不能用（只这一处判定）：连不上，或 Chromium 起不来（服务回 503 + 一句原因，browser/service.py launch_reason）。
    和“这个网页打不开”分开：工具据此把画面卡标成 down，不留一张永远黑着的卡；str = 给模型的整句，short = 卡上一句。"""

    @property
    def short(self) -> str:
        first = str(self).split("。")[0]
        return first.split("：", 1)[1] if first.startswith("云浏览器没能启动：") else first


async def call(session: str, method: str, path: str, json: dict | None = None) -> httpx.Response:
    try:
        async with httpx.AsyncClient(base_url=settings.browser_url, timeout=60) as c:
            r = await c.request(method, f"/sessions/{session}{path}", headers=_h(), json=json)
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        raise BrowserDown(f"云浏览器没连上（{type(e).__name__}）。浏览器服务没在运行，马上重试也没用；请告诉用户需要管理员启动 browser 服务。") from e
    if r.status_code == 503:
        raise BrowserDown(_detail(r) or "云浏览器暂时不能用。")
    return r


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


async def downloads(session: str) -> list[dict]:
    """这个会话还没取走的下载 [{id, name, size, state downloading|done|failed, error}]。"""
    r = await call(session, "GET", "/downloads")
    if r.status_code >= 400:
        raise RuntimeError(_detail(r))
    return r.json().get("downloads", [])


async def fetch_download(session: str, did: str, dest) -> int:
    """把一个下载流式写到 dest（Path），返回字节数；之后服务端那份由 drop_download 删。"""
    async with httpx.AsyncClient(base_url=settings.browser_url, timeout=120) as c:
        async with c.stream("GET", f"/sessions/{session}/downloads/{did}", headers=_h()) as r:
            if r.status_code >= 400:
                raise RuntimeError(f"取下载失败（{r.status_code}）")
            n = 0
            with open(dest, "wb") as f:
                async for chunk in r.aiter_bytes():
                    f.write(chunk)
                    n += len(chunk)
            return n


async def drop_download(session: str, did: str) -> None:
    r = await call(session, "DELETE", f"/downloads/{did}")
    if r.status_code >= 400:
        raise RuntimeError(_detail(r))


async def login_state(session: str, state: str) -> None:
    """记登录标记 signed_in / expired（服务端 /state/<name>.meta.json）。尽力而为：连不上 → RuntimeError，调用方吞掉。"""
    try:
        r = await call(session, "PUT", "/login-state", {"state": state})
    except httpx.HTTPError as e:
        raise RuntimeError(f"云浏览器没连上：{e}") from e
    if r.status_code >= 400:
        raise RuntimeError(_detail(r))


async def render(html: str, fmt: str = "pdf", paper: str = "A4", landscape: bool = False, width: int = 1024,
                 page_numbers: bool = True) -> tuple[bytes, int, bool]:
    """排好的 HTML → PDF / PNG 字节（v2.22，doc_render 用）。返回 (数据, 没加载的网络资源数, 长图是否被截断)；
    连不上 / 浏览器报错 → RuntimeError（中文原因）。"""
    body = {"html": html, "format": fmt, "paper": paper, "landscape": landscape, "width": width, "page_numbers": page_numbers}
    try:
        async with httpx.AsyncClient(base_url=settings.browser_url, timeout=90) as c:
            r = await c.post("/render", headers=_h(), json=body)
    except httpx.HTTPError as e:
        raise RuntimeError(f"云浏览器没连上，排不了版：{e}") from e
    if r.status_code >= 400:
        raise RuntimeError(_detail(r))
    try:
        blocked = int(r.headers.get("x-render-blocked", "0"))
    except ValueError:
        blocked = 0
    return r.content, blocked, r.headers.get("x-render-cut") == "1"


async def live_connect(session: str, reopen: bool = False):
    """和 browser 服务的实时画面 WS 握手（browser/service.py /sessions/{name}/live），返回 websockets 连接；连不上抛异常。
    帧是 JPEG 二进制，后端不解码，只转发（routes/browser.py live）。"""
    import websockets
    base = settings.browser_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    return await websockets.connect(f"{base}/sessions/{session}/live" + ("?open=1" if reopen else ""),
                                    open_timeout=15, ping_interval=None, compression=None, proxy=None,
                                    max_size=8 * 1024 * 1024, additional_headers=_h())
