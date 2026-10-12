"""保险箱：所有敏感值（API Key、网站登录密码、OAuth Token、MCP 令牌）的加解密都在这里。
解密只在发请求的最后一刻发生（credentials.py 调用），结果直接进 HTTP 头，不回到模型、不进日志。"""
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import Secret
from .wire_time import iso

_f = Fernet(settings.vault_key.encode()) if settings.vault_key else None


def _fernet() -> Fernet:
    if not _f:
        raise RuntimeError("服务器没有配置 VAULT_KEY，保险箱不可用")
    return _f


def normalize_host(h: str) -> str:
    h = h.strip().lower()
    return (urlparse(h).hostname or "") if "://" in h else h.split("/")[0]


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def create(name: str, value: str, hosts: list[str], kind: str = "api_key", username: str | None = None,
           header_name: str = "Authorization", header_prefix: str = "Bearer ") -> Secret:
    login = kind == "login"
    return Secret(name=name, kind="login" if login else "api_key", username=username if login else None,
                  hosts=[x for x in (normalize_host(h) for h in hosts) if x],
                  header_name=header_name or "Authorization", header_prefix=header_prefix,
                  ciphertext=encrypt(value), preview="" if login else value[-4:])  # 密码连末位都不露


def host_matches(host: str, allowed: list[str]) -> bool:
    return any(host == a or host.endswith("." + a) for a in allowed)


async def find_for_url(db: AsyncSession, url: str, kind: str = "api_key") -> Secret | None:
    """按网址找对应条目。kind 严格区分：登录密码永远不会被当成 API Key 塞进请求头。"""
    host = urlparse(url).hostname or ""
    for s in (await db.scalars(select(Secret).where(Secret.kind == kind))).all():
        if host_matches(host, s.hosts):
            return s
    return None


def reveal(secret: Secret) -> str:
    return decrypt(secret.ciphertext)


def public(s: Secret) -> dict:
    return {"id": s.id, "kind": s.kind, "name": s.name, "username": s.username, "hosts": s.hosts,
            "header_name": s.header_name,
            "header_prefix": s.header_prefix, "preview": s.preview, "created_at": iso(s.created_at)}
