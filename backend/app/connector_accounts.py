"""v2.36 BRAIN (bb)：助手看得见、也能帮你接上自己的账户——“连接器在助手眼里是什么样”的唯一规则。

对标 Hark 公开的 connector_accounts（list：连接器与连接状态；create：发起连接；disconnect：只在用户明确要求时断开）。
以前用户说“帮我连上 Gmail”，助手只能口头叫他去“我的 → 连接器”；系统提示也只列已连上的，模型不知道还能连什么、
哪个已经失效。现在：
- status(provider) 只有四种：connected（连着能用）/ expired（连着但授权失效，要重新连接——oauth.expired 放过提醒）/
  available（服务器配好了 OAuth 应用、还没连）/ unconfigured（服务器没配应用，只有部署的人能在 .env 里加，助手如实说）。
- MCP 服务器跟着列出（problem 规则在 connectors/mcp.py，这里只照抄）。
- connect 产出 ConnectBlock：聊天里一张“连接 X”卡，用户点了才去服务商授权页（授权必须本人来，助手从不经手 token）。
  本轮不等结果：连上后客户端卡片自己变“已连接”，碰壁的任务由 task_wall.retry_fixed 自动重跑（v2.19，已有）。
- 断开只走 oauth.forget，并且必须经审批卡（工具 risk）：Hark 写的是“只在用户明确要求时断开”，我们让用户再点一次批准。
文案、状态判定都在这里；工具（agent/builtin/connectors.py）只做参数分派。"""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import system_alerts
from .connectors import mcp
from .connectors.providers import PROVIDERS, Provider
from .models import Connection, McpServer

CONNECTED, EXPIRED, AVAILABLE, UNCONFIGURED = "connected", "expired", "available", "unconfigured"
LABEL = {CONNECTED: "已连接", EXPIRED: "授权失效，要重新连接", AVAILABLE: "可以连接", UNCONFIGURED: "服务器没配这个应用"}
REASON_MAX = 80


@dataclass
class Account:
    provider: Provider
    status: str
    account: str = ""


def _key(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def find(name: str) -> Provider | None:
    """按 id / 显示名 / 别称找服务商（大小写、空格、符号不计）。真实 E2E：模型会传“Google Calendar”“google_calendar”，
    所以 id 是前缀也算（googlecalendar → google）；对上不止一个就不猜，返回 None。"""
    k = _key(name or "")
    if not k:
        return None
    exact = [p for p in PROVIDERS.values() if k in (_key(p.id), _key(p.name), *map(_key, p.aliases))]
    if exact:
        return exact[0]
    prefix = [p for p in PROVIDERS.values() if k.startswith(_key(p.id))]
    return prefix[0] if len(prefix) == 1 else None


async def accounts(db: AsyncSession) -> list[Account]:
    conns = {c.provider: c for c in (await db.scalars(select(Connection))).all()}
    out = []
    for p in PROVIDERS.values():
        c = conns.get(p.id)
        if c is None:
            out.append(Account(p, AVAILABLE if p.configured else UNCONFIGURED))
        else:
            dead = await system_alerts.active(db, f"connector:{p.id}")
            out.append(Account(p, EXPIRED if dead else CONNECTED, c.account))
    return out


async def one(db: AsyncSession, p: Provider) -> Account:
    return next(a for a in await accounts(db) if a.provider.id == p.id)


async def listing(db: AsyncSession) -> str:
    """给模型看的一览：按状态分组（真实 E2E：一行一个“｜”分隔的列表，模型把“可以连接”读成了“已连”），再列 MCP 服务器。"""
    groups: dict[str, list[str]] = {CONNECTED: [], EXPIRED: [], AVAILABLE: [], UNCONFIGURED: []}
    for a in await accounts(db):
        who = f"，账户 {a.account}" if a.account else ""
        groups[a.status].append(f"{a.provider.name}（id {a.provider.id}：{a.provider.desc}{who}）")
    head = {CONNECTED: "已连接（能直接用）", EXPIRED: "连过但授权失效（要用户重新连接，发连接卡）",
            AVAILABLE: "还没连、可以连（发连接卡）", UNCONFIGURED: "服务器没配应用（现在连不了）"}
    lines = [f"{head[k]}：{'、'.join(v) if v else '无'}" for k, v in groups.items() if v or k == CONNECTED]
    servers = (await db.scalars(select(McpServer).order_by(McpServer.created_at))).all()
    if servers:
        parts = []
        for s in servers:
            pr = await mcp.problem(db, s)
            parts.append(f"{s.name}（{'令牌被拒' if pr == 'auth' else '连不上' if pr == 'down' else '正常'}）")
        lines.append("MCP 服务器：" + "、".join(parts))
    lines.append("MCP 服务器和别的 API Key 只能用户自己在「我的 → 连接器 / 保险箱」里加。")
    return "\n".join(lines)


async def missing_hint(db: AsyncSession, url: str) -> str:
    """api_request 没带上任何凭证、而域名属于某个服务商时追加的一句（真实 E2E：模型调日历接口拿到 403，
    只叫用户“自己去连”，不发卡）。不属于任何服务商 → ""。"""
    from urllib.parse import urlsplit
    host = (urlsplit(url).hostname or "").lower()
    p = next((p for p in PROVIDERS.values() if host in p.api_hosts), None)
    if p is None:
        return ""
    a = await one(db, p)
    if a.status in (AVAILABLE, EXPIRED):
        return (f"\n（这是 {p.name} 的接口，但用户的 {p.name} {'授权失效了' if a.status == EXPIRED else '还没连接'}："
                f"调 connector_accounts action=connect provider={p.id} 给用户一张连接卡，别只叫他自己去设置里找。）")
    if a.status == UNCONFIGURED:
        return f"\n（这是 {p.name} 的接口，服务器没配 {p.name} 应用；{refuse_connect(a)}）"
    return ""


def prompt(connected: list[str]) -> str | None:
    """系统提示里一行：服务器配好了、还没连的账户（按 id 排序，逐字稳定才命中提示缓存）。都连了 / 都没配 → None。"""
    can = sorted(p.id for p in PROVIDERS.values() if p.configured and p.id not in connected)
    if not can:
        return None
    names = "、".join(f"{PROVIDERS[i].name}（id {i}：{PROVIDERS[i].desc}）" for i in can)
    # 真实 E2E：只写 action=connect 时模型照抄、漏了 provider，所以参数写全
    return (f"还没连接、但可以连：{names}。任务要用到时调 connector_accounts（action=connect, provider=<id>, reason=一句话）"
            "给用户一张连接卡。")


def refuse_connect(a: Account) -> str | None:
    """不能发连接卡的原因（给模型）；None = 可以发。已连接照样可以发（用户想换号 / 重新授权）。"""
    if a.status == UNCONFIGURED:
        return (f"服务器还没配置 {a.provider.name} 的 OAuth 应用（.env 里的 {a.provider.id.upper()}_CLIENT_ID / "
                f"{a.provider.id.upper()}_CLIENT_SECRET），只有部署的人能加，别发连接卡。"
                f"替代办法只说一次：用户可以在「我的 → 保险箱」为 {'、'.join(a.provider.api_hosts)} 存一个 API Key / 个人访问令牌，"
                "之后 api_request 自动带上；没存之前别去试调接口。")
    return None


def card(a: Account, reason: str = "") -> dict:
    from .blocks import ConnectBlock  # blocks 不依赖这里
    reason = (reason or "").strip()[:REASON_MAX]
    return ConnectBlock(provider=a.provider.id, name=a.provider.name, desc=a.provider.desc, logo=a.provider.logo,
                        reason=reason or None, account=a.account or None,
                        reconnect=a.status in (CONNECTED, EXPIRED)).model_dump()


def connect_text(a: Account) -> str:
    if a.status == CONNECTED:
        head = f"{a.provider.name} 已经连着（{a.account}）；卡片可以用来换号或重新授权。"
    elif a.status == EXPIRED:
        head = f"{a.provider.name}（{a.account}）的授权失效了，卡片会带用户重新连接。"
    else:
        head = f"已经给用户一张「连接 {a.provider.name}」卡。"
    return (head + "授权要用户本人点卡片去服务商页面完成，这一轮拿不到结果：告诉用户点卡片，"
            "连好之后再请他让你接着做；别在文字里贴链接、别让用户把密码发给你。")


def disconnect_reason(p: Provider) -> str:
    """审批卡标题（审批在执行前、同步算，不查库，所以不带账户名）。"""
    return f"断开 {p.name} 账户：之后我不能再代你读写它"
