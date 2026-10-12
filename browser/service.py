"""云浏览器服务：唯一运行 Chromium 的地方。后端用 token 调它，模型只看到“页面快照”。

- 会话 = 一个浏览器上下文，按站点命名（后端 app/browser_sessions.py 起名，如 taobao-com），
  登录状态持久化到 /state/<name>.json，下次同名会话自动带上；GET /sessions 列出、DELETE ?forget=1 = 退出登录
- 快照：可交互元素编上号（ref），外加页面可见文字（截断），给模型用
- 截图 + 鼠标/键盘：给你“实时画面 + 接管”用
- 安全：只允许 http(s)，内网/回环地址的请求一律拦截（防 SSRF 打到你的数据库）
- 空闲 15 分钟自动关闭会话
"""
import asyncio
import ipaddress
import json
import os
import re
import socket
import time
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import Response
from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from pydantic import BaseModel

TOKEN = os.environ["BROWSER_TOKEN"]
STATE = "/state"
IDLE = 15 * 60
VIEW = {"width": 1280, "height": 800}
MAX_TEXT = 6000
# 同时开着的会话上限（小 VPS 设 1）：超出时把最久没用的会话存好登录状态后关掉
MAX_SESSIONS = max(1, int(os.environ.get("BROWSER_MAX_SESSIONS", "3")))

app = FastAPI()
_pw = None
_browser: Browser | None = None
_sessions: dict[str, tuple[BrowserContext, Page]] = {}
_used: dict[str, float] = {}
_restored: set[str] = set()  # 这次是从存好的登录状态恢复出来的会话（goto 回报给后端，模型知道“沿用了登录”）
_lock = asyncio.Lock()


def auth(authorization: str = Header("")) -> None:
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(401)


_host_ok: dict[str, bool] = {}  # DNS 结果缓存，避免每个请求都解析


def _public_host(host: str) -> bool:
    if host in _host_ok:
        return _host_ok[host]
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    _host_ok[host] = all(ipaddress.ip_address(i[4][0]).is_global for i in infos)
    return _host_ok[host]


async def _guard(route):
    u = urlparse(route.request.url)
    if u.scheme in ("data", "blob", "about"):
        return await route.continue_()
    if u.scheme not in ("http", "https") or not await asyncio.to_thread(_public_host, u.hostname or ""):
        return await route.abort("blockedbyclient")
    await route.continue_()


def _check_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
        raise HTTPException(400, "bad session name")
    return name


async def _session(name: str) -> Page:
    global _pw, _browser
    async with _lock:
        if not _browser:
            _pw = await async_playwright().start()
            _browser = await _pw.chromium.launch(args=["--disable-dev-shm-usage"])
        if name not in _sessions:
            while len(_sessions) >= MAX_SESSIONS:
                await _evict(min(_sessions, key=lambda n: _used.get(n, 0)))
            path = _state_path(name)
            saved = os.path.exists(path)
            ctx = await _browser.new_context(viewport=VIEW, locale="zh-CN", timezone_id="Asia/Shanghai",
                                             storage_state=path if saved else None)
            if saved:
                _restored.add(name)
            else:
                _restored.discard(name)
            await ctx.route("**/*", _guard)
            page = await ctx.new_page()
            _sessions[name] = (ctx, page)
    _used[name] = time.time()
    return _sessions[name][1]


async def _evict(name: str) -> None:
    """存好登录状态再关：下次用到同名会话会自动恢复登录。"""
    try:
        await _save(name)
    except Exception:
        pass
    ctx, _ = _sessions.pop(name)
    _used.pop(name, None)
    await ctx.close()


def _state_path(name: str) -> str:
    return f"{STATE}/{name}.json"


async def _save(name: str) -> None:
    ctx, _ = _sessions[name]
    os.makedirs(STATE, exist_ok=True)
    await ctx.storage_state(path=_state_path(name))


def _summary(name: str) -> dict:
    """一条会话的概况（给“我的电脑”列表）：只读 cookie 的域名和个数，不回任何 cookie 值。"""
    path = _state_path(name)
    domains: list[str] = []
    cookies = 0
    saved = os.path.exists(path)
    if saved:
        try:
            with open(path, encoding="utf-8") as f:
                state = json.load(f)
            for c in state.get("cookies", []):
                cookies += 1
                d = str(c.get("domain", "")).lstrip(".")
                if d and d not in domains:
                    domains.append(d)
        except (OSError, ValueError):
            pass
    used = _used.get(name) or (os.path.getmtime(path) if saved else None)
    return {"name": name, "open": name in _sessions, "saved": saved, "last_used": used,
            "cookies": cookies, "domains": domains[:5]}


SNAPSHOT_JS = """
() => {
  const sel = 'a[href],button,input,textarea,select,[role=button],[role=link],[role=tab],[role=checkbox],[contenteditable=true]';
  const out = []; let n = 0;
  document.querySelectorAll('[data-ref]').forEach(e => e.removeAttribute('data-ref'));
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || r.bottom < 0 || r.top > innerHeight * 3) continue;
    const st = getComputedStyle(el); if (st.visibility === 'hidden' || st.display === 'none') continue;
    const ref = String(++n); el.setAttribute('data-ref', ref);
    const val = el.type === 'password' ? '' : el.value;  // 密码框的值绝不进快照
    const name = (el.getAttribute('aria-label') || el.innerText || val || el.placeholder || el.title || el.alt || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
    out.push({ ref, tag: el.tagName.toLowerCase(), type: el.type || '', name });
    if (n >= 150) break;
  }
  return { url: location.href, title: document.title, text: document.body ? document.body.innerText : '', elements: out };
}
"""


async def _snapshot(page: Page) -> dict:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=8000)
    except Exception:
        pass
    snap = await page.evaluate(SNAPSHOT_JS)
    snap["text"] = re.sub(r"\n{3,}", "\n\n", snap["text"])[:MAX_TEXT]
    return snap


class GotoIn(BaseModel):
    url: str


class ActIn(BaseModel):
    action: str             # click | type | press | scroll | back
    ref: str | None = None
    text: str | None = None
    submit: bool = False
    dy: int = 600


class LoginIn(BaseModel):
    user_ref: str
    pass_ref: str
    username: str
    password: str
    submit: bool = True


class PointIn(BaseModel):
    x: float                # 0..1，相对截图宽度
    y: float


class KeysIn(BaseModel):
    text: str | None = None
    key: str | None = None


@app.post("/sessions/{name}/goto", dependencies=[Depends(auth)])
async def goto(name: str, body: GotoIn):
    if urlparse(body.url).scheme not in ("http", "https"):
        raise HTTPException(400, "只允许 http(s)")
    page = await _session(_check_name(name))
    try:
        await page.goto(body.url, timeout=30000, wait_until="domcontentloaded")
    except Exception as e:
        raise HTTPException(502, f"打不开：{e}")
    await _save(name)
    snap = await _snapshot(page)
    snap["restored"] = name in _restored
    return snap


@app.get("/sessions/{name}/snapshot", dependencies=[Depends(auth)])
async def snapshot(name: str):
    return await _snapshot(await _session(_check_name(name)))


@app.post("/sessions/{name}/act", dependencies=[Depends(auth)])
async def act(name: str, body: ActIn):
    page = await _session(_check_name(name))
    el = page.locator(f'[data-ref="{body.ref}"]') if body.ref else None
    try:
        match body.action:
            case "click":
                await el.click(timeout=8000)
            case "type":
                await el.fill(body.text or "", timeout=8000)
                if body.submit:
                    await el.press("Enter")
            case "press":
                await page.keyboard.press(body.text or "Enter")
            case "scroll":
                await page.mouse.wheel(0, body.dy)
            case "back":
                await page.go_back(timeout=15000)
            case _:
                raise HTTPException(400, "未知动作")
        await page.wait_for_timeout(800)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"操作失败：{str(e)[:200]}")
    await _save(name)
    return await _snapshot(page)


@app.post("/sessions/{name}/login", dependencies=[Depends(auth)])
async def login(name: str, body: LoginIn):
    """代填登录：密码只在这里出现一次，直接进输入框，返回的快照里没有它。"""
    page = await _session(_check_name(name))
    try:
        await page.locator(f'[data-ref="{body.user_ref}"]').fill(body.username, timeout=8000)
        pw = page.locator(f'[data-ref="{body.pass_ref}"]')
        if await pw.get_attribute("type") != "password":
            raise HTTPException(400, "pass_ref 不是密码框")
        await pw.fill(body.password, timeout=8000)
        if body.submit:
            await pw.press("Enter")
        await page.wait_for_timeout(1500)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"代填失败：{str(e)[:200]}")
    await _save(name)
    return await _snapshot(page)


# ---- 实时画面与人工接管 ----
@app.get("/sessions/{name}/screen", dependencies=[Depends(auth)])
async def screen(name: str):
    if name not in _sessions:
        raise HTTPException(404)
    page = _sessions[name][1]
    return Response(await page.screenshot(type="jpeg", quality=60), media_type="image/jpeg")


@app.post("/sessions/{name}/mouse", dependencies=[Depends(auth)])
async def mouse(name: str, body: PointIn):
    page = await _session(_check_name(name))
    await page.mouse.click(body.x * VIEW["width"], body.y * VIEW["height"])
    await _save(name)
    return {"ok": True}


@app.post("/sessions/{name}/keyboard", dependencies=[Depends(auth)])
async def keyboard(name: str, body: KeysIn):
    page = await _session(_check_name(name))
    if body.text:
        await page.keyboard.type(body.text, delay=20)
    if body.key:
        await page.keyboard.press(body.key)
    await _save(name)
    return {"ok": True}


@app.get("/sessions", dependencies=[Depends(auth)])
async def sessions():
    """开着的 + 存过登录状态的会话，最近用过的在前。"""
    names = set(_sessions)
    if os.path.isdir(STATE):
        names |= {f[:-5] for f in os.listdir(STATE) if f.endswith(".json") and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", f[:-5])}
    out = [_summary(n) for n in names]
    out.sort(key=lambda x: -(x["last_used"] or 0))
    return {"sessions": out, "max_open": MAX_SESSIONS}


@app.delete("/sessions/{name}", dependencies=[Depends(auth)])
async def close(name: str, forget: bool = False):
    """关掉会话。默认先存好登录状态（下次接着用）；forget=1 = 退出登录：连存档一起删。"""
    _check_name(name)
    async with _lock:
        if name in _sessions:
            if forget:
                ctx, _ = _sessions.pop(name)
                _used.pop(name, None)
                await ctx.close()
            else:
                await _evict(name)
        _restored.discard(name)
        if forget:
            try:
                os.remove(_state_path(name))
            except FileNotFoundError:
                pass
    return {"ok": True}


async def _reaper():
    while True:
        await asyncio.sleep(60)
        for name, t in list(_used.items()):
            if time.time() - t > IDLE and name in _sessions:
                async with _lock:
                    if name in _sessions:
                        await _evict(name)


@app.on_event("startup")
async def _start():
    asyncio.create_task(_reaper())
