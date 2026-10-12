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
自动搬进工作区 downloads/（_after），模型被告知路径；搬过的文件记在画面卡的 files 上（用户点了能打开）。"""
import re
import time
import uuid

from ... import browser_client, browser_files, browser_sessions, vault
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
    return (f"页面：{snap.get('title', '')}\n{snap.get('url', '')}\n\n可操作元素：\n" + "\n".join(lines)
            + f"\n\n页面文字：\n{snap.get('text', '')}")


def _card(tab: Tab, live: bool = False, files: list[dict] | None = None, ws: str | None = None) -> dict:
    block = {"type": "browser", "session": tab.session, "site": browser_sessions.site_of(tab.url) or None}
    if live:
        block["live"] = True
    if files:
        block["files"], block["workspace"] = files, ws
    return {k: v for k, v in block.items() if v is not None}


async def _after(ctx: ToolContext, tab: Tab, text: str, card: bool = False) -> ToolResult:
    """每个浏览器动作之后：把页面触发的下载搬进工作区。有搬到的 → 告诉模型并在画面卡上记一笔。"""
    moved = await browser_files.collect(ctx.workspace, tab.session)
    if moved.note:
        text = f"{moved.note}\n{text}"
    blocks = [_card(tab, files=moved.files, ws=ctx.workspace)] if (card or moved.files) else []
    return ToolResult(text, blocks)


async def _act(ctx: ToolContext, method: str, path: str, json: dict | None = None) -> ToolResult:
    r = await _snap(ctx, method, path, json)
    return ToolResult(r) if isinstance(r, str) else await _after(ctx, r[1], r[0])


async def _snap(ctx: ToolContext, method: str, path: str, json: dict | None = None) -> tuple[str, Tab] | str:
    """对当前会话发一个返回快照的请求 → (给模型的文字, tab)；还没打开 → 提示字符串。"""
    tab = _tab(ctx)
    if not tab.session:
        return NOT_OPEN
    return _render(await browser_client.snapshot_call(tab.session, method, path, json), tab), tab


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
    tab = _tab(ctx)
    name = browser_sessions.clean(session) or browser_sessions.name_for(url)
    switched = tab.session if tab.session and tab.session != name else ""
    tab.session, tab.url = name, url if "://" in url else f"https://{url}"
    tab.names.clear()
    ctx.live(_card(tab, live=True))  # 打开要几秒到几十秒：先让用户看到画面卡
    snap = await browser_client.snapshot_call(name, "POST", "/goto", {"url": url})
    text = _render(snap, tab)
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


@tool("browser_read", "正在查看页面", "重新读取当前页面（例如用户在实时画面里操作完之后）。",
      {"type": "object", "properties": {}})
async def browser_read(ctx: ToolContext) -> ToolResult:
    return await _act(ctx, "GET", "/snapshot")


@tool("browser_look", "正在看页面",
      "截一张云浏览器当前画面给你看。快照文字说不清时再用（图表、图片内容、布局、按钮在哪、页面是否正常显示），"
      "比快照费 token，别每步都截。",
      {"type": "object", "properties": {}})
async def browser_look(ctx: ToolContext) -> ToolResult:
    tab = _tab(ctx)
    if not tab.session:
        return ToolResult(NOT_OPEN)
    r = await browser_client.call(tab.session, "GET", "/screen")
    if r.status_code == 404:
        return ToolResult("这个会话的浏览器已经关了（空闲太久会自动关），先用 browser_open 重新打开。")
    if r.status_code >= 400:
        raise RuntimeError(f"截图失败（{r.status_code}）")
    return ToolResult("当前页面截图：", [_card(tab)], images=[ToolImage("页面截图.jpg", r.content)])


async def _login_form(ctx: ToolContext, args: dict) -> dict | None:
    """保险箱里有这个网站的登录就直接代填，不打扰用户；没有就在聊天里弹登录卡。"""
    tab = _tab(ctx)
    host = tab.host
    if not tab.session or not host or await vault.find_for_url(ctx.db, tab.url, kind="login"):
        return None
    return {"type": "form", "purpose": "login", "title": "登录以继续", "site": host, "action": "登录",
            "remember": bool(settings.vault_key),
            "fields": [{"name": "username", "label": "账号", "kind": "text"},
                       {"name": "password", "label": "密码", "kind": "password"}]}


@tool("browser_login", "正在登录",
      "登录当前网页。user_ref/pass_ref 是快照里用户名框和密码框的编号。保险箱里有这个网站的登录就直接代填；"
      "没有就会在聊天里给用户弹登录卡，用户填完自动代填（你始终看不到账号密码），不用你另外询问。",
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
                ctx.db.add(vault.create(tab.host, password, [tab.host], kind="login", username=username))
                await ctx.db.commit()
                note = "已按用户的选择记到保险箱，下次自动登录。"
            except Exception:  # 没配 VAULT_KEY 等：登录照常，只是记不住
                await ctx.db.rollback()
                note = "没能记到保险箱（服务器没配好保险箱）。"
        source = "用户在登录卡上填的账号"
    else:
        secret = await vault.find_for_url(ctx.db, tab.url, kind="login")
        if not secret:
            return ToolResult("没有可用的登录信息。用 browser_handoff 请用户在实时画面里自己登录。", [_card(tab)])
        username, password, source = secret.username or "", vault.reveal(secret), f"保险箱「{secret.name}」"
    snap = await browser_client.snapshot_call(tab.session, "POST", "/login", {
        "user_ref": user_ref, "pass_ref": pass_ref, "username": username, "password": password})
    return await _after(ctx, tab, f"已用{source}代填登录（你看不到密码）。登录状态存在会话 {tab.session}，"
                        f"以后打开这个网站会接着用。{note}\n" + _render(snap, tab))


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
    snap = await browser_client.snapshot_call(tab.session, "POST", "/act",
                                              {"action": "type", "ref": ref, "text": code, "submit": submit})
    return await _after(ctx, tab, "已把用户填的验证码填进去。\n" + _render(snap, tab))


def handoff_reason(reason: str) -> str:
    """接管条上的那句话：压成一行、截到 REASON_MAX；空 → 通用说法。"""
    text = " ".join((reason or "").split())
    return (text[:REASON_MAX - 1] + "…") if len(text) > REASON_MAX else (text or "需要你在画面里操作一下")


@tool("browser_handoff", "正在等你接管",
      "遇到你过不去、只有用户能做的一步时用：图形验证码、滑块、人机验证、扫码登录、要在手机上点批准、"
      "保险箱里没有登录且不适合弹登录卡。会在当前会话的实时画面卡上请用户接管，用户在画面里弄完点“交还”你就接着做，"
      "结果里带交还后的新快照。reason 用一句话告诉用户要做什么，如“拖动滑块完成验证”“用淘宝 App 扫码登录”。"
      "短信/邮箱验证码用 browser_code，账号密码用 browser_login，不要用它。",
      {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]})
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
        text = _render(await browser_client.snapshot_call(tab.session, "GET", "/snapshot"), tab)
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
       "required": ["ref", "paths"]})
async def browser_upload(ctx: ToolContext, ref: str, paths: list[str]) -> ToolResult:
    tab = _tab(ctx)
    if not tab.session:
        return ToolResult(NOT_OPEN)
    try:
        snap, moved = await browser_files.upload(ctx.workspace, tab.session, ref, paths)
    except browser_files.BrowserFileError as e:
        return ToolResult(str(e), failed=str(e))
    r = await _after(ctx, tab, f"{moved.note}\n" + _render(snap, tab))
    card = _card(tab, files=browser_files.card_files(moved.files, (r.blocks[0].get("files") if r.blocks else None)),
                 ws=ctx.workspace)
    return ToolResult(r.content, [card])
