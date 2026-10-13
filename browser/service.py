"""云浏览器服务：唯一运行 Chromium 的地方。后端用 token 调它，模型只看到“页面快照”。

- 会话 = 一个浏览器上下文，按站点命名（后端 app/browser_sessions.py 起名，如 taobao-com），
  登录状态持久化到 /state/<name>.json，下次同名会话自动带上；GET /sessions 列出、DELETE ?forget=1 = 退出登录
- 快照：可交互元素编上号（ref），外加页面可见文字（截断），给模型用
- 截图 + 鼠标/键盘：给你“实时画面 + 接管”用
- 安全：只允许 http(s)；Chromium 的每个连接都走本进程里的出网关卡 egress.py（v2.02：页面里的跳转、重定向、
  WebSocket、Service Worker 都算，连的是查过的 IP），内网/回环地址一律拦截并在快照里报给模型（blocked）
- 空闲 15 分钟自动关闭会话
- 登录状态标记（v1.36）：/state/<name>.meta.json 记 {signed_in, expired}（unix 秒）——后端看到“登录成功”/“登录页又出来了”
  就 PUT /login-state 记一笔；goto 回报给后端（之前登录过的会话现在是登录页 = 登录过期），GET /sessions 列出给“我的电脑”
- 文件（v1.32）：POST /upload 把后端传来的工作区文件放进网页的文件框（<input type=file> 直接设；
  别的按钮先等“选文件”对话框再设）；页面触发的下载存到 DOWNLOADS/<会话>/，GET /downloads 列出、
  取走后 DELETE——后端把它搬进工作区 downloads/（app/browser_files.py），这里只是中转，关会话就清掉
"""
import asyncio
import base64
import shutil
import uuid
import ipaddress
import json
import os
import re
import time
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, Response
from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from pydantic import BaseModel

import egress

TOKEN = os.environ["BROWSER_TOKEN"]
STATE = "/state"
IDLE = 15 * 60
VIEW = {"width": 1280, "height": 800}
MAX_TEXT = 6000
# 同时开着的会话上限（小 VPS 设 1）：超出时把最久没用的会话存好登录状态后关掉
MAX_SESSIONS = max(1, int(os.environ.get("BROWSER_MAX_SESSIONS", "3")))
DOWNLOADS = "/tmp/browser-downloads"
UPLOAD_MAX = 20 * 1024 * 1024  # 一次上传的总字节（后端 browser_files.UPLOAD_MAX_MB 同值）
DOWNLOAD_MAX = 200 * 1024 * 1024  # 单个下载超过就丢掉，只回报名字

app = FastAPI()
_pw = None
_browser: Browser | None = None
_sessions: dict[str, tuple[BrowserContext, Page]] = {}
_used: dict[str, float] = {}
_downloads: dict[str, list[dict]] = {}  # 会话 → [{id, name, size, state downloading|done|failed, error}]
_restored: set[str] = set()  # 这次是从存好的登录状态恢复出来的会话（goto 回报给后端，模型知道“沿用了登录”）
_lock = asyncio.Lock()
_egress = egress.Egress(egress.ALLOW_HOSTS)


def auth(authorization: str = Header("")) -> None:
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(401)


async def _guard(route):
    """只管协议（file:、chrome: 之类直接拒）；地址由出网关卡 egress 在连接时查，那里每一跳都过。"""
    u = urlparse(route.request.url)
    if u.scheme in ("data", "blob", "about", "http", "https"):
        return await route.continue_()
    await route.abort("blockedbyclient")


def _check_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
        raise HTTPException(400, "bad session name")
    return name


async def _ensure_browser() -> Browser:
    """在 _lock 里调：第一次用到时才起 Chromium（会话和渲染共用一个进程，小 VPS 只养一个）。"""
    global _pw, _browser
    if not _browser:
        if not _egress.port:
            await _egress.start()
        _pw = await async_playwright().start()
        # proxy per-context：先给浏览器一个占位代理，每个会话再用自己的代理账号（被拦记到对的会话上）；
        # WebRTC 只许走代理（不然 UDP 能绕过关卡直连内网）
        _browser = await _pw.chromium.launch(proxy={"server": "http://per-context"}, args=[
            "--disable-dev-shm-usage", "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"])
    return _browser


async def _session(name: str) -> Page:
    async with _lock:
        await _ensure_browser()
        if name not in _sessions:
            while len(_sessions) >= MAX_SESSIONS:
                await _evict(min(_sessions, key=lambda n: _used.get(n, 0)))
            path = _state_path(name)
            saved = os.path.exists(path)
            ctx = await _browser.new_context(viewport=VIEW, locale="zh-CN", timezone_id="Asia/Shanghai",
                                             storage_state=path if saved else None, accept_downloads=True,
                                             proxy=_egress.proxy_for(name), service_workers="block")
            if saved:
                _restored.add(name)
            else:
                _restored.discard(name)
            await ctx.route("**/*", _guard)
            ctx.on("page", lambda p, n=name: _watch(n, p))  # 弹出的新标签页里的下载也要收
            page = await ctx.new_page()
            _watch(name, page)
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
    _drop_downloads(name)
    _egress.forget(name)


# ---- 下载中转 ----
_watched: set[int] = set()


def _watch(name: str, page) -> None:
    if id(page) in _watched:
        return
    _watched.add(id(page))
    page.on("download", lambda d: asyncio.ensure_future(_keep(name, d)))


async def _keep(name: str, download) -> None:
    """把一个下载存到中转目录。超过 DOWNLOAD_MAX 删掉，只留名字和原因。"""
    did = uuid.uuid4().hex[:12]
    fname = os.path.basename(download.suggested_filename or "") or "download"
    item = {"id": did, "name": fname[:120], "size": 0, "state": "downloading", "error": ""}
    _downloads.setdefault(name, []).append(item)
    path = os.path.join(DOWNLOADS, name, did)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        await download.save_as(path)
        item["size"] = os.path.getsize(path)
        if item["size"] > DOWNLOAD_MAX:
            os.remove(path)
            item.update(state="failed", error=f"文件太大（超过 {DOWNLOAD_MAX // 1024 // 1024} MB），没留")
        else:
            item["state"] = "done"
    except Exception as e:
        item.update(state="failed", error=f"下载失败：{str(e)[:120]}")


def _drop_downloads(name: str) -> None:
    _downloads.pop(name, None)
    shutil.rmtree(os.path.join(DOWNLOADS, name), ignore_errors=True)


def _state_path(name: str) -> str:
    return f"{STATE}/{name}.json"


def _meta_path(name: str) -> str:
    return f"{STATE}/{name}.meta.json"


def _meta(name: str) -> dict:
    """登录标记 {signed_in, expired}（unix 秒或 None）；没有 / 坏了 → 全 None。"""
    try:
        with open(_meta_path(name), encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError):
        m = {}
    return {k: m.get(k) if isinstance(m.get(k), (int, float)) else None for k in ("signed_in", "expired")}


def _set_meta(name: str, state: str) -> dict:
    m = _meta(name)
    if state == "signed_in":
        m = {"signed_in": time.time(), "expired": None}
    elif state == "expired" and m["signed_in"] and not m["expired"]:
        m["expired"] = time.time()
    os.makedirs(STATE, exist_ok=True)
    tmp = _meta_path(name) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f)
    os.replace(tmp, _meta_path(name))
    return m


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
            "cookies": cookies, "domains": domains[:5], **_meta(name)}


SNAPSHOT_JS = """
() => {
  const sel = 'a[href],button,input,textarea,select,[role=button],[role=link],[role=tab],[role=checkbox],[contenteditable=true]';
  const out = []; let n = 0;
  document.querySelectorAll('[data-ref]').forEach(e => e.removeAttribute('data-ref'));
  for (const el of document.querySelectorAll(sel)) {
    // 文件框常被藏起来（样式化的“上传”按钮盖在上面），照样编号：browser_upload 直接往里放文件
    const file = el.tagName === 'INPUT' && el.type === 'file';
    const r = el.getBoundingClientRect();
    if (!file && (r.width < 2 || r.height < 2 || r.bottom < 0 || r.top > innerHeight * 3)) continue;
    const st = getComputedStyle(el); if (!file && (st.visibility === 'hidden' || st.display === 'none')) continue;
    const ref = String(++n); el.setAttribute('data-ref', ref);
    const val = el.type === 'password' || file ? '' : el.value;  // 密码框的值绝不进快照
    const label = file ? ((el.labels && el.labels[0] && el.labels[0].innerText) || el.accept || '选择文件') : '';
    const name = (el.getAttribute('aria-label') || el.innerText || val || el.placeholder || el.title || el.alt || label || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
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


def _with_blocked(name: str, snap: dict) -> dict:
    """附上这个会话上次以来被出网关卡拦下的请求（[{host, reason}]，没有就不带）。"""
    blocked = _egress.take_blocked(name)
    if blocked:
        snap["blocked"] = blocked
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


class UploadFile(BaseModel):
    name: str
    mime: str = "application/octet-stream"
    data: str               # base64


class UploadIn(BaseModel):
    ref: str
    files: list[UploadFile]


class LoginStateIn(BaseModel):
    state: str              # signed_in | expired


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
        if "Download is starting" not in str(e):  # 网址直接是个文件：不是打不开，是下载了（后端随后取走）
            blocked = _egress.take_blocked(name)
            if blocked:  # 打开的地址（或它的重定向）进了内网：说清楚是被拦，不是网站坏了
                raise HTTPException(403, "被拦下：" + "；".join(b["reason"] for b in blocked[:3])
                                    + "。助手的浏览器不能访问内网 / 本机地址。")
            raise HTTPException(502, f"打不开：{e}")
        await page.wait_for_timeout(1500)
    await _save(name)
    snap = _with_blocked(name, await _snapshot(page))
    snap["restored"] = name in _restored
    snap["login"] = _meta(name)
    return snap


@app.put("/sessions/{name}/login-state", dependencies=[Depends(auth)])
async def login_state(name: str, body: LoginStateIn):
    """后端判定的登录状态：signed_in（登录成功，清掉过期）/ expired（之前登录过、现在又是登录页；没登录过就不记）。"""
    if body.state not in ("signed_in", "expired"):
        raise HTTPException(400, "state 只能是 signed_in / expired")
    return _set_meta(_check_name(name), body.state)


@app.get("/sessions/{name}/snapshot", dependencies=[Depends(auth)])
async def snapshot(name: str):
    return _with_blocked(name, await _snapshot(await _session(_check_name(name))))


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
    return _with_blocked(name, await _snapshot(page))


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
    return _with_blocked(name, await _snapshot(page))


@app.post("/sessions/{name}/upload", dependencies=[Depends(auth)])
async def upload(name: str, body: UploadIn):
    """把文件放进网页：ref 是 <input type=file> 就直接设；是“上传”按钮之类就点它、等选文件对话框再设。"""
    page = await _session(_check_name(name))
    try:
        payload = [{"name": os.path.basename(f.name) or "file", "mimeType": f.mime, "buffer": base64.b64decode(f.data, validate=True)}
                   for f in body.files]
    except ValueError:
        raise HTTPException(400, "文件数据不是 base64")
    if not payload:
        raise HTTPException(400, "没有文件")
    if sum(len(f["buffer"]) for f in payload) > UPLOAD_MAX:
        raise HTTPException(413, f"一次最多传 {UPLOAD_MAX // 1024 // 1024} MB")
    el = page.locator(f'[data-ref="{body.ref}"]')
    try:
        kind = await el.evaluate("e => e.tagName.toLowerCase() + ':' + (e.type || '')", timeout=8000)
        if kind == "input:file":
            if len(payload) > 1 and not await el.evaluate("e => e.multiple"):
                raise HTTPException(400, "这个文件框一次只收一个文件")
            await el.set_input_files(payload, timeout=8000)
        else:
            async with page.expect_file_chooser(timeout=8000) as info:
                await el.click(timeout=8000)
            chooser = await info.value
            if len(payload) > 1 and not chooser.is_multiple():
                raise HTTPException(400, "这个上传框一次只收一个文件")
            await chooser.set_files(payload, timeout=8000)
        await page.wait_for_timeout(800)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"上传失败（{str(e)[:160]}）：ref 要是文件框或点了会弹出选文件的按钮")
    await _save(name)
    return _with_blocked(name, await _snapshot(page))


@app.get("/sessions/{name}/downloads", dependencies=[Depends(auth)])
async def downloads(name: str):
    """还没被后端取走的下载（含正在下的、失败的）。"""
    return {"downloads": [dict(d) for d in _downloads.get(_check_name(name), [])]}


@app.get("/sessions/{name}/downloads/{did}", dependencies=[Depends(auth)])
async def download_file(name: str, did: str):
    _check_name(name)
    item = next((d for d in _downloads.get(name, []) if d["id"] == did), None)
    path = os.path.join(DOWNLOADS, name, did)
    if not item or item["state"] != "done" or not os.path.isfile(path):
        raise HTTPException(404)
    return FileResponse(path, filename=item["name"])


@app.delete("/sessions/{name}/downloads/{did}", dependencies=[Depends(auth)])
async def download_done(name: str, did: str):
    """后端取走了（或不要了）：删中转文件。"""
    _check_name(name)
    _downloads[name] = [d for d in _downloads.get(name, []) if d["id"] != did]
    try:
        os.remove(os.path.join(DOWNLOADS, name, re.sub(r"[^0-9a-f]", "", did)))
    except FileNotFoundError:
        pass
    return {"ok": True}


# ---- 渲染文档（v2.22）：后端排好的 HTML → PDF / PNG ----
# 一次性上下文：不联网（offline + 只放行 data:/about:）、不跑脚本、不带任何会话的 cookie；渲染完就关。
# 网页里引用的网络资源一律不加载，数量回报给后端（X-Render-Blocked），后端告诉模型“渲染时不联网”。
RENDER_HTML_MAX = 16 * 1024 * 1024  # 后端 doc_render.HTML_MAX 同值
RENDER_TIMEOUT_MS = 30_000
RENDER_PNG_MAX_H = 16_384  # 长图最高像素（再高 Chromium 截图会失败 / 吃内存）
PAPERS = ("A3", "A4", "A5", "Letter", "Legal")
_render_lock = asyncio.Semaphore(1)  # 一次只渲染一份（4G 机器）
FOOTER = ('<div style="width:100%;font-size:8px;color:#8a8a8a;text-align:center;font-family:sans-serif">'
          '<span class="pageNumber"></span> / <span class="totalPages"></span></div>')


class RenderIn(BaseModel):
    html: str
    format: str = "pdf"  # pdf | png
    paper: str = "A4"
    landscape: bool = False
    width: int = 1024  # png 视口宽
    page_numbers: bool = True


@app.post("/render", dependencies=[Depends(auth)])
async def render(body: RenderIn):
    if body.format not in ("pdf", "png"):
        raise HTTPException(400, "format 只能是 pdf 或 png")
    if body.paper not in PAPERS:
        raise HTTPException(400, f"纸张只能是 {'/'.join(PAPERS)}")
    if len(body.html.encode()) > RENDER_HTML_MAX:
        raise HTTPException(413, f"HTML 超过 {RENDER_HTML_MAX // 1024 // 1024} MB")
    width = min(max(body.width, 320), 2000)
    blocked: set[str] = set()
    cut = False

    async def guard(route):
        u = route.request.url
        if u.startswith(("data:", "about:")):
            return await route.continue_()
        if u.startswith(("http:", "https:")):
            blocked.add(u)
        await route.abort("blockedbyclient")

    async with _render_lock:
        async with _lock:
            browser = await _ensure_browser()
        ctx = await browser.new_context(viewport={"width": width, "height": 800 if body.format == "pdf" else 64}, java_script_enabled=False,
                                        offline=True, service_workers="block", locale="zh-CN")
        try:
            await ctx.route("**/*", guard)
            page = await ctx.new_page()
            await page.set_content(body.html, wait_until="load", timeout=RENDER_TIMEOUT_MS)
            if body.format == "pdf":
                data = await page.pdf(format=body.paper, landscape=body.landscape, print_background=True,
                                      prefer_css_page_size=True, display_header_footer=body.page_numbers,
                                      header_template="<span></span>", footer_template=FOOTER if body.page_numbers else "<span></span>",
                                      margin={"top": "16mm", "bottom": "18mm", "left": "16mm", "right": "16mm"})
                kind = "application/pdf"
            else:
                data, kind = await page.screenshot(type="png", full_page=True, timeout=RENDER_TIMEOUT_MS), "image/png"
                if png_height(data) > RENDER_PNG_MAX_H:  # 太长：只要最上面 RENDER_PNG_MAX_H 像素
                    data = await page.screenshot(type="png", full_page=True, timeout=RENDER_TIMEOUT_MS,
                                                 clip={"x": 0, "y": 0, "width": width, "height": RENDER_PNG_MAX_H})
                    cut = True
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(422, f"渲染失败：{str(e)[:200]}")
        finally:
            await ctx.close()
    return Response(data, media_type=kind, headers={"X-Render-Blocked": str(len(blocked)), "X-Render-Cut": "1" if cut else "0"})


def png_height(data: bytes) -> int:
    """PNG 头里的高度（IHDR 第 20–24 字节）；不是 PNG → 0。"""
    return int.from_bytes(data[20:24], "big") if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24 else 0


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
                _drop_downloads(name)
                _egress.forget(name)
            else:
                await _evict(name)
        _restored.discard(name)
        if forget:
            for path in (_state_path(name), _meta_path(name)):
                try:
                    os.remove(path)
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
