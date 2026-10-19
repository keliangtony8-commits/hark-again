"""云浏览器服务：唯一运行 Chromium 的地方。后端用 token 调它，模型只看到“页面快照”。

- 会话 = 一个浏览器上下文，按站点命名（后端 app/browser_sessions.py 起名，如 taobao-com），
  登录状态持久化到 /state/<name>.json，下次同名会话自动带上；GET /sessions 列出、DELETE ?forget=1 = 退出登录
- 快照：可交互元素编上号（ref），外加页面可见文字（截断），给模型用
- 实时画面 + 接管（v2.89）：WS /sessions/{name}/live，CDP screencast 推帧、同一条 WS 收输入（规则 live.py）；
  有人在看不回收、没人看不推；会话关了观看者收 4404，open=1 用存好的登录回到最后网址。/screen 只给助手截图用
- 安全：只允许 http(s)；Chromium 的每个连接都走本进程里的出网关卡 egress.py（v2.02：页面里的跳转、重定向、
  WebSocket、Service Worker 都算，连的是查过的 IP），内网/回环地址一律拦截并在快照里报给模型（blocked）
- 空闲 15 分钟自动关闭会话
- 登录状态标记（v1.36）：/state/<name>.meta.json 记 {signed_in, expired}（unix 秒）——后端看到“登录成功”/“登录页又出来了”
  就 PUT /login-state 记一笔；goto 回报给后端（之前登录过的会话现在是登录页 = 登录过期），GET /sessions 列出给“我的电脑”
- 标签页（v2.47，规则在 tabs.py）：网站开的新标签页自动切过去、页面被关退回上一个、渲染进程崩了在原网址重开，
  每次的变化放在快照的 tab 字段里告诉后端（后端 tab_note 说成话）；后退到头的弹出页 = 关掉它回原页
- 表单控件（v2.53，规则在 forms.py）：快照里下拉框带当前值 + 选项、勾选框带 checked；/act select 按选项文字选，
  /act press 按键（可先聚焦某个元素）
- 网页弹框（v2.56，规则在 dialogs.py）：alert / confirm / prompt / 离开提示当场处理（不挂着，挂着会卡死页面脚本），
  confirm / prompt 按这次动作说好的 dialog（accept / dismiss，没说 = 取消）办；弹过什么放快照的 dialogs 字段；
  用户在实时画面里亲手点 = accept
- 内嵌框（v2.59，规则在 frames.py）：看得见的 iframe（支付卡号框、嵌入的登录框 / 表单、Cookie 同意层）里的元素和文字
  一起进快照，编号全局接着编、元素带 frame 标签；点 / 填 / 登录 / 上传按 ref 自动去对应的框里找
- 地区（v2.68，规则在 region.py）：网页看到的语言 / 时区跟用户走——后端 goto 带 locale（回复语言）+ timezone（TIMEZONE），
  设置变了下次 goto 存好登录重开会话
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

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from pydantic import BaseModel

import dialogs
import egress
import forms
import frames
import identity
import live
import region
import shadow
import tabs

TOKEN = os.environ["BROWSER_TOKEN"]
STATE = "/state"
IDLE = 15 * 60
VIEW = {"width": 1280, "height": 800}
MAX_TEXT = 6000
# 同时开着的会话上限（小 VPS 设 1）：超出时把最久没用的会话存好登录状态后关掉
MAX_SESSIONS = max(1, int(os.environ.get("BROWSER_MAX_SESSIONS", "2")))
DOWNLOADS = "/tmp/browser-downloads"
UPLOAD_MAX = 20 * 1024 * 1024  # 一次上传的总字节（后端 browser_files.UPLOAD_MAX_MB 同值）
DOWNLOAD_MAX = 200 * 1024 * 1024  # 单个下载超过就丢掉，只回报名字

app = FastAPI()
_pw = None
_browser: Browser | None = None
_sessions: dict[str, tuple[BrowserContext, Page]] = {}
_used: dict[str, float] = {}
_downloads: dict[str, list[dict]] = {}  # 会话 → [{id, name, size, state downloading|done|failed, error}]
_tabs: dict[str, tabs.Tabs] = {}  # 会话 → 现在操作哪个标签页（规则在 tabs.py）
_dialog_arm: dict[str, tuple[str | None, str | None, float]] = {}  # 会话 → (accept/dismiss/None, prompt 字, 有效到)
_dialog_notes: dict[str, list[dict]] = {}  # 会话 → 上次快照以来弹过的框（dialogs.decide 的 note）
_frame_of: dict[str, dict[str, object]] = {}  # 会话 → {ref: 内嵌框}（上一张快照里在 iframe 里的元素，frames.py）
_dialog_seen: dict[str, int] = {}  # 会话 → 这次动作里已弹过几个（连环弹框判定）
ARM_AFTER_S = 2.0  # 动作返回后说好的处理再保留这么久（点完弹框可能稍后才到）
_region: dict[str, region.Region] = {}  # 会话 → 开它时的语言 / 时区（region.py）
_region_last: region.Region = region.pick()  # 最近一次 goto 要的地区：别的动作新开会话时沿用
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


LAUNCH_RETRY_S = 30  # Chromium 起不来后这么久内不再硬试（每次试要几秒，模型连着调会一直卡）
_launch_error: tuple[float, str] | None = None


def launch_reason(err: BaseException | str) -> str:
    """Chromium 起不来时给模型和人看的一句话（只这一处判断原因）。
    缺系统库 / 没装浏览器（镜像和 playwright 版本对不上）/ 内存不够 / 其它取第一行有内容的话。"""
    text = str(err)
    libs = re.findall(r"\b(lib[\w.+-]+\.so[\w.]*)", text)
    if libs or "missing dependencies" in text.lower():
        names = "、".join(dict.fromkeys(libs[:3])) or "若干系统库"
        why = f"缺少系统库 {names}"
    elif "executable doesn't exist" in text.lower() or "playwright install" in text:
        why = "镜像里没有对应版本的 Chromium（playwright 版本和镜像对不上）"
    elif re.search(r"cannot allocate memory|out of memory|enomem", text, re.I):
        why = "服务器内存不够"
    else:
        line = next((x.strip() for x in text.splitlines() if x.strip() and not set(x.strip()) <= set("=═╔╗╚╝║─-")), "未知错误")
        why = line[:160]
    return f"云浏览器没能启动：{why}。这不是网页的问题，马上重试也没用；请告诉用户需要管理员修复 browser 服务（重建镜像或加内存）。"


def _forget_browser() -> None:
    """Chromium 进程没了（崩溃 / 被 OOM 杀）：会话全作废，下次用到重新起。登录状态早在每次操作后存过档。"""
    global _browser
    _browser = None
    for name in list(_sessions):
        _sessions.pop(name, None)
        _tabs.pop(name, None)
        _used.pop(name, None)
        _region.pop(name, None)
        _drop_downloads(name)
        _egress.forget(name)
        _forget_dialogs(name)
        asyncio.ensure_future(_live_end(name))  # 看着的人收到“浏览器已关闭”


async def _ensure_browser() -> Browser:
    """在 _lock 里调：第一次用到时才起 Chromium（会话和渲染共用一个进程，小 VPS 只养一个）。
    起不来 → 503 + launch_reason（不是 500 "Internal Server Error"）；进程死了 → 作废会话重起。"""
    global _pw, _browser, _launch_error
    if _browser and not _browser.is_connected():
        _forget_browser()
    if not _browser:
        if _launch_error and time.time() - _launch_error[0] < LAUNCH_RETRY_S:
            raise HTTPException(503, _launch_error[1])
        if not _egress.port:
            await _egress.start()
        try:
            if not _pw:
                _pw = await async_playwright().start()
            # proxy per-context：先给浏览器一个占位代理，每个会话再用自己的代理账号（被拦记到对的会话上）；
            # WebRTC 只许走代理（不然 UDP 能绕过关卡直连内网）
            # 不自报“受自动化控制”（identity.py：用户亲手过人机验证时 Cloudflare 看的就是这些）
            _browser = await _pw.chromium.launch(proxy={"server": "http://per-context"}, args=[
                # 无头不需要 GPU；不关的话 SwiftShader 的 gpu-process 在 2 核 VPS 上空转吃满一核
                "--disable-gpu", "--disable-dev-shm-usage", "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                *identity.LAUNCH_ARGS], ignore_default_args=identity.IGNORE_DEFAULT_ARGS)
        except Exception as e:
            _launch_error = (time.time(), launch_reason(e))
            raise HTTPException(503, _launch_error[1])
        _launch_error = None
    return _browser


async def _session(name: str, want: region.Region | None = None) -> Page:
    """want = 这次 goto 要的地区；已开着的同名会话地区不同 → 存好登录状态重开（region.needs_reopen）。"""
    async with _lock:
        await _ensure_browser()
        if want is not None and name in _sessions and region.needs_reopen(_region.get(name), want):
            await _evict(name)
        if name not in _sessions:
            reg = want or _region_last
            while len(_sessions) >= MAX_SESSIONS:
                await _evict(min(_sessions, key=lambda n: (_watched_now(n), _used.get(n, 0))))  # 先关没人看的
            path = _state_path(name)
            saved = os.path.exists(path)
            ctx = await _browser.new_context(viewport=VIEW, **reg.options(), user_agent=identity.user_agent(getattr(_browser, "version", "")),
                                             storage_state=path if saved else None, accept_downloads=True,
                                             proxy=_egress.proxy_for(name), service_workers="block")
            if saved:
                _restored.add(name)
            else:
                _restored.discard(name)
            await ctx.route("**/*", _guard)
            ctx.on("page", lambda p, n=name: _on_page(n, p))  # 网站开的新标签页：记下（follow 切过去）+ 收下载
            page = await ctx.new_page()
            _tabs[name] = tabs.Tabs(page)
            _watch(name, page)
            _sessions[name] = (ctx, page)
            _region[name] = reg
    _used[name] = time.time()
    return await _follow(name)


def _on_page(name: str, page) -> None:
    if name in _tabs:
        _tabs[name].on_page(page)
    _watch(name, page)


async def _follow(name: str) -> Page:
    """照 tabs.follow 换到该用的标签页：开新页 / 关崩掉和多余的页都在这里做。"""
    ctx, _ = _sessions[name]
    t = _tabs[name]
    mv = tabs.follow(t, list(ctx.pages))
    for p in mv.close:
        try:
            await p.close()
        except Exception:
            pass
    page = mv.page
    if page is None:
        page = await ctx.new_page()
        t.adopt(page)
        _watch(name, page)
        if mv.reload:
            try:
                await page.goto(mv.reload, timeout=30000, wait_until="domcontentloaded")
            except Exception:
                pass  # 重开也失败：快照照常给出（多半是空白 / 错误页），tab 字段已说明崩过
    _sessions[name] = (ctx, page)
    _cast_follow(name)
    return page


async def _evict(name: str) -> None:
    """存好登录状态再关：下次用到同名会话会自动恢复登录。"""
    try:
        await _save(name)
    except Exception:
        pass
    await _live_end(name)
    _remember_url(name, _sessions[name][1])
    ctx, _ = _sessions.pop(name)
    _tabs.pop(name, None)
    _used.pop(name, None)
    _region.pop(name, None)
    await ctx.close()
    _drop_downloads(name)
    _egress.forget(name)
    _forget_dialogs(name)


# ---- 下载中转 ----
_watched: set[int] = set()


def _watch(name: str, page) -> None:
    if id(page) in _watched:
        return
    _watched.add(id(page))
    page.on("download", lambda d: asyncio.ensure_future(_keep(name, d)))
    page.on("crash", lambda p, n=name: _tabs[n].on_crash(p) if n in _tabs else None)
    page.on("dialog", lambda d, n=name: asyncio.ensure_future(_on_dialog(n, d)))  # 有人接 = Playwright 不再自动取消


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
({start, cap, shadowDepth, shadowRoots}) => {
  const sel = 'a[href],button,input,textarea,select,[role=button],[role=link],[role=tab],[role=checkbox],[contenteditable=true]';
  const out = []; let n = start; const end = start + cap;
  // 文档顺序深度优先，组件先走它的 open 影子树（规则在 shadow.py；定位器自己穿透影子树）
  const all = [], roots = [];
  const walk = (root, depth) => {
    for (const el of root.querySelectorAll('*')) {
      all.push(el);
      if (el.shadowRoot && depth < shadowDepth) { roots.push(el); walk(el.shadowRoot, depth + 1); }
    }
  };
  walk(document, 0);
  all.forEach(e => e.hasAttribute('data-ref') && e.removeAttribute('data-ref'));
  const shadow = [];
  for (const host of roots) {
    if (shadow.length >= shadowRoots) break;
    const r = host.getBoundingClientRect(); if (r.width < 1 || r.height < 1) continue;
    const t = [...host.shadowRoot.childNodes].map(x => x.nodeType === 3 ? x.data
      : (x.nodeType !== 1 || ['STYLE', 'SCRIPT', 'SLOT', 'TEMPLATE'].includes(x.tagName)) ? '' : (x.innerText || '')).join('\\n');
    if (t.trim()) shadow.push([host.tagName.toLowerCase(), t]);
  }
  for (const el of (cap > 0 ? all.filter(e => e.matches(sel)) : [])) {
    // 文件框常被藏起来（样式化的“上传”按钮盖在上面），照样编号：browser_upload 直接往里放文件
    const file = el.tagName === 'INPUT' && el.type === 'file';
    const r = el.getBoundingClientRect();
    if (!file && (r.width < 2 || r.height < 2 || r.bottom < 0 || r.top > innerHeight * 3)) continue;
    const st = getComputedStyle(el); if (!file && (st.visibility === 'hidden' || st.display === 'none')) continue;
    const ref = String(++n); el.setAttribute('data-ref', ref);
    // 密码框、钱包代填过的卡号/安全码框（data-secret，v2.74）、浏览器认得的卡号/安全码框，值绝不进快照
    const hidden = el.type === 'password' || file || el.hasAttribute('data-secret') || /^cc-(number|csc)$/.test(el.autocomplete || '');
    const val = hidden ? '' : el.value;
    const label = file ? ((el.labels && el.labels[0] && el.labels[0].innerText) || el.accept || '选择文件') : '';
    // 下拉框 / 勾选框：名字取标签（innerText 是全部选项糊在一起，value 是 "on"），状态单独给（v2.53 forms.py）
    const sel_ = el.tagName === 'SELECT', tick = el.tagName === 'INPUT' && (el.type === 'checkbox' || el.type === 'radio');
    const lab = (el.labels && el.labels[0] && el.labels[0].innerText) || '';
    const raw = sel_ || tick ? (el.getAttribute('aria-label') || lab || el.title || el.name || '')
                             : (el.getAttribute('aria-label') || el.innerText || val || el.placeholder || lab || el.title || el.alt || label || '');
    const name = raw.trim().replace(/\\s+/g, ' ').slice(0, 80);
    const item = { ref, tag: el.tagName.toLowerCase(), type: el.type || '', name };
    if (sel_) {
      const o = el.options[el.selectedIndex];
      item.value = o ? o.text.trim().replace(/\\s+/g, ' ') : '';
      item.options = [...el.options].slice(0, 40).filter(x => !x.disabled).map(x => x.text.trim().replace(/\\s+/g, ' ').slice(0, 40));
      item.count = [...el.options].filter(x => !x.disabled).length;
    }
    if (tick) item.checked = el.checked;
    if (el.disabled) item.disabled = true;
    out.push(item);
    if (n >= end) break;
  }
  return { url: location.href, title: document.title, text: document.body ? document.body.innerText : '', elements: out, shadow };
}
"""


def _tidy(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text or "").strip()


async def _frames_in(frame, depth: int = 1):
    """主页面下的内嵌框，按文档顺序（深度优先），带深度。"""
    for child in frame.child_frames:
        yield child, depth
        if depth < frames.DEPTH_MAX:
            async for sub in _frames_in(child, depth + 1):
                yield sub


async def _frame_box(frame) -> dict | None:
    try:
        el = await frame.frame_element()
        return await el.bounding_box()
    except Exception:
        return None  # 框已脱离 / 跨站框拿不到位置：当看不见


async def _snapshot(name: str, page: Page) -> dict:
    """主页面 + 看得见的内嵌框拍成一张快照（收哪些框、编号、文字规则在 frames.py）；记住每个 ref 在哪个框。"""
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=8000)
    except Exception:
        pass
    snap = await page.evaluate(SNAPSHOT_JS, {"start": 0, "cap": frames.ELEMENT_MAX, **shadow.js_args()})
    where: dict[str, object] = {}
    parts: list[tuple[str, str]] = []
    taken = more = 0
    async for frame, depth in _frames_in(page.main_frame):
        if not frames.include(frame.url, await _frame_box(frame), depth):
            continue
        if taken >= frames.FRAME_MAX:
            more += 1
            continue
        try:
            sub = await frame.evaluate(SNAPSHOT_JS, {"start": len(snap["elements"]), "cap": frames.budget(len(snap["elements"])),
                                                       **shadow.js_args()})
        except Exception:
            continue  # 框正在跳转 / 刚被删：这次不收
        taken += 1
        lab = frames.label(frame.url, page.url)
        for e in sub["elements"]:
            e["frame"] = lab
            where[e["ref"]] = frame
        snap["elements"] += sub["elements"]
        parts.append((lab, _tidy(shadow.merge_text(_tidy(sub["text"]), sub.pop("shadow", [])))))
    _frame_of[name] = where
    main = shadow.merge_text(_tidy(snap["text"]), snap.pop("shadow", []))
    snap["text"] = frames.merge_text(main, parts, MAX_TEXT)
    if more:
        snap["frames_more"] = more
    return snap


def _ref(name: str, page: Page, ref: str):
    """ref → 元素定位器：在内嵌框里的去那个框找（快照时记下的），其余在主页面。"""
    frame = _frame_of.get(name, {}).get(ref)
    if frame is not None and not frame.is_detached():
        return frame.locator(f'[data-ref="{ref}"]')
    return page.locator(f'[data-ref="{ref}"]')


def _with_blocked(name: str, snap: dict) -> dict:
    """附上这个会话上次以来被出网关卡拦下的请求（[{host, reason}]）、标签页的变化（tab，tabs.py）
    和弹过的框（dialogs，dialogs.py），没有就不带。"""
    blocked = _egress.take_blocked(name)
    if blocked:
        snap["blocked"] = blocked
    shown = _dialog_notes.pop(name, None)
    if shown:
        snap["dialogs"] = shown
    note = _tabs[name].take_note() if name in _tabs else None
    if note:
        snap["tab"] = note
    return snap


async def _after(name: str) -> dict:
    """动作做完：先跟到该看的标签页（网站可能开了新页 / 关了页 / 崩了），存登录，再拍快照。"""
    page = await _follow(name)
    await _save(name)
    return _with_blocked(name, await _snapshot(name, page))


class GotoIn(BaseModel):
    url: str
    locale: str | None = None    # BCP 47，后端按“回复语言”给（region.py）；新开 / 地区变了才用
    timezone: str | None = None  # IANA，后端 settings.timezone


class ActIn(BaseModel):
    action: str             # click | type | select | press | scroll | back
    ref: str | None = None
    text: str | None = None
    submit: bool = False
    dy: int = 600
    dialog: str | None = None       # 这次动作弹出 confirm / prompt 时：accept | dismiss（没说 = 取消，dialogs.py）
    dialog_text: str | None = None  # prompt 确定时填的字


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


@app.post("/sessions/{name}/goto", dependencies=[Depends(auth)])
async def goto(name: str, body: GotoIn):
    if urlparse(body.url).scheme not in ("http", "https"):
        raise HTTPException(400, "只允许 http(s)")
    global _region_last
    _region_last = region.pick(body.locale, body.timezone)
    page = await _session(_check_name(name), _region_last)
    _arm(name, None)
    try:
        await page.goto(body.url, timeout=30000, wait_until="domcontentloaded")
    except Exception as e:
        crashed = id(page) in _tabs[name].crashed  # 打开时渲染进程崩了：_after 照 tabs 规则重开一次并说明
        if "Download is starting" not in str(e) and not crashed:  # 网址直接是个文件：不是打不开，是下载了（后端随后取走）
            blocked = _egress.take_blocked(name)
            if blocked:  # 打开的地址（或它的重定向）进了内网：说清楚是被拦，不是网站坏了
                raise HTTPException(403, "被拦下：" + "；".join(b["reason"] for b in blocked[:3])
                                    + "。助手的浏览器不能访问内网 / 本机地址。")
            raise HTTPException(502, f"打不开：{e}")
        await page.wait_for_timeout(1500)
    snap = await _after(name)
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
    return _with_blocked(name, await _snapshot(name, await _session(_check_name(name))))


@app.post("/sessions/{name}/act", dependencies=[Depends(auth)])
async def act(name: str, body: ActIn):
    page = await _session(_check_name(name))
    el = _ref(name, page, body.ref) if body.ref else None
    if el is not None and body.action in ("click", "type", "select", "press") and await _gone(el):
        # 编号是上一张快照的（页面换了 / 切到了新标签页）：马上说清楚，不空等 8 秒超时
        raise HTTPException(400, f"当前页（{(await page.title())[:40] or page.url}）上没有编号 {body.ref}：页面已经换了，"
                                 "编号以最新那张快照为准；要点原来那页的东西先 browser_back。")
    _arm(name, dialogs.arm(body.dialog), body.dialog_text)
    try:
        match body.action:
            case "click":
                await el.click(timeout=8000)
            case "type":
                await el.fill(body.text or "", timeout=8000)
                if body.submit:
                    await el.press("Enter")
            case "select":
                await _select(el, body.text or "")
            case "press":
                key = _key(body.text)
                await (el.press(key, timeout=8000) if el is not None else page.keyboard.press(key))
            case "scroll":
                await page.mouse.wheel(0, body.dy)
            case "back":
                await _back(name, page)
            case _:
                raise HTTPException(400, "未知动作")
        await page.wait_for_timeout(800)
    except HTTPException:
        raise
    except Exception as e:
        if id(page) not in _tabs[name].crashed and not page.is_closed():
            raise HTTPException(400, f"操作失败：{str(e)[:200]}")
        # 点的时候页面崩了 / 被网站关了：不算操作失败，_after 照 tabs 规则换页并在 tab 字段里说明
    finally:
        _disarm(name)
    return await _after(name)


def _arm(name: str, armed: str | None, text: str | None = None) -> None:
    """动作开始：说好这次弹框怎么办（dialogs.decide 用），连环弹框计数清零。"""
    _dialog_arm[name] = (armed, text, float("inf"))
    _dialog_seen[name] = 0


def _disarm(name: str) -> None:
    """动作结束：说好的处理只再管 ARM_AFTER_S 秒（点击触发的弹框可能晚一点到）。"""
    armed, text, _ = _dialog_arm.get(name, (None, None, 0.0))
    _dialog_arm[name] = (armed, text, time.time() + ARM_AFTER_S)


async def _on_dialog(name: str, dialog) -> None:
    """弹框当场按 dialogs.decide 处理并记下；处理失败（页面已关）就算了。"""
    armed, text, until = _dialog_arm.get(name, (None, None, 0.0))
    if time.time() > until:
        armed, text = None, None
    seen = _dialog_seen.get(name, 0)
    _dialog_seen[name] = seen + 1
    d = dialogs.decide(dialog.type, dialog.message, dialog.default_value, armed, seen, text)
    notes = _dialog_notes.setdefault(name, [])
    if len(notes) < dialogs.DIALOGS_MAX:
        notes.append(d.note)
    elif notes[-1].get("more") is None:
        notes.append({"kind": "more", "more": 1})
    else:
        notes[-1]["more"] += 1
    try:
        if not d.accept:
            await dialog.dismiss()
        elif d.text is not None:
            await dialog.accept(d.text)
        else:
            await dialog.accept()
    except Exception:
        pass


def _forget_dialogs(name: str) -> None:
    for m in (_dialog_arm, _dialog_notes, _dialog_seen, _frame_of):  # 会话没了：弹框状态和内嵌框 ref 一起清
        m.pop(name, None)


def _key(name: str | None) -> str:
    try:
        return forms.key(name or "")
    except forms.KeyError_ as e:
        raise HTTPException(400, str(e))


async def _select(el, want: str) -> None:
    """原生下拉框按选项文字 / 值选一项（forms.pick 定哪一项）；不是 <select> → 说清楚改用点击。"""
    info = await el.evaluate("e => e.tagName === 'SELECT' ? [...e.options].map(o => ({text: o.text, value: o.value, disabled: o.disabled})) : null")
    if info is None:
        raise HTTPException(400, "这个不是原生下拉框：先 browser_click 点开它，再在新快照里点要的那一项。")
    try:
        index = forms.pick(info, want)
    except forms.PickError as e:
        raise HTTPException(400, str(e))
    await el.select_option(index=index, timeout=8000)


async def _gone(el) -> bool:
    try:
        return await el.count() == 0
    except Exception:
        return False


async def _back(name: str, page: Page) -> None:
    """后退。网站开的弹出页退到头了（没有上一页、网址没变）→ 关掉它，follow 退回原来那页（tab.kind = returned）。"""
    before = page.url
    went = await page.go_back(timeout=15000)
    if went is None and page.url == before and await page.opener() is not None and len(_sessions[name][0].pages) > 1:
        await page.close()
        await _follow(name)
        t = _tabs[name]
        if t.note and t.note.get("kind") == "closed":
            t.note["kind"] = "returned"


@app.post("/sessions/{name}/login", dependencies=[Depends(auth)])
async def login(name: str, body: LoginIn):
    """代填登录：密码只在这里出现一次，直接进输入框，返回的快照里没有它。"""
    page = await _session(_check_name(name))
    _arm(name, None)
    try:
        await _ref(name, page, body.user_ref).fill(body.username, timeout=8000)
        pw = _ref(name, page, body.pass_ref)
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
    return await _after(name)


class CardField(BaseModel):
    ref: str
    value: str
    options: list[str] = []  # 下拉框依次试的写法（wallet.fields 给）
    secret: bool = False     # 卡号 / 安全码：填完打 data-secret，之后的快照不带它的值


class CardIn(BaseModel):
    fields: list[CardField]


@app.post("/sessions/{name}/card", dependencies=[Depends(auth)])
async def card(name: str, body: CardIn):
    """钱包代填付款卡（v2.74，规则在后端 app/wallet.py）：卡号只在这里出现一次，直接进框，返回的快照里没有它。
    不点付款（付款按钮照常由 browser_click 点）。"""
    page = await _session(_check_name(name))
    _arm(name, None)
    try:
        for f in body.fields:
            el = _ref(name, page, f.ref)
            if await _gone(el):
                raise HTTPException(400, f"当前页上没有编号 {f.ref}：页面已经换了，先 browser_look 拿新快照")
            if await el.evaluate("e => e.tagName === 'SELECT'"):
                await _select_any(el, f.options or [f.value])
                continue
            if f.secret:
                await el.evaluate("e => e.setAttribute('data-secret', '1')")
            await el.fill(f.value, timeout=8000)
        await page.wait_for_timeout(800)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"代填失败：{str(e)[:200]}")
    finally:
        _disarm(name)
    return await _after(name)


async def _select_any(el, wants: list[str]) -> None:
    """有效期下拉框：按 wallet 给的几种写法依次试（09 / 9 / 9月 / Sep…），都对不上说清楚。"""
    info = await el.evaluate("e => [...e.options].map(o => ({text: o.text, value: o.value, disabled: o.disabled}))")
    for w in wants:
        try:
            index = forms.pick(info, w)
        except forms.PickError:
            continue
        await el.select_option(index=index, timeout=8000)
        return
    raise HTTPException(400, f"下拉框里没有 {wants[0]} 这一项：用 browser_select 自己选")


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
    el = _ref(name, page, body.ref)
    _arm(name, None)
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
    return await _after(name)


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
                                        offline=True, service_workers="block", locale=_region_last.locale)
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


# ---- 截图（助手看一眼 browser_look / 存文件 browser_screenshot）----
SHOT_FORMATS = ("jpeg", "png")
SHOT_HEIGHT_JS = "Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0)"


@app.get("/sessions/{name}/screen", dependencies=[Depends(auth)])
async def screen(name: str, format: str = "jpeg", full: bool = False, quality: int = 60):
    """当前画面。默认 = JPEG q60 视口（助手 browser_look）；存文件（backend browser_shot）用 png / full=整页。
    整页高过 RENDER_PNG_MAX_H 只截最上面那一段，X-Shot-Cut: 1。"""
    if format not in SHOT_FORMATS:
        raise HTTPException(400, "format 只能是 jpeg 或 png")
    if _browser and not _browser.is_connected():
        _forget_browser()
    if name not in _sessions:
        raise HTTPException(404)
    page = await _follow(name)  # 画面跟着当前标签页（网站开的新页、崩了重开的页）
    kw: dict = {"type": format}
    if format == "jpeg":
        kw["quality"] = max(30, min(95, quality))
    cut = False
    if full:
        kw["full_page"] = True
        try:
            height = int(await page.evaluate(SHOT_HEIGHT_JS))
        except Exception:
            height = 0
        if height > RENDER_PNG_MAX_H:
            kw["clip"] = {"x": 0, "y": 0, "width": (page.viewport_size or {}).get("width", 1280), "height": RENDER_PNG_MAX_H}
            cut = True
    return Response(await page.screenshot(**kw), media_type=f"image/{format}", headers={"X-Shot-Cut": "1" if cut else "0"})


NAV_TIMEOUT_MS = 15_000


# ---- 实时画面（v2.89 §M）：一条 WS = 下行 JPEG 帧（CDP screencast）+ 上行接管输入；规则在 live.py ----
class _Live:
    """一个会话的推流：观看者们 + 挂在当前标签页上的 CDP screencast。"""

    def __init__(self) -> None:
        self.hub = live.Hub()
        self.page = None
        self.cdp = None
        self.width = 0
        self.lock = asyncio.Lock()
        self.sockets: list = []


_live: dict[str, _Live] = {}


def _watched_now(name: str) -> bool:
    lv = _live.get(name)
    return bool(lv and lv.hub.viewers)


async def _cast_stop(lv: _Live) -> None:
    cdp, lv.cdp, lv.page, lv.width = lv.cdp, None, None, 0
    if cdp is None:
        return
    try:
        await cdp.send("Page.stopScreencast")
        await cdp.detach()
    except Exception:
        pass  # 页面已关 / 崩了：会话跟着没了


async def _ack(cdp, sid) -> None:
    try:
        await cdp.send("Page.screencastFrameAck", {"sessionId": sid})
    except Exception:
        pass  # 会话已拆


async def _cast(name: str) -> None:
    """让 screencast 挂在会话的当前标签页、按观看者的宽度推；没人看就停（0 开销）。换页 / 换宽度才重挂。"""
    lv = _live.get(name)
    if lv is None:
        return
    async with lv.lock:
        if not lv.hub.viewers or name not in _sessions:
            await _cast_stop(lv)
            return
        ctx, page = _sessions[name]
        width = lv.hub.width(live.MAX_DIMENSION)
        if lv.page is page and lv.width == width and lv.cdp is not None:
            return
        await _cast_stop(lv)
        try:
            cdp = await ctx.new_cdp_session(page)

            def frame(ev, cdp=cdp):
                asyncio.ensure_future(_ack(cdp, ev.get("sessionId")))  # 立刻 ack，Chrome 才继续出帧；慢的观看者靠 latest-frame-wins 跳帧
                if lv.cdp is cdp:
                    lv.hub.deliver(base64.b64decode(ev.get("data") or ""))

            cdp.on("Page.screencastFrame", frame)
            # 先登记再开：第一帧可能在 startScreencast 返回之前就到（静止页面只有这一帧，丢了就一直黑屏）
            lv.cdp, lv.page, lv.width = cdp, page, width
            await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": live.DEFAULT_QUALITY,
                                                    "maxWidth": width, "maxHeight": width, "everyNthFrame": 1})
        except Exception:
            lv.cdp, lv.page, lv.width = None, None, 0
            return  # 页面正在关 / 崩：下一次 _follow 或输入会再挂


def _cast_follow(name: str) -> None:
    """_follow 换了标签页（网站开新页、崩了重开）：有人在看就把推流挂过去。"""
    lv = _live.get(name)
    if lv and lv.hub.viewers and lv.page is not _sessions[name][1]:
        asyncio.ensure_future(_cast(name))


async def _live_end(name: str) -> None:
    """会话关了：所有观看者断开（客户端收到 4404 → “浏览器已关闭”+“重新打开”）。"""
    lv = _live.pop(name, None)
    if lv is None:
        return
    lv.hub.close_all()
    await _cast_stop(lv)
    for ws in list(lv.sockets):
        try:
            await ws.close(live.CLOSE_NOT_OPEN, "浏览器已关闭")
        except Exception:
            pass


def _last_url_path(name: str) -> str:
    return f"{STATE}/{name}.last"


def _remember_url(name: str, page) -> None:
    """关会话前记下最后网址：“重新打开”用存好的登录回到这里。"""
    url = getattr(page, "url", "") or ""
    if not url.startswith(("http://", "https://")):
        return
    try:
        os.makedirs(STATE, exist_ok=True)
        with open(_last_url_path(name), "w", encoding="utf-8") as f:
            f.write(url[:2000])
    except OSError:
        pass


async def _reopen(name: str) -> None:
    """“重新打开”：同名会话用存好的登录状态开起来，回到最后网址（出网关卡照样管，内网进不去）。"""
    page = await _session(name)
    try:
        with open(_last_url_path(name), encoding="utf-8") as f:
            url = f.read().strip()
    except OSError:
        url = ""
    if url and page.url in ("", "about:blank"):
        try:
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        except Exception:
            pass  # 打不开：画面照样推（错误页），用户自己看得到


async def _input(name: str, cmd: dict) -> None:
    """用户在接管页里亲手操作（live.parse 洗过的命令）。坐标 0–1 × 视口。
    click/up/text/key = 一次完整操作：弹出的确认框就是他要确认的（dialogs 规则 5）、跟新标签页、存登录态；
    move 只移动（拖动中 / 悬停时一秒十几次），down 只按下。"""
    if name not in _sessions:
        return
    _used[name] = time.time()
    page = await _follow(name)
    t = cmd["t"]
    if t == "view":
        return
    x, y = cmd.get("x", 0.5) * VIEW["width"], cmd.get("y", 0.5) * VIEW["height"]
    if t == "mouse" and cmd["kind"] == "move":
        await page.mouse.move(x, y, steps=2)
        return
    if t == "mouse" and cmd["kind"] == "down":
        await page.mouse.move(x, y)
        await page.mouse.down()
        return
    if t == "wheel":
        await page.mouse.move(x, y)
        await page.mouse.wheel(cmd["dx"], cmd["dy"])
        return
    if t == "nav":
        try:
            if cmd["action"] == "back":
                await page.go_back(timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
            else:
                await page.reload(timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
        except Exception as e:  # noqa: BLE001 —— 只吞超时（测试里 playwright 是桩，按类名认）
            if type(e).__name__ != "TimeoutError":
                raise  # 慢页面超时：画面会自己跟上，不当错误
    else:
        _arm(name, "accept")
        try:
            if t == "mouse" and cmd["kind"] == "up":
                await page.mouse.move(x, y, steps=2)
                await page.mouse.up()
            elif t == "mouse":  # 一次完整的点：移过去 → 按下 → 按住真实时长 → 抬起（规则见 live.py 文件头）
                await page.mouse.move(x, y, steps=live.APPROACH_STEPS)
                await page.mouse.down()
                await asyncio.sleep(cmd["hold"] / 1000)
                await page.mouse.up()
            elif t == "text":
                await page.keyboard.type(cmd["text"], delay=20)
            elif t == "key":
                await page.keyboard.press(cmd["key"])
        finally:
            _disarm(name)
    if name in _sessions:
        await _follow(name)  # 用户在画面里点开了新标签页：推流跟过去（_follow 里接）
        await _save(name)


@app.websocket("/sessions/{name}/live")
async def live_ws(ws: WebSocket, name: str, open: bool = False):
    """实时画面 + 接管。open=1 = 浏览器关着就用存好的登录重开（客户端“重新打开”）。
    关闭码见 live.CLOSE_*。每个连接、每条输入都算“在用”；有人在看，空闲回收不关它。"""
    if ws.headers.get("authorization") != f"Bearer {TOKEN}":
        await ws.close(live.CLOSE_UNAUTHORIZED)
        return
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
        await ws.close(live.CLOSE_BAD_NAME)
        return
    await ws.accept()
    if _browser and not _browser.is_connected():
        _forget_browser()
    if name not in _sessions:
        if not open:
            await ws.close(live.CLOSE_NOT_OPEN, "浏览器已关闭")
            return
        try:
            await _reopen(name)
        except HTTPException as e:
            await ws.close(live.CLOSE_DOWN, str(e.detail)[:120])
            return
    lv = _live.setdefault(name, _Live())
    viewer = live.Viewer()
    lv.hub.join(viewer)
    lv.sockets.append(ws)
    _used[name] = time.time()
    await _cast(name)

    async def pump():
        while (frame := await viewer.next()) is not None:
            await ws.send_bytes(frame)

    sender = asyncio.ensure_future(pump())
    try:
        while True:
            cmd = live.parse(await ws.receive_text())
            if cmd is None:
                continue
            if cmd["t"] == "view":
                viewer.px = cmd["px"]
                await _cast(name)
                continue
            try:
                await _input(name, cmd)
            except Exception:
                pass  # 一次操作失败（页面正在跳转）不断线；画面会说明一切
            if name not in _sessions:
                break
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        sender.cancel()
        lv.hub.leave(viewer)
        if ws in lv.sockets:
            lv.sockets.remove(ws)
        if name in _sessions:
            _used[name] = time.time()  # 刚看完也算刚用过
            if not lv.hub.viewers:
                await _cast(name)  # 最后一个人走了：停推
    if name not in _sessions:
        try:
            await ws.close(live.CLOSE_NOT_OPEN, "浏览器已关闭")
        except RuntimeError:
            pass


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
                await _live_end(name)
                ctx, _ = _sessions.pop(name)
                _tabs.pop(name, None)
                _used.pop(name, None)
                _region.pop(name, None)
                await ctx.close()
                _drop_downloads(name)
                _egress.forget(name)
                _forget_dialogs(name)
            else:
                await _evict(name)
        _restored.discard(name)
        if forget:
            for path in (_state_path(name), _meta_path(name), _last_url_path(name)):
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass
    return {"ok": True}


def _idle_out(now: float) -> list[str]:
    """空闲超过 IDLE 该关的会话；有人在看 / 接管的不算（用户 18:38“动不动就断”）。"""
    return [n for n, t in list(_used.items()) if now - t > IDLE and n in _sessions and not _watched_now(n)]


async def _reaper():
    while True:
        await asyncio.sleep(60)
        for name in _idle_out(time.time()):
            async with _lock:
                if name in _sessions:
                    await _evict(name)


@app.on_event("startup")
async def _start():
    asyncio.create_task(_reaper())
