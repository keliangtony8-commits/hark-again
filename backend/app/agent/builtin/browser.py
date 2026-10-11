"""云浏览器工具。模型看到的是“快照”：页面文字 + 编号的可点元素（[12] 按钮 登录）。
用户在聊天里看到实时画面卡，随时可以接管（输入密码、过验证码）。
付款、下单、发送这类按钮要先审批。浏览器很费 token，能用 web_search/web_fetch 解决的不要开浏览器。"""
import re
from urllib.parse import urlparse

from ... import browser_client, vault
from ...config import settings
from ..approvals import FormReply
from ..tools import ToolContext, ToolImage, ToolResult, tool

RISKY_BUTTON = re.compile(r"支付|付款|购买|下单|提交订单|确认订单|发送|发布|删除|pay|buy|purchase|checkout|place order|send|post|delete", re.I)
_last_names: dict[str, str] = {}  # ref -> 元素名，用来判断点击的风险
_last_url = {"url": ""}           # 当前页面地址，代填登录时按它匹配保险箱


def _render(snap: dict) -> str:
    _last_names.clear()
    _last_url["url"] = snap.get("url", "")
    lines = []
    for e in snap.get("elements", []):
        _last_names[e["ref"]] = e["name"]
        kind = e["tag"] + (f":{e['type']}" if e["type"] and e["tag"] == "input" else "")
        lines.append(f"[{e['ref']}] {kind} {e['name']}")
    return (f"页面：{snap.get('title', '')}\n{snap.get('url', '')}\n\n可操作元素：\n" + "\n".join(lines)
            + f"\n\n页面文字：\n{snap.get('text', '')}")


def _live_card() -> dict:
    return {"type": "browser", "session": browser_client.SESSION}


def _click_risk(args: dict) -> str | None:
    name = _last_names.get(str(args.get("ref")), "")
    return f"点击「{name}」（可能付款、发送或删除）" if RISKY_BUTTON.search(name) else None


@tool("browser_open", "正在打开网页",
      "在云浏览器打开网址，返回页面快照。用于需要登录、点击、填表的网站；单纯读资料用 web_fetch。",
      {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]})
async def browser_open(ctx: ToolContext, url: str) -> ToolResult:
    snap = await browser_client.snapshot_call("POST", "/goto", {"url": url})
    return ToolResult(_render(snap), [_live_card()])


@tool("browser_click", "正在点击", "点击快照里编号为 ref 的元素，返回新快照。",
      {"type": "object", "properties": {"ref": {"type": "string"}}, "required": ["ref"]}, risk=_click_risk)
async def browser_click(ctx: ToolContext, ref: str) -> ToolResult:
    return ToolResult(_render(await browser_client.snapshot_call("POST", "/act", {"action": "click", "ref": ref})))


@tool("browser_type", "正在输入", "在编号为 ref 的输入框里填入文字；submit=true 时随后按回车。"
      "不要用它输入密码或验证码：登录用 browser_login，验证码用 browser_code（都会在聊天里问用户）。",
      {"type": "object", "properties": {"ref": {"type": "string"}, "text": {"type": "string"},
                                        "submit": {"type": "boolean", "default": False}},
       "required": ["ref", "text"]})
async def browser_type(ctx: ToolContext, ref: str, text: str, submit: bool = False) -> ToolResult:
    return ToolResult(_render(await browser_client.snapshot_call(
        "POST", "/act", {"action": "type", "ref": ref, "text": text, "submit": submit})))


@tool("browser_scroll", "正在滚动页面", "向下（dy>0）或向上滚动页面，返回新快照。",
      {"type": "object", "properties": {"dy": {"type": "integer", "default": 600}}})
async def browser_scroll(ctx: ToolContext, dy: int = 600) -> ToolResult:
    return ToolResult(_render(await browser_client.snapshot_call("POST", "/act", {"action": "scroll", "dy": dy})))


@tool("browser_read", "正在查看页面", "重新读取当前页面（例如用户在实时画面里操作完之后）。",
      {"type": "object", "properties": {}})
async def browser_read(ctx: ToolContext) -> ToolResult:
    return ToolResult(_render(await browser_client.snapshot_call("GET", "/snapshot")))


@tool("browser_look", "正在看页面",
      "截一张云浏览器当前画面给你看。快照文字说不清时再用（图表、图片内容、布局、按钮在哪、页面是否正常显示），"
      "比快照费 token，别每步都截。",
      {"type": "object", "properties": {}})
async def browser_look(ctx: ToolContext) -> ToolResult:
    r = await browser_client.call("GET", "/screen")
    if r.status_code == 404:
        return ToolResult("浏览器还没打开页面，先用 browser_open。")
    if r.status_code >= 400:
        raise RuntimeError(f"截图失败（{r.status_code}）")
    return ToolResult("当前页面截图：", [_live_card()], images=[ToolImage("页面截图.jpg", r.content)])


def _host() -> str:
    return urlparse(_last_url["url"]).hostname or ""


async def _login_form(ctx: ToolContext, args: dict) -> dict | None:
    """保险箱里有这个网站的登录就直接代填，不打扰用户；没有就在聊天里弹登录卡。"""
    host = _host()
    if not host or await vault.find_for_url(ctx.db, _last_url["url"], kind="login"):
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
    if not _host():
        return ToolResult("浏览器还没打开页面，先用 browser_open 打开登录页。")
    note = ""
    if form is not None:
        username, password = form.values.get("username", "").strip(), form.values.get("password", "")
        if not username or not password:
            return ToolResult("用户没有把账号和密码填完整，登录没做。")
        if form.remember:
            try:
                ctx.db.add(vault.create(_host(), password, [_host()], kind="login", username=username))
                await ctx.db.commit()
                note = "已按用户的选择记到保险箱，下次自动登录。"
            except Exception:  # 没配 VAULT_KEY 等：登录照常，只是记不住
                await ctx.db.rollback()
                note = "没能记到保险箱（服务器没配好保险箱）。"
        source = "用户在登录卡上填的账号"
    else:
        secret = await vault.find_for_url(ctx.db, _last_url["url"], kind="login")
        if not secret:
            return ToolResult("没有可用的登录信息。请用户在实时画面里点“接管”自己登录，完成后用 browser_read 继续。",
                              [_live_card()])
        username, password, source = secret.username or "", vault.reveal(secret), f"保险箱「{secret.name}」"
    snap = await browser_client.snapshot_call("POST", "/login", {
        "user_ref": user_ref, "pass_ref": pass_ref, "username": username, "password": password})
    return ToolResult(f"已用{source}代填登录（你看不到密码）。{note}\n" + _render(snap))


async def _code_form(ctx: ToolContext, args: dict) -> dict | None:
    if not _host():
        return None
    return {"type": "form", "purpose": "code", "title": (args.get("label") or "输入验证码")[:40], "site": _host(),
            "action": "填入", "fields": [{"name": "code", "label": "验证码", "kind": "code"}]}


@tool("browser_code", "正在填验证码",
      "网站要短信/邮箱/两步验证码时用：在聊天里给用户弹验证码卡，用户填完自动填进编号为 ref 的输入框"
      "（submit=true 随后按回车）。label 写清是哪种码，如“短信验证码（发到尾号 1234）”。图形验证码让用户在实时画面里自己点。",
      {"type": "object", "properties": {"ref": {"type": "string"}, "label": {"type": "string"},
                                        "submit": {"type": "boolean", "default": True}},
       "required": ["ref"]}, form=_code_form)
async def browser_code(ctx: ToolContext, ref: str, label: str = "", submit: bool = True,
                       form: FormReply | None = None) -> ToolResult:
    code = (form.values.get("code", "") if form else "").strip()
    if not _host():
        return ToolResult("浏览器还没打开页面，先用 browser_open。")
    if not code:
        return ToolResult("用户没有填验证码，没填进去。")
    snap = await browser_client.snapshot_call("POST", "/act", {"action": "type", "ref": ref, "text": code, "submit": submit})
    return ToolResult("已把用户填的验证码填进去。\n" + _render(snap))
