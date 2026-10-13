"""云浏览器工具。模型看到的是“快照”：页面文字 + 编号的可点元素（[12] 按钮 登录）。
用户在聊天里看到实时画面卡，随时可以接管（输入密码、过验证码）。
付款、下单、发送这类按钮要先审批。浏览器很费 token，能用 web_search/web_fetch 解决的不要开浏览器。

会话（v1.26，规则在 app/browser_sessions.py）：browser_open 按网站起会话名（taobao.com → taobao-com），
同一网站的所有任务共用它，登录一次以后都在；也可显式传 session 接着某个会话。之后的点击/输入/截图
都作用于这段对话“当前”的会话（Tab）。打开网页期间先推一张实时画面卡（ctx.live），页面打开后换成最终卡。

接管（v1.29）：图形验证码、滑块、扫码、人机验证、要手机批准的登录，模型调 browser_handoff(reason)：
同会话的画面卡上出“需要你来”条（handoff pending），这一步挂起等用户在画面里弄完点“交还”（复用表单通道 form.reply），
交还后重新读页面接着做；点“做不了”/ 10 分钟没人回 → 告诉模型别再弹。定时任务里没人能接管，直接说明。

文件（v1.32，规则在 app/browser_files.py）：browser_upload 把工作区文件放进网页的文件框；页面触发的下载在每个动作之后
自动搬进工作区 downloads/（_after），模型被告知路径；搬过的文件记在画面卡的 files 上（用户点了能打开）。

登录过期（v1.36，判定在 browser_sessions.observe）：每张快照都经 _view：之前登录过的会话又是登录页 → 在快照前
告诉模型“登录过期了”和怎么重登（保险箱有 → browser_login 直接重登；没有 → 登录卡 / 接管；定时任务里没人 →
如实说明，并在 Home 上发一张系统提醒“X 的登录过期了”，带“去做”让用户在聊天里一键重登）。重登成功 → 收起提醒。
自动登录（v2.50）：登录页（过期或第一次）+ 保险箱有 + login_fields 判得准 → _view 里直接代填一次，模型拿到的是登录后的页面。"""
import re
import time
import uuid

import asyncio

from ... import browser_client, browser_files, browser_sessions, browser_shot, deliver, egress_note, file_edit, file_seen, system_alerts, task_wall, vault, web_guard
from ...storage import project_dir
from ...browser_sessions import Tab
from ...config import settings
from .. import approvals
from ..approvals import FormReply
from ..tools import ToolContext, ToolImage, ToolResult, nobody, tool

RISKY_BUTTON = re.compile(r"支付|付款|购买|下单|提交订单|确认订单|发送|发布|删除|pay|buy|purchase|checkout|place order|send|post|delete", re.I)
NOT_OPEN = "这段对话还没打开浏览器，先用 browser_open。"
REASON_MAX = 60


def _tab(ctx: ToolContext) -> Tab:
    return browser_sessions.tab(ctx.conversation_id, ctx.task_id)


def _render(snap: dict, tab: Tab) -> str:
    tab.names.clear()
    tab.url = snap.get("url", "")
    lines = []
    for e in snap.get("elements", []):
        tab.names[e["ref"]] = e["name"]
        kind = e["tag"] + (f":{e['type']}" if e["type"] and e["tag"] == "input" else "")
        lines.append(f"[{e['ref']}] {kind} {e['name']}")
    return (tab_note(snap) + blocked_note(snap) + f"页面：{snap.get('title', '')}\n{snap.get('url', '')}\n\n可操作元素：\n" + "\n".join(lines)
            + f"\n\n页面文字：\n{snap.get('text', '')}")


def blocked_note(snap: dict) -> str:
    """浏览器出网关卡（browser/egress.py）拦下的页面内请求：说法统一在 app/egress_note.py。"""
    return egress_note.note(snap.get("blocked"), "browser")


def tab_note(snap: dict) -> str:
    """标签页变了（规则在 browser/tabs.py，快照的 tab 字段）→ 放在快照最前面的一句话；没变 → 空。"""
    t = snap.get("tab")
    if not isinstance(t, dict):
        return ""
    url, n = str(t.get("url") or ""), t.get("tabs")
    more = f"（现在开着 {n} 个标签页）" if isinstance(n, int) and n > 1 else ""
    match t.get("kind"):
        case "opened":
            return (f"⤷ 网站在新标签页里打开了 {url}，已切过去{more}；之后的点击、输入都在这页上，"
                    "看完要回原来那页用 browser_back。\n")
        case "returned":
            return f"⤷ 这个标签页没有上一页，已关掉它，回到原来的 {url}。\n"
        case "closed":
            if url and not url.startswith("about:"):
                return f"⤷ 刚才那个标签页被网站关掉了，已退回 {url}{more}。\n"
            return "⤷ 网站把页面关掉了，现在是空白页：要接着做就用 browser_open 重新打开要去的网址。\n"
        case "crashed":
            return (f"⚠ 页面崩溃了（多半是页面太重、这台机器内存不够），已自动重新打开 {url}；"
                    "刚才填到一半的内容可能没了，先看这张快照再接着做。\n")
        case "crash_loop":
            return (f"⚠ {url} 刚重开又崩溃了（页面太重、这台机器内存不够），没再重开，现在是空白页。别再反复打开它："
                    "换个轻一点的入口（手机版 m. 域名、搜索结果页，或用 web_fetch 只读文字），实在不行如实告诉用户。\n")
    return ""


def _card(tab: Tab, live: bool = False, files: list[dict] | None = None, ws: str | None = None, down: str | None = None) -> dict:
    block = {"type": "browser", "session": tab.session, "site": browser_sessions.site_of(tab.url) or None, "down": down}
    if live:
        block["live"] = True
    if files:
        block["files"], block["workspace"] = files, ws
    return {k: v for k, v in block.items() if v is not None}


def expired_note(tab: Tab, has_vault: bool, unattended: bool) -> str:
    """登录过期时放在快照前面给模型看的话。"""
    site = browser_sessions.site_of(tab.url) or tab.host
    head = f"⚠ 会话 {tab.session} 之前登录过 {site}，现在出现的是登录页：登录已过期（已记下）。"
    if has_vault:
        return head + "保险箱里有这个网站的登录：直接用 browser_login（填快照里的用户名框、密码框编号）重新登录，不用问用户。"
    if unattended:
        return head + ("现在是定时任务，用户不在，保险箱里也没有登录，没法自己重登：别硬试，如实说明这一步做不了；"
                       "已经在用户的 Home 上放了一张提醒，请他在聊天里让你重新登录。")
    return head + ("保险箱里没有登录：有账号密码框就用 browser_login（会在聊天里弹登录卡给用户填）；"
                   "扫码、滑块、手机批准这类用 browser_handoff 请用户接管。登好后接着做原来的事。")


async def _view(ctx: ToolContext, tab: Tab, snap: dict, auth: bool = False) -> str:
    """快照 → 给模型的文字，顺带判定登录过期 / 登录成功（只此一处调 browser_sessions.observe）。
    v2.50 自动登录：登录页（过期的或第一次要登录的都算）+ 保险箱有这个网站的登录 + 用户名框和密码框判得准
    （browser_sessions.login_fields）→ 每次打开先自动代填一次（_autologin），模型直接拿到登录后的页面；
    判不准 → 告诉模型保险箱里有，用 browser_login。"""
    text = _render(snap, tab)
    event = await browser_sessions.observe(tab, snap, auth)
    if event == "signed_in":
        await _clear_alert(ctx, tab)
        return text
    secret = None
    if browser_sessions.login_page(snap) and not tab.autofilled:
        secret = await vault.find_for_url(ctx.db, tab.url, kind="login")
        refs = browser_sessions.login_fields(snap)
        if secret and secret.username and refs:
            tab.autofilled = True
            again = await _autologin(ctx, tab, secret, refs, expired=event == "expired")
            if again is not None:
                return again
        if secret and event != "expired":
            return (f"⚠ 这页要登录。保险箱里有这个网站的登录「{secret.name}」：用 browser_login（填快照里的用户名框、"
                    "密码框编号）直接登录，不用问用户、也别让用户自己登。\n" + text)
    if event == "expired":
        if secret is None:
            secret = await vault.find_for_url(ctx.db, tab.url, kind="login")
        unattended = ctx.ask is nobody
        if unattended and not secret:
            await _alert(ctx, tab, browser_sessions.alert_subject(tab.session))
        return expired_note(tab, bool(secret), unattended) + "\n" + text
    return text


async def _clear_alert(ctx: ToolContext, tab: Tab) -> None:
    try:
        await system_alerts.clear(ctx.db, browser_sessions.alert_subject(tab.session))
        await ctx.db.commit()  # 0 张也要提交：DELETE 已经拿了写锁
    except Exception:
        await ctx.db.rollback()


async def _autologin(ctx: ToolContext, tab: Tab, secret, refs: tuple[str, str], expired: bool) -> str | None:
    """登录页 → 用保险箱自动代填一次（每次打开最多一次：tab.autofilled）。成功 → 登录后的页面 + 一句说明；
    代填后还是登录页 → 说明没成功、别用同一份密码再试；浏览器代填出错 → None（退回普通提示，让模型自己 browser_login）。"""
    site = browser_sessions.site_of(tab.url) or tab.host
    try:
        snap = await browser_client.snapshot_call(tab.session, "POST", "/login", {
            "user_ref": refs[0], "pass_ref": refs[1], "username": secret.username, "password": vault.reveal(secret)})
    except Exception:  # 代填失败（框变了、超时、浏览器断了、保险箱解不开）：交给模型，下一步自然会碰到同样的错
        return None
    text = _render(snap, tab)
    event = await browser_sessions.observe(tab, snap, auth=True)
    if event == "signed_in":
        await _clear_alert(ctx, tab)
        why = "登录过期了，已" if expired else "要登录，已"
        return (f"⟳ 会话 {tab.session} 在 {site} {why}用保险箱「{secret.name}」自动{'重新' if expired else ''}登录（你看不到密码），"
                "下面是登录后的页面：接着做原来的事，不用再登录、也不用告诉用户。\n" + text)
    head = (f"⚠ 会话 {tab.session} 在 {site} {'的登录过期了' if expired else '要登录'}，已用保险箱「{secret.name}」自动代填过一次，但还停在登录页"
            "（可能要验证码，或保险箱里的密码已经改了）。别用同一份密码反复试：")
    tab.vault_failed = secret.id
    if ctx.ask is nobody:
        await _alert(ctx, tab, browser_sessions.alert_subject(tab.session), stale=True)
        return head + "现在是定时任务、用户不在，如实说明这一步做不了；已在用户的 Home 上放了一张提醒。\n" + text
    return head + ("页面要验证码就用 browser_code，要滑块/扫码就用 browser_handoff；页面说账号或密码错了就用 browser_login："
                   "这次它会在聊天里弹登录卡请用户填新的（勾“记住”就更新保险箱「" + secret.name + "」，你看不到密码），"
                   "直接调就行。绝不要让用户在聊天里把账号密码发给你。\n" + text)


async def _alert(ctx: ToolContext, tab: Tab, subject: str, stale: bool = False) -> None:
    """定时任务碰到登录过期、自己重登不了：Home 上发一张系统提醒（同一会话同一次过期只发一次）。
    stale=True：保险箱里有账号但自动代填没登上（多半密码改了 / 要验证码）。"""
    site = browser_sessions.site_of(tab.url) or tab.host
    why = ("保险箱里的账号自动代填后没登上（密码可能改了，或要验证码），只能你来登一次。" if stale
           else "保险箱里也没有它的账号，只能你来登一次。")
    try:
        await system_alerts.post(
            ctx.db, subject=subject, once="expired", title=f"{site} 的登录过期了",
            text=f"定时任务要用 {site}，但云浏览器里的登录已经失效，{why}",
            open=f"task:{ctx.task_id}" if ctx.task_id else "vault",
            prompt=f"帮我在云浏览器里重新登录 {site}（会话 {tab.session}）。")
        await ctx.db.commit()
    except Exception:  # 提醒发不出去不影响任务本身
        await ctx.db.rollback()


async def _after(ctx: ToolContext, tab: Tab, text: str, card: bool = False) -> ToolResult:
    """每个浏览器动作之后：把页面触发的下载搬进工作区。有搬到的 → 告诉模型并在画面卡上记一笔。"""
    moved = await browser_files.collect(ctx.workspace, tab.session)
    if moved.note:
        text = f"{moved.note}\n{text}"
    blocks = [_card(tab, files=moved.files, ws=ctx.workspace)] if (card or moved.files) else []
    return ToolResult(text, blocks)


def _down(tab: Tab, e: browser_client.BrowserDown) -> ToolResult:
    """浏览器服务不能用：画面卡标 down（不再拉画面），这一步记失败，原因整句给模型。"""
    return ToolResult(str(e), [_card(tab, down=e.short)], failed=e.short)


async def _act(ctx: ToolContext, method: str, path: str, json: dict | None = None) -> ToolResult:
    try:
        r = await _snap(ctx, method, path, json)
    except browser_client.BrowserDown as e:
        return _down(_tab(ctx), e)
    return ToolResult(r) if isinstance(r, str) else await _after(ctx, r[1], r[0])


async def _snap(ctx: ToolContext, method: str, path: str, json: dict | None = None) -> tuple[str, Tab] | str:
    """对当前会话发一个返回快照的请求 → (给模型的文字, tab)；还没打开 → 提示字符串。"""
    tab = _tab(ctx)
    if not tab.session:
        return NOT_OPEN
    return await _view(ctx, tab, await browser_client.snapshot_call(tab.session, method, path, json)), tab


def _click_risk(args: dict, ctx: ToolContext | None = None) -> str | None:
    name = _tab(ctx).names.get(str(args.get("ref")), "") if ctx else ""
    return f"点击「{name}」（可能付款、发送或删除）" if RISKY_BUTTON.search(name) else None


@tool("browser_open", "正在打开网页",
      "在云浏览器打开网址，返回页面快照。用于需要登录、点击、填表的网站；单纯读资料用 web_fetch。"
      "同一个网站自动用同一个会话（按网站命名，如 taobao-com），登录过一次之后的任务都还登录着，不用重登；"
      "要接着之前某个会话（结果里会写会话名）或同一网站换第二个账号时，传 session。",
      {"type": "object", "properties": {"url": {"type": "string"},
                                        "session": {"type": "string", "description": "会话名，可省略（按网站自动起名）"}},
       "required": ["url"]})
async def browser_open(ctx: ToolContext, url: str, session: str = "") -> ToolResult:
    try:  # 浏览器容器和后端同在内网：模型给的地址先过出网检查（之后页面里的每个连接由浏览器的出网关卡 egress.py 再查）
        await web_guard.check(url, unresolved_ok=True)
    except web_guard.Blocked as e:
        return ToolResult(str(e), failed=str(e))
    tab = _tab(ctx)
    name = browser_sessions.clean(session) or browser_sessions.name_for(url)
    switched = tab.session if tab.session and tab.session != name else ""
    tab.session, tab.url = name, url if "://" in url else f"https://{url}"
    tab.names.clear()
    ctx.live(_card(tab, live=True))  # 打开要几秒到几十秒：先让用户看到画面卡
    try:
        snap = await browser_client.snapshot_call(name, "POST", "/goto", {"url": url})
    except browser_client.BrowserDown as e:
        return _down(tab, e)
    tab.opened(snap.get("login"))
    text = await _view(ctx, tab, snap)
    note = ("沿用了这个会话之前保存的登录，先看页面是否已经登录，已登录就别再登录。" if snap.get("restored")
            else "这是新会话（没有保存过的登录）。")
    if switched:
        note += f"（从会话 {switched} 换到了这个；之后的点击、输入都作用于 {name}。）"
    return await _after(ctx, tab, f"会话：{name}。{note}\n" + text, card=True)


@tool("browser_click", "正在点击", "点击快照里编号为 ref 的元素，返回新快照。",
      {"type": "object", "properties": {"ref": {"type": "string"}}, "required": ["ref"]}, risk=_click_risk)
async def browser_click(ctx: ToolContext, ref: str) -> ToolResult:
    return await _act(ctx, "POST", "/act", {"action": "click", "ref": ref})


@tool("browser_type", "正在输入", "在编号为 ref 的输入框里填入文字；submit=true 时随后按回车。"
      "不要用它输入密码或验证码：登录用 browser_login，验证码用 browser_code（都会在聊天里问用户）。",
      {"type": "object", "properties": {"ref": {"type": "string"}, "text": {"type": "string"},
                                        "submit": {"type": "boolean", "default": False}},
       "required": ["ref", "text"]})
async def browser_type(ctx: ToolContext, ref: str, text: str, submit: bool = False) -> ToolResult:
    return await _act(ctx, "POST", "/act", {"action": "type", "ref": ref, "text": text, "submit": submit})


@tool("browser_scroll", "正在滚动页面", "向下（dy>0）或向上滚动页面，返回新快照。",
      {"type": "object", "properties": {"dy": {"type": "integer", "default": 600}}})
async def browser_scroll(ctx: ToolContext, dy: int = 600) -> ToolResult:
    return await _act(ctx, "POST", "/act", {"action": "scroll", "dy": dy})


@tool("browser_back", "正在返回上一页",
      "浏览器后退一页，返回新快照。网站在新标签页里打开的页面退到头时，会关掉这个标签页、回到原来那页。",
      {"type": "object", "properties": {}})
async def browser_back(ctx: ToolContext) -> ToolResult:
    return await _act(ctx, "POST", "/act", {"action": "back"})


@tool("browser_read", "正在查看页面", "重新读取当前页面（例如用户在实时画面里操作完之后）。",
      {"type": "object", "properties": {}})
async def browser_read(ctx: ToolContext) -> ToolResult:
    return await _act(ctx, "GET", "/snapshot")


@tool("browser_look", "正在看页面",
      "截一张云浏览器当前画面给你看（只给你看，不存文件、不交给用户；用户要截图用 browser_screenshot）。"
      "快照文字说不清时再用（图表、图片内容、布局、按钮在哪、页面是否正常显示），比快照费 token，别每步都截。",
      {"type": "object", "properties": {}})
async def browser_look(ctx: ToolContext) -> ToolResult:
    tab = _tab(ctx)
    if not tab.session:
        return ToolResult(NOT_OPEN)
    try:
        r = await browser_client.call(tab.session, "GET", "/screen")
    except browser_client.BrowserDown as e:
        return _down(tab, e)
    if r.status_code == 404:
        return ToolResult("这个会话的浏览器已经关了（空闲太久会自动关），先用 browser_open 重新打开。")
    if r.status_code >= 400:
        raise RuntimeError(f"截图失败（{r.status_code}）")
    return ToolResult("当前页面截图：", [_card(tab)], images=[ToolImage("页面截图.jpg", r.content)])


@tool("browser_screenshot", "正在截图",
      "把云浏览器当前页面截图存成工作区里的图片文件，默认直接作为文件卡交给用户。用户说“截个图给我 / 保存这个页面的样子”时用这个；"
      "不要用 image_search 去网上找截图冒充。full_page=true 截整页长图。不会覆盖已有文件（重名自动编号）。",
      {"type": "object", "properties": {
          "path": {"type": "string", "default": "", "description": f"存到哪（.png / .jpg，相对工作区）；空 = {browser_shot.DIR}/<网站>.png"},
          "full_page": {"type": "boolean", "default": False, "description": "整页长图（默认只截当前可见画面）"},
          "show": {"type": "boolean", "default": True, "description": "存好直接交给用户"}}})
async def browser_screenshot(ctx: ToolContext, path: str = "", full_page: bool = False, show: bool = True) -> ToolResult:
    tab = _tab(ctx)
    if not tab.session:
        return ToolResult(NOT_OPEN)
    root = project_dir(ctx.workspace)
    try:
        first, fmt = browser_shot.target(root, browser_sessions.site_of(tab.url) or tab.session, path)
        p = browser_shot.free(first)
    except browser_shot.ShotError as e:
        return ToolResult(f"没截成：{e}", failed="没截成")
    q = f"/screen?format={fmt}&full={'true' if full_page else 'false'}"
    if fmt == "jpeg":
        q += f"&quality={browser_shot.JPEG_QUALITY}"
    try:
        r = await browser_client.call(tab.session, "GET", q)
    except browser_client.BrowserDown as e:
        return _down(tab, e)
    if r.status_code == 404:
        return ToolResult("这个会话的浏览器已经关了（空闲太久会自动关），先用 browser_open 重新打开。")
    if r.status_code >= 400:
        raise RuntimeError(f"截图失败（{r.status_code}）")
    owner = file_seen.owner_of(ctx.conversation_id, ctx.task_id)
    try:
        shot = await asyncio.to_thread(browser_shot.save, ctx.workspace, p, r.content, fmt, full_page,
                                       r.headers.get("x-shot-cut") == "1", ctx.changes, owner, first)
    except browser_shot.ShotError as e:
        return ToolResult(f"没截成：{e}", failed="没截成")
    blocks, note = [], ""
    if show:
        try:
            blocks.append((await asyncio.to_thread(deliver.deliver, ctx.workspace, shot.rel)).block)
        except deliver.DeliverError as e:
            show, note = False, f"\n没交付：{e}"
    res = await _after(ctx, tab, browser_shot.for_model(shot, show) + note)
    return ToolResult(res.content, blocks + res.blocks, change=file_edit.change(shot.rel, None, ""), detail=browser_shot.detail(shot))


async def _login_form(ctx: ToolContext, args: dict) -> dict | None:
    """保险箱里有这个网站的登录就直接代填，不打扰用户；没有就在聊天里弹登录卡。"""
    tab = _tab(ctx)
    host = tab.host
    if not tab.session or not host:
        return None
    secret = await vault.find_for_url(ctx.db, tab.url, kind="login")
    if secret and secret.id != tab.vault_failed:
        return None
    stale = secret is not None  # v2.51：保险箱那条刚代填没登上 → 问用户新的，预填原用户名
    return {"type": "form", "purpose": "login", "title": "保险箱里的密码没登上，请填新的" if stale else "登录以继续",
            "site": host, "action": "登录", "remember": bool(settings.vault_key),
            "fields": [{"name": "username", "label": "账号", "kind": "text", "value": (secret.username or None) if stale else None},
                       {"name": "password", "label": "密码", "kind": "password"}]}


@tool("browser_login", "正在登录",
      "登录当前网页。user_ref/pass_ref 是快照里用户名框和密码框的编号。保险箱里有这个网站的登录就直接代填；"
      "没有（或保险箱那条刚自动代填没登上）就会在聊天里给用户弹登录卡，用户填完自动代填、勾记住就存进/更新保险箱（你始终看不到账号密码），不用你另外询问。",
      {"type": "object", "properties": {"user_ref": {"type": "string"}, "pass_ref": {"type": "string"}},
       "required": ["user_ref", "pass_ref"]}, form=_login_form)
async def browser_login(ctx: ToolContext, user_ref: str, pass_ref: str, form: FormReply | None = None) -> ToolResult:
    tab = _tab(ctx)
    if not tab.session or not tab.host:
        return ToolResult(NOT_OPEN)
    note = ""
    if form is not None:
        username, password = form.values.get("username", "").strip(), form.values.get("password", "")
        if not username or not password:
            return ToolResult("用户没有把账号和密码填完整，登录没做。")
        if form.remember:
            try:
                old = await vault.find_for_url(ctx.db, tab.url, kind="login")
                if old is not None:  # 保险箱那条密码过期了：原地更新，不再建一条
                    vault.replace_login(old, username, password)
                    tab.vault_failed = ""
                else:
                    ctx.db.add(vault.create(tab.host, password, [tab.host], kind="login", username=username))
                retried = await task_wall.retry_fixed(ctx.db, "needs_login", hosts=[tab.host])
                await ctx.db.commit()
                note = "已按用户的选择记到保险箱，下次自动登录。" + (f"{task_wall.retry_note(retried)}。" if retried else "")
            except Exception:  # 没配 VAULT_KEY 等：登录照常，只是记不住
                await ctx.db.rollback()
                note = "没能记到保险箱（服务器没配好保险箱）。"
        source = "用户在登录卡上填的账号"
    else:
        secret = await vault.find_for_url(ctx.db, tab.url, kind="login")
        if not secret:
            return ToolResult("没有可用的登录信息。用 browser_handoff 请用户在实时画面里自己登录。", [_card(tab)])
        username, password, source = secret.username or "", vault.reveal(secret), f"保险箱「{secret.name}」"
    try:
        snap = await browser_client.snapshot_call(tab.session, "POST", "/login", {
            "user_ref": user_ref, "pass_ref": pass_ref, "username": username, "password": password})
    except browser_client.BrowserDown as e:
        return _down(tab, e)
    tab.autofilled = True  # 刚亲手代填过：还停在登录页也别再用同一份密码自动代填一遍
    return await _after(ctx, tab, f"已用{source}代填登录（你看不到密码）。登录状态存在会话 {tab.session}，"
                        f"以后打开这个网站会接着用。{note}\n" + await _view(ctx, tab, snap, auth=True))


async def _code_form(ctx: ToolContext, args: dict) -> dict | None:
    tab = _tab(ctx)
    if not tab.session or not tab.host:
        return None
    return {"type": "form", "purpose": "code", "title": (args.get("label") or "输入验证码")[:40], "site": tab.host,
            "action": "填入", "fields": [{"name": "code", "label": "验证码", "kind": "code"}]}


@tool("browser_code", "正在填验证码",
      "网站要短信/邮箱/两步验证码时用：在聊天里给用户弹验证码卡，用户填完自动填进编号为 ref 的输入框"
      "（submit=true 随后按回车）。label 写清是哪种码，如“短信验证码（发到尾号 1234）”。图形验证码、滑块、扫码不能用它，用 browser_handoff。",
      {"type": "object", "properties": {"ref": {"type": "string"}, "label": {"type": "string"},
                                        "submit": {"type": "boolean", "default": True}},
       "required": ["ref"]}, form=_code_form)
async def browser_code(ctx: ToolContext, ref: str, label: str = "", submit: bool = True,
                       form: FormReply | None = None) -> ToolResult:
    code = (form.values.get("code", "") if form else "").strip()
    tab = _tab(ctx)
    if not tab.session or not tab.host:
        return ToolResult(NOT_OPEN)
    if not code:
        return ToolResult("用户没有填验证码，没填进去。")
    try:
        snap = await browser_client.snapshot_call(tab.session, "POST", "/act",
                                                  {"action": "type", "ref": ref, "text": code, "submit": submit})
    except browser_client.BrowserDown as e:
        return _down(tab, e)
    return await _after(ctx, tab, "已把用户填的验证码填进去。\n" + await _view(ctx, tab, snap, auth=True))


def handoff_reason(reason: str) -> str:
    """接管条上的那句话：压成一行、截到 REASON_MAX；空 → 通用说法。"""
    text = " ".join((reason or "").split())
    return (text[:REASON_MAX - 1] + "…") if len(text) > REASON_MAX else (text or "需要你在画面里操作一下")


@tool("browser_handoff", "正在等你接管",
      "遇到你过不去、只有用户能做的一步时用：图形验证码、滑块、人机验证、扫码登录、要在手机上点批准、"
      "保险箱里没有登录且不适合弹登录卡。会在当前会话的实时画面卡上请用户接管，用户在画面里弄完点“交还”你就接着做，"
      "结果里带交还后的新快照。reason 用一句话告诉用户要做什么，如“拖动滑块完成验证”“用淘宝 App 扫码登录”。"
      "短信/邮箱验证码用 browser_code，账号密码用 browser_login，不要用它。",
      {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}, deferred=True)
async def browser_handoff(ctx: ToolContext, reason: str) -> ToolResult:
    tab = _tab(ctx)
    if not tab.session:
        return ToolResult(NOT_OPEN)
    if ctx.ask is nobody:  # 定时任务：没人在看，不挂一张等不到人的条
        return ToolResult("现在是定时任务在跑，用户不在，没法接管。如实说明卡在哪一步；需要他之后处理就用 offer_on_home。",
                          failed="用户不在，没法接管")
    hid, why = uuid.uuid4().hex, handoff_reason(reason)
    card = _card(tab)
    ctx.live({**card, "handoff": {"id": hid, "reason": why, "state": "pending"}})
    started = time.monotonic()
    reply = await ctx.ask(hid, {"type": "handoff", "id": hid, "reason": why, "fields": []})
    if reply is None:
        expired = time.monotonic() - started >= approvals.TIMEOUT_SECONDS - 1
        state = "expired" if expired else "cancelled"
        why_not = "等了 10 分钟没人交还" if expired else "用户点了做不了"
        return ToolResult(f"用户没有完成接管（{why_not}）。别再弹接管，告诉用户卡在哪一步、问他想怎么办。",
                          [{**card, "handoff": {"id": hid, "reason": why, "state": state}}], failed=why_not)
    try:
        text = await _view(ctx, tab, await browser_client.snapshot_call(tab.session, "GET", "/snapshot"), auth=True)
    except Exception as e:  # 浏览器在接管期间关了等：交还本身成功，让模型重开
        text = f"（重新读页面失败：{e}；用 browser_open 重新打开）"
    moved = await browser_files.collect(ctx.workspace, tab.session)  # 用户接管时点出来的下载
    final = {**_card(tab, files=moved.files, ws=ctx.workspace), "handoff": {"id": hid, "reason": why, "state": "done"}}
    note = f"{moved.note}\n" if moved.note else ""
    return ToolResult(f"用户完成了接管，把浏览器交还给你了。先看新快照确认那一步过了，再接着做。\n{note}" + text, [final])


@tool("browser_upload", "正在上传文件",
      "把工作区里的文件放进网页的文件框（简历、图片、表格…）。ref = 快照里的文件框（input:file，常是隐藏的，名字可能叫“选择文件”）"
      "或点了会弹出选文件的“上传”按钮；paths = 工作区相对路径，最多 5 个、共 20 MB，目录先打包成 zip。"
      "只是放进框里，之后照常点提交/上传按钮。网页下载的文件会自动存进工作区 downloads/，不用这个。",
      {"type": "object", "properties": {"ref": {"type": "string"},
                                        "paths": {"type": "array", "items": {"type": "string"}}},
       "required": ["ref", "paths"]}, deferred=True)
async def browser_upload(ctx: ToolContext, ref: str, paths: list[str]) -> ToolResult:
    tab = _tab(ctx)
    if not tab.session:
        return ToolResult(NOT_OPEN)
    try:
        snap, moved = await browser_files.upload(ctx.workspace, tab.session, ref, paths)
    except browser_files.BrowserFileError as e:
        return ToolResult(str(e), failed=str(e))
    r = await _after(ctx, tab, f"{moved.note}\n" + await _view(ctx, tab, snap))
    card = _card(tab, files=browser_files.card_files(moved.files, (r.blocks[0].get("files") if r.blocks else None)),
                 ws=ctx.workspace)
    return ToolResult(r.content, [card])
