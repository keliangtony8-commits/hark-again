"""凭证解析：给一个 URL，找出该附加的认证头。
优先 OAuth 连接（按服务声明的 api_hosts），其次保险箱里的 API Key（按用户填的域名）。
返回 scrub 列表，调用方用它把响应里回显的密钥抹掉。
连接失效时 access_token 抛 oauth.ReconnectNeeded（已在主页提醒用户），调用方把它的说明交给模型。"""
from dataclasses import dataclass, field
from urllib.parse import quote, urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import vault
from .connectors.oauth import access_token
from .connectors.providers import PROVIDERS
from .models import Connection


@dataclass
class Resolved:
    headers: dict[str, str] = field(default_factory=dict)
    source: str | None = None          # 给模型看的来源名，如 “GitHub 连接”
    scrub: list[str] = field(default_factory=list)
    connection: Connection | None = None  # 用的是哪个 OAuth 连接（对方回 401 → 判它失效）
    params: dict[str, str] = field(default_factory=dict)  # v2.52 Key 放网址参数的服务（api_keys.Scheme.query_param）


async def resolve(db: AsyncSession, url: str) -> Resolved:
    host = urlparse(url).hostname or ""
    for conn in (await db.scalars(select(Connection))).all():
        p = PROVIDERS.get(conn.provider)
        if p and vault.host_matches(host, p.api_hosts):
            tok = await access_token(db, conn)
            return Resolved({"Authorization": f"Bearer {tok}"}, f"{p.name} 连接（{conn.account}）", [tok], conn)
    if secret := await vault.find_for_url(db, url):
        value = vault.reveal(secret)
        if secret.query_param:
            return Resolved({}, f"保险箱「{secret.name}」", [value, quote(value, safe="")], params={secret.query_param: value})
        return Resolved({secret.header_name: f"{secret.header_prefix}{value}"}, f"保险箱「{secret.name}」", [value])
    return Resolved()


def scrub(text: str, values: list[str]) -> str:
    for v in values:
        if v:
            text = text.replace(v, "••••")
    return text
