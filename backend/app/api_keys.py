"""v2.52 BRAIN (bf)：把用户自己的 API Key 接到一个服务上——唯一的规则（助手的 connect_api_key 工具和保险箱接口共用）。

对标 Hark 公开的 request_secret + connect_service：用户在卡上亲手填 Key → 绑到这个服务的域名 → 先用它真调一次确认能用
→ 之后 api_request 发往这些域名时在线路上自动带上，模型和聊天记录里永远没有 Key。三个参照（deepseek-harness / Codex /
Gemini CLI）都跑在用户本机、靠用户自己 export 环境变量，没有“按域名托管密钥”这层 → 自写。

规则：
- 域名：1–HOSTS_MAX 个，去协议 / 路径、小写；要带点（"com"、"localhost" 这类不收）；
  助手要接的域名属于已有连接器（GitHub、Google…）不收——那些走 connector_accounts 的 OAuth 连接（用户自己在保险箱存 PAT 照收）。
- 怎么带上 Key（scheme）：默认请求头 Authorization: Bearer <Key>；header_name / header_prefix 换成服务文档写的
  （x-api-key、空前缀…）；query_param 给了 = 改放网址参数（OpenWeather ?appid=、高德 ?key=），请求头就不用。
  Cookie / Host / Content-* 这类头不许拿来放 Key。
- 同一服务再接一次（域名有重叠）= 原地换 Key 和带法，不另建一条（Key 过期 / 换号最常见）。
- verify_url（可选，强烈建议）：必须 https 且在这些域名里；带上 Key 真 GET 一次：
  2xx/3xx → 验证通过；401/403 → Key 被拒，什么都不存（ConnectError kind="rejected"）；
  其它状态 / 连不上 → 照样保存，但结果写明“没能验证”（verified=None），不夸大。
- 保存后卡在“需要连接这个服务”的定时任务立即重跑一次（task_wall.retry_fixed needs_connector，名字 = 服务名 / 域名）。
- 沙盒里的命令（curl、脚本）拿不到这把 Key（出网代理不解 https，不能在线路上注入）：要在命令里用就是 request_env。"""
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import task_wall, vault, web_guard
from .connectors.providers import PROVIDERS
from .models import Secret

HOSTS_MAX = 4
NAME_MAX = 60
VALUE_MIN = 4
VERIFY_TIMEOUT = 15
_HEADER = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_PARAM = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
_BAD_HEADERS = {"cookie", "host", "content-length", "content-type", "transfer-encoding", "connection",
                "proxy-authorization"}
_KINDS = ("hosts", "scheme", "name", "value", "oauth", "verify_url", "rejected")


class ConnectError(ValueError):
    """没接成（原因是给人看的中文）。kind ∈ _KINDS；kind="oauth" 时 provider = 该走的连接器 id。"""
    def __init__(self, kind: str, text: str, provider: str | None = None):
        super().__init__(text)
        self.kind = kind
        self.provider = provider


@dataclass
class Scheme:
    header_name: str = "Authorization"
    header_prefix: str = "Bearer "
    query_param: str | None = None


@dataclass
class Connected:
    secret: Secret
    replaced: bool
    verified: bool | None        # True 验证通过；None 没能验证（没给地址 / 对方回了别的 / 连不上）
    verify_note: str = ""        # verified 不是 True 时的原因
    retried: str | None = None   # task_wall.retry_note


def check_hosts(hosts, by: str = "agent") -> list[str]:
    raw = hosts if isinstance(hosts, list) else re.split(r"[\s,，]+", str(hosts or ""))
    out: list[str] = []
    for h in raw:
        n = vault.normalize_host(str(h)).rstrip(".")
        if not n:
            continue
        if "." not in n or n.startswith(("*", ".")) or n.endswith(".localhost"):
            raise ConnectError("hosts", f"「{str(h)[:60]}」不像一个服务的域名（要像 api.openweathermap.org 这样）。")
        if n not in out:
            out.append(n)
    if not out:
        raise ConnectError("hosts", "要给这个服务的 API 域名（如 api.openweathermap.org）。")
    if len(out) > HOSTS_MAX:
        raise ConnectError("hosts", f"一个服务最多绑 {HOSTS_MAX} 个域名。")
    for p in PROVIDERS.values() if by == "agent" else ():  # 用户自己在保险箱存 GitHub PAT 照收
        if any(vault.host_matches(n, p.api_hosts) for n in out):
            raise ConnectError("oauth", f"这是 {p.name} 的接口，要用 {p.name} 连接（connector_accounts provider={p.id}），"
                                        "不用 API Key。", p.id)
    return out


def check_scheme(header_name: str = "", header_prefix: str | None = None, query_param: str = "") -> Scheme:
    q = (query_param or "").strip()
    if q:
        if not _PARAM.match(q):
            raise ConnectError("scheme", "query_param 只能是字母、数字、_ . -（如 appid、key、api_key）。")
        return Scheme("", "", q)
    h = (header_name or "").strip() or "Authorization"
    if not _HEADER.match(h) or h.lower() in _BAD_HEADERS:
        raise ConnectError("scheme", f"请求头「{h[:40]}」不能用来放 Key（常见是 Authorization、X-API-Key）。")
    p = "Bearer " if header_prefix is None else header_prefix
    if len(p) > 32 or any(c in p for c in "\r\n"):
        raise ConnectError("scheme", "header_prefix 太长或带换行（常见是 \"Bearer \"、\"Token \" 或空）。")
    return Scheme(h, p, None)


def clean_name(name: str, hosts: list[str]) -> str:
    n = " ".join((name or "").split())
    if len(n) > NAME_MAX:
        raise ConnectError("name", f"名字太长（最多 {NAME_MAX} 个字）。")
    return n or hosts[0]


def check_verify_url(url: str, hosts: list[str]) -> str | None:
    u = (url or "").strip()
    if not u:
        return None
    host = (urlsplit(u).hostname or "").lower()
    if not u.startswith("https://") or not vault.host_matches(host, hosts):
        raise ConnectError("verify_url", f"verify_url 要是 https 地址，而且在 {'、'.join(hosts)} 里。")
    return u


def where(s: Secret) -> str:
    """这把 Key 怎么带上（给模型 / 列表看，不含值）。"""
    if s.query_param:
        return f"网址参数 ?{s.query_param}="
    return f"请求头 {s.header_name}: {s.header_prefix}…"


async def existing(db: AsyncSession, hosts: list[str]) -> Secret | None:
    """域名有重叠（相等或互为子域）的那条 API Key。"""
    for s in (await db.scalars(select(Secret).where(Secret.kind == "api_key").order_by(Secret.created_at))).all():
        if any(vault.host_matches(a, [b]) or vault.host_matches(b, [a]) for a in hosts for b in s.hosts or []):
            return s
    return None


async def verify(url: str, value: str, scheme: Scheme) -> tuple[bool | None, str]:
    """带上 Key 真 GET 一次。返回 (True 通过 / False 被拒 / None 没能确认, 原因)。原因里从不带 Key。"""
    headers, params = {}, {}
    if scheme.query_param:
        params[scheme.query_param] = value
    else:
        headers[scheme.header_name] = f"{scheme.header_prefix}{value}"
    try:
        async with web_guard.client(timeout=VERIFY_TIMEOUT, follow_redirects=False) as c:
            r = await c.get(url, headers=headers, params=params)
    except web_guard.Blocked as e:
        return None, str(e)
    except Exception as e:  # noqa: BLE001 —— 网络错误只影响“验证没做成”
        return None, f"无法连接验证地址（{type(e).__name__}）"
    if r.status_code in (401, 403):
        return False, f"对方回了 HTTP {r.status_code}"
    if r.status_code < 400:
        return True, ""
    return None, f"验证地址回了 HTTP {r.status_code}，不确定 Key 对不对"


async def connect(db: AsyncSession, name: str, value: str, hosts, *, header_name: str = "",
                  header_prefix: str | None = None, query_param: str = "", verify_url: str = "",
                  by: str = "agent") -> Connected:
    """检查 → （可选）真调一次 → 新建或原地换 → 重跑卡在它上的任务，并提交。Key 被拒抛 ConnectError，什么都不存。"""
    hs = check_hosts(hosts, by)
    scheme = check_scheme(header_name, header_prefix, query_param)
    n = clean_name(name, hs)
    url = check_verify_url(verify_url, hs)
    value = (value or "").strip()
    if len(value) < VALUE_MIN or any(c in value for c in "\r\n"):
        raise ConnectError("value", f"Key 至少 {VALUE_MIN} 个字符，不能带换行。")
    verified, note = (None, "没给验证地址，还没真调过") if url is None else await verify(url, value, scheme)
    if verified is False:
        raise ConnectError("rejected", f"这个 Key 被 {hs[0]} 拒绝了（{note}），没有保存。")
    old = await existing(db, hs)
    if old is not None:
        old.name, old.hosts, old.ciphertext, old.preview = n, hs, vault.encrypt(value), value[-4:]
        old.header_name, old.header_prefix, old.query_param = scheme.header_name, scheme.header_prefix, scheme.query_param
        s = old
    else:
        s = vault.create(n, value, hs, "api_key", header_name=scheme.header_name, header_prefix=scheme.header_prefix,
                         query_param=scheme.query_param)
        db.add(s)
    retried = task_wall.retry_note(await task_wall.retry_fixed(db, "needs_connector", names=[n, *hs]))
    await db.commit()
    return Connected(s, old is not None, verified, "" if verified else note, retried)


def connected_text(c: Connected) -> str:
    s = c.secret
    head = (f"用户已在卡上填好 {s.name} 的 Key（不用再让用户填），已{'替换原来那把' if c.replaced else '加密存进保险箱'}，"
            f"绑定 {'、'.join(s.hosts)}，带法：{where(s)}。")
    check = "已用它真调过一次，验证通过。" if c.verified else f"注意：{c.verify_note}——如实告诉用户“存好了但还没确认能用”。"
    return (head + check + "之后用 api_request 调这些域名会自动带上 Key（别在 url / headers 里自己放 Key）；"
            "沙盒命令里的 curl 拿不到它。" + (f"{c.retried}。" if c.retried else ""))


def rejected_hint(source: str | None, other_hint: str) -> str:
    """api_request 收到 401/403、用的不是 OAuth 连接时追加的一句。已经有连接器提示（other_hint）就不再说。"""
    if other_hint:
        return ""
    if source:  # 保险箱里的 Key 被拒
        return (f"\n（{source} 被对方拒绝：Key 可能过期或带法不对。先对照服务文档确认带法；Key 本身失效就调 connect_api_key "
                "让用户在卡上换一把新的，绝不让用户把 Key 发在聊天里。）")
    return ("\n（这个接口要认证，而保险箱里没有它的 Key：服务要用户自己的 API Key 就调 connect_api_key 弹卡让用户填"
            "（写清去哪儿申请），绝不让用户把 Key 发在聊天里。）")
