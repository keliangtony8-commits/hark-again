"""云浏览器会话的唯一规则（v1.26）：会话按站点命名、每段对话记住“当前会话”、列出 / 退出登录。

- 起名 name_for(url)：按站点（主域名）起名，同一站点的所有任务共用一个会话 → 登录一次，下次接着用；
  taobao.com、www.taobao.com、login.taobao.com 都是 taobao-com；bbc.co.uk 这类二级后缀取三段。
- 模型也可以显式给会话名（继续之前那个会话、或同站点开第二个账号），clean() 规整成合法名字。
- 当前会话：每段对话（定时任务按任务）一份 Tab 状态：会话名 + 最后的网址 + 快照里元素编号对应的名字
  （点击风险判断用）。只在本进程内存里（单用户单进程）；进程重启后模型再 browser_open 一次即可。
- 登录过期（v1.36）：login_page(snap) 认登录页（可见的密码框 / 登录类网址 / “请重新登录”类字样）；
  observe(tab, snap, auth) 是唯一判定：之前登录过（服务端标记 signed_in）的会话又出现登录页 → "expired"
  （服务端记 expired，“我的电脑”显示登录已过期；每次打开只提醒模型一次）；在这个 tab 里见过登录页、随后一次
  登录类动作（browser_login / browser_code / 接管交还，auth=True）之后不再是登录页 → "signed_in"（清掉过期）。
  只看 auth 动作：用户点“返回”离开登录页不算登录成功。
- 自动重登（v2.50）：login_fields(snap) 是“这张登录页能不能不问模型直接代填”的唯一判定：恰好一个密码框，
  它前面最近的一个文本类输入框（text/email/tel/无类型）当用户名框 → (user_ref, pass_ref)；否则 None
  （只有用户名的两步登录、没有表单只有“请重新登录”字样、多个密码框的注册/改密页都不自动填）。
- 旧版本只有一个会话 "main"，它的登录存档照常列出（标成“早先的浏览器会话”），可以退出。
"""
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

from . import browser_client
from .wire_time import iso

LEGACY = "main"
NAME_MAX = 40
# 常见“二级后缀”：这些后面跟的才是站点名（bbc.co.uk → bbc-co-uk，不是 co-uk）
_SECOND_LEVEL = {"com", "net", "org", "gov", "edu", "ac", "co", "or", "ne", "go"}


def site_of(url: str) -> str:
    """网址 → 站点主域名（taobao.com）；不是 http(s) 网址 → ""。"""
    u = urlparse(url if "://" in url else f"https://{url}")
    host = (u.hostname or "").lower().strip(".")
    if not host:
        return ""
    if re.fullmatch(r"[\d.]+|\[?[0-9a-f:]+\]?", host):  # IP 地址：整串就是站点
        return host
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    n = 3 if parts[-2] in _SECOND_LEVEL and len(parts[-1]) == 2 else 2
    return ".".join(parts[-n:])


def clean(name: str) -> str:
    """任意字符串 → 合法会话名（字母数字 _ -，≤40）；空 → ""。"""
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", name.strip().lower()).strip("-")
    return s[:NAME_MAX].strip("-")


def name_for(url: str) -> str:
    return clean(site_of(url).replace(".", "-")) or "web"


def label(name: str, domains: list[str] | None = None) -> str:
    """给人看的会话名：旧的 main → 早先的浏览器会话；按站点起名的 → 还原成域名（taobao-com → taobao.com）。"""
    if name == LEGACY:
        return "早先的浏览器会话"
    if domains:
        guess = name.replace("-", ".")
        for d in domains:
            if d == guess or d.endswith("." + guess):
                return guess
    return name.replace("-", ".") if re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)+", name) else name


# 登录页的网址：路径里的 login/signin/passport/sso…，或 login./passport./sso./accounts./auth. 开头的主机
LOGIN_URL = re.compile(r"(^|[/._-])(log-?in|sign-?in|sign_in|signon|passport|sso|auth|oauth|account/login|user/login)"
                       r"([/._?#-]|$)", re.I)
LOGIN_HOST = re.compile(r"^(login|signin|passport|sso|accounts?|auth|id|uc|cas)\.", re.I)
# 页面开头的“登录过期”字样（只看前 EXPIRED_SCAN 字，正文里讨论“登录”的文章不算）
EXPIRED_TEXT = re.compile(r"登录(已|状态)?(过期|失效|超时)|请(先|重新)登录|会话(已)?(过期|失效)|"
                          r"session (has )?(expired|timed out)|please (log|sign) ?in( again)?|you have been (logged|signed) out",
                          re.I)
EXPIRED_SCAN = 600


def login_page(snap: dict) -> bool:
    """快照像登录页吗：可见的密码框，或登录类网址，或页面开头写着要重新登录。"""
    if any(e.get("tag") == "input" and e.get("type") == "password" for e in snap.get("elements", [])):
        return True
    u = urlparse(snap.get("url") or "")
    if u.hostname and LOGIN_HOST.match(u.hostname):
        return True
    if LOGIN_URL.search(u.path or ""):
        return True
    return bool(EXPIRED_TEXT.search((snap.get("text") or "")[:EXPIRED_SCAN]))


USER_TYPES = {"", "text", "email", "tel"}


def login_fields(snap: dict) -> tuple[str, str] | None:
    """登录页上可以直接代填的 (用户名框编号, 密码框编号)；判不准 → None（交给模型看着办）。"""
    els = [e for e in snap.get("elements", []) if e.get("tag") == "input"]
    pw = [i for i, e in enumerate(els) if e.get("type") == "password"]
    if len(pw) != 1:
        return None
    user = [e for e in els[:pw[0]] if (e.get("type") or "") in USER_TYPES]
    if not user:
        return None
    return str(user[-1]["ref"]), str(els[pw[0]]["ref"])


@dataclass
class Tab:
    """一段对话（或一次定时任务）此刻在用的浏览器会话。"""
    session: str = ""
    url: str = ""
    names: dict[str, str] = field(default_factory=dict)  # 快照元素 ref → 名字
    frames: dict[str, str] = field(default_factory=dict)  # 快照里在跨站内嵌框里的元素 ref → 框的域名（v2.59，browser/frames.py）
    signed_in: bool = False   # 这个会话登录过（服务端标记）
    expired: bool = False     # 已判定过期（服务端标记过）
    login_seen: bool = False  # 这次打开后见过登录页（之后的 auth 动作成功 → signed_in）
    noted: bool = False       # 这次打开已经提醒过模型“登录过期”
    autofilled: bool = False  # 这次打开已经用保险箱自动代填过（v2.50，每次打开最多一次）
    vault_failed: str = ""    # 自动代填后仍停在登录页的保险箱条目 id（v2.51；这段对话里一直记着，browser_login 改弹登录卡问新密码）

    def opened(self, login: dict | None) -> None:
        """browser_open 之后：按服务端的登录标记重置这次打开的状态。"""
        login = login or {}
        self.signed_in, self.expired = bool(login.get("signed_in")), bool(login.get("expired"))
        self.login_seen = self.noted = self.autofilled = False

    @property
    def host(self) -> str:
        return urlparse(self.url).hostname or ""

    def login_url(self, pass_ref: str | None) -> str:
        """这个密码框属于哪个网站（v2.59）——保险箱查 / 存登录、登录卡写的站点只认它：密码框在别的网站嵌进来的
        框里（第三方登录框、支付页里的账户框）→ 那个框的域名，绝不把主页面网站的密码填进别人家的框；否则主页面。"""
        host = self.frames.get(str(pass_ref or ""))
        return f"https://{host}/" if host else self.url

    def login_host(self, pass_ref: str | None) -> str:
        return urlparse(self.login_url(pass_ref)).hostname or ""


_tabs: dict[str, Tab] = {}
_TABS_MAX = 200


def _key(conversation_id: str | None, task_id: str | None) -> str:
    return f"c:{conversation_id}" if conversation_id else f"t:{task_id or '-'}"


def tab(conversation_id: str | None, task_id: str | None = None) -> Tab:
    k = _key(conversation_id, task_id)
    if k not in _tabs:
        if len(_tabs) >= _TABS_MAX:  # 只是防无限增长：丢最早的
            _tabs.pop(next(iter(_tabs)))
        _tabs[k] = Tab()
    return _tabs[k]


async def _mark(session: str, state: str) -> None:
    try:
        await browser_client.login_state(session, state)
    except RuntimeError:  # 标记只是给“我的电脑”看的，记不上不影响任务
        pass


async def observe(tab: Tab, snap: dict, auth: bool = False) -> str | None:
    """每张快照之后调一次 → "expired"（该提醒模型重登）/ "signed_in"（刚登录成功）/ None。"""
    if login_page(snap):
        tab.login_seen = True
        if (tab.signed_in or tab.expired) and not tab.noted:
            tab.noted = True
            if not tab.expired:
                tab.expired = True
                await _mark(tab.session, "expired")
            return "expired"
        return None
    if auth and tab.login_seen:
        tab.signed_in, tab.expired, tab.login_seen, tab.noted = True, False, False, False
        await _mark(tab.session, "signed_in")
        return "signed_in"
    return None


def alert_subject(session: str) -> str:
    return f"browser:{session}"


def forget_tabs(session: str) -> None:
    """会话被退出登录后，正在用它的对话下次要先重新打开。"""
    for t in _tabs.values():
        if t.session == session:
            t.session, t.url = "", ""
            t.names.clear()
            t.opened(None)


def _when(ts) -> str | None:
    return iso(datetime.fromtimestamp(ts, timezone.utc)) if isinstance(ts, (int, float)) else None


async def listing() -> dict:
    """给客户端的会话列表：{sessions: [{name, label, open, saved, last_used, cookies, domains, signed_in_at, expired_at}], max_open}。
    浏览器服务连不上 → RuntimeError（路由回 503）。"""
    data = await browser_client.sessions()
    out = []
    for s in data.get("sessions", []):
        domains = [str(d) for d in s.get("domains", [])][:5]
        out.append({"name": s["name"], "label": label(s["name"], domains), "open": bool(s.get("open")),
                    "saved": bool(s.get("saved")), "last_used": _when(s.get("last_used")),
                    "cookies": int(s.get("cookies") or 0), "domains": domains,
                    "signed_in_at": _when(s.get("signed_in")), "expired_at": _when(s.get("expired"))})
    return {"sessions": out, "max_open": int(data.get("max_open") or 1)}


async def sign_out(name: str) -> None:
    """退出登录 = 关掉会话 + 删掉登录存档。名字不合法 → ValueError；服务连不上 → RuntimeError。"""
    if clean(name) != name or not name:
        raise ValueError("会话名不对")
    await browser_client.close(name, forget=True)
    forget_tabs(name)


async def saved_names() -> list[str]:
    """存过登录的会话名（给模型提示“这些站点已经登录过”）；服务连不上 → []。"""
    try:
        data = await browser_client.sessions()
    except RuntimeError:
        return []
    return [s["name"] for s in data.get("sessions", []) if s.get("saved")]
