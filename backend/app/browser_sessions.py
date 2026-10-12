"""云浏览器会话的唯一规则（v1.26）：会话按站点命名、每段对话记住“当前会话”、列出 / 退出登录。

- 起名 name_for(url)：按站点（主域名）起名，同一站点的所有任务共用一个会话 → 登录一次，下次接着用；
  taobao.com、www.taobao.com、login.taobao.com 都是 taobao-com；bbc.co.uk 这类二级后缀取三段。
- 模型也可以显式给会话名（继续之前那个会话、或同站点开第二个账号），clean() 规整成合法名字。
- 当前会话：每段对话（定时任务按任务）一份 Tab 状态：会话名 + 最后的网址 + 快照里元素编号对应的名字
  （点击风险判断用）。只在本进程内存里（单用户单进程）；进程重启后模型再 browser_open 一次即可。
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


@dataclass
class Tab:
    """一段对话（或一次定时任务）此刻在用的浏览器会话。"""
    session: str = ""
    url: str = ""
    names: dict[str, str] = field(default_factory=dict)  # 快照元素 ref → 名字

    @property
    def host(self) -> str:
        return urlparse(self.url).hostname or ""


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


def forget_tabs(session: str) -> None:
    """会话被退出登录后，正在用它的对话下次要先重新打开。"""
    for t in _tabs.values():
        if t.session == session:
            t.session, t.url = "", ""
            t.names.clear()


def _when(ts) -> str | None:
    return iso(datetime.fromtimestamp(ts, timezone.utc)) if isinstance(ts, (int, float)) else None


async def listing() -> dict:
    """给客户端的会话列表：{sessions: [{name, label, open, saved, last_used, cookies, domains}], max_open}。
    浏览器服务连不上 → RuntimeError（路由回 503）。"""
    data = await browser_client.sessions()
    out = []
    for s in data.get("sessions", []):
        domains = [str(d) for d in s.get("domains", [])][:5]
        out.append({"name": s["name"], "label": label(s["name"], domains), "open": bool(s.get("open")),
                    "saved": bool(s.get("saved")), "last_used": _when(s.get("last_used")),
                    "cookies": int(s.get("cookies") or 0), "domains": domains})
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
