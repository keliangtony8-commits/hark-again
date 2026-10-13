"""v2.20 命令借用已连接账户（对标 Hark shell 的 credentials=[{"provider": ...}]）：唯一规则在这里。

一条 run_command（前台 / 后台 / 常驻）声明 credentials=["github"] 之后，这条命令的环境里才有该连接的 Token，
外加让常用命令行直接认它的配置：
- GitHub：$GH_TOKEN、$GITHUB_TOKEN（gh、大多数 SDK 认这两个）+ git 访问 https://github.com/ 免密
  （GIT_CONFIG_* 注入一个凭证助手，助手里只引用 $GH_TOKEN，值不进任何配置文件、不落盘）；
- Google：$GOOGLE_OAUTH_ACCESS_TOKEN、$CLOUDSDK_AUTH_ACCESS_TOKEN（gcloud 认后者）；
- 以后新增的服务商：$<ID>_TOKEN。
没声明的命令一律拿不到（不像 command_env 那样每条都给）：Token 权限大，按需借。

参考：三家（deepseek-harness / Codex / Gemini CLI）都跑在用户本机、用用户自己的 gh / gcloud 登录，没有“把云端连接借给
沙盒里一条命令”这层；Codex exec_env.rs 的“运行时注入的变量最后写、覆盖继承值”照用（借来的覆盖同名用户变量）。

边界（不夸大）：Hark 是在线路上按域名注入、Token 不进环境；我们的沙盒没有出网代理（要 VPS 上的网络策略），
所以退一步放进这条命令的环境，靠 command_env.scrub 在一切输出里抹成 [$GH_TOKEN]；防的是不小心打印，不是对抗模型。
每次启动现取（Google 一小时过期：常驻任务重启时拿新的）。"""
import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import command_env, vault
from .connectors import oauth
from .connectors.providers import PROVIDERS
from .models import Connection

MAX = 4  # 一条命令最多借几个
ENV_EXTRA_MAX = MAX * 2 + 6  # 最多多出几个变量（每个服务两个名字 + GitHub 的 git 配置 6 个）；sandbox/runner.py ENV_MAX = 30 + 这个
# 服务商 → 放哪些变量（第一个是打码时显示的名字）
ENV_NAMES = {"github": ("GH_TOKEN", "GITHUB_TOKEN"), "google": ("GOOGLE_OAUTH_ACCESS_TOKEN", "CLOUDSDK_AUTH_ACCESS_TOKEN")}
# git 走 https 时的凭证助手：只引用变量，值不出现在配置里；先给空值清掉用户 / 系统配的其它助手（git 的列表重置写法）
GIT_HOSTS = {"github": ("https://github.com", "x-access-token", "GH_TOKEN")}


def env_names(provider: str) -> tuple[str, ...]:
    return ENV_NAMES.get(provider) or (f"{provider.upper().replace('-', '_')}_TOKEN",)


def parse(raw) -> list[str]:
    """模型给的 credentials → 去重后的服务商 id 列表。接受 "github"、{"provider": "github"}（Hark 的写法）。
    不认识的服务商 / 太多 / 形状不对抛 ValueError（一句能照做的话）。"""
    if raw in (None, "", []):
        return []
    items = raw if isinstance(raw, list) else [raw]
    out: list[str] = []
    for it in items:
        pid = it.get("provider") if isinstance(it, dict) else it
        pid = str(pid or "").strip().lower()
        if pid not in PROVIDERS:
            known = "、".join(PROVIDERS)
            raise ValueError(f"credentials 里的「{pid or it}」不是可连接的服务（可用：{known}）")
        if pid not in out:
            out.append(pid)
    if len(out) > MAX:
        raise ValueError(f"一条命令最多借 {MAX} 个账户")
    return out


@dataclass
class Grant:
    env: dict[str, str] = field(default_factory=dict)
    labels: list[str] = field(default_factory=list)   # 借到的：“GitHub（octocat）”
    missing: list[str] = field(default_factory=list)  # 借不到的原因，每条一句


def _git(provider: str, env: dict[str, str]) -> None:
    if provider not in GIT_HOSTS:
        return
    url, user, var = GIT_HOSTS[provider]
    n = int(env.get("GIT_CONFIG_COUNT", "0"))
    pairs = [(f"credential.{url}.helper", ""),
             (f"credential.{url}.helper", f"!f() {{ echo username={user}; echo \"password=${var}\"; }}; f")]
    for k, v in pairs:
        env[f"GIT_CONFIG_KEY_{n}"], env[f"GIT_CONFIG_VALUE_{n}"] = k, v
        n += 1
    env["GIT_CONFIG_COUNT"] = str(n)
    env["GIT_TERMINAL_PROMPT"] = "0"  # 万一认证失败直接报错，不在沙盒里卡着等输入


async def grant(db: AsyncSession, providers: list[str]) -> Grant:
    """现取 Token（快过期就续）→ 这条命令要加的环境变量。没连 / 连接失效的进 missing（不抛：命令照跑，模型据此告诉用户）。
    借到的值立刻登记进打码表（command_env.remember），这个进程里任何输出都抹掉。"""
    g = Grant()
    if not providers:
        return g
    rows = {c.provider: c for c in (await db.scalars(select(Connection))).all()}
    for pid in providers:
        p = PROVIDERS[pid]
        conn = rows.get(pid)
        if conn is None:
            g.missing.append(f"还没连接 {p.name}：请用户在“连接器”页连上，连好后再跑")
            continue
        try:
            tok = await oauth.access_token(db, conn)
        except oauth.ReconnectNeeded as e:
            g.missing.append(str(e))
            continue
        names = env_names(pid)
        for n in names:
            g.env[n] = tok
        command_env.remember(names[0], tok)
        _git(pid, g.env)
        g.labels.append(f"{p.name}（{conn.account}）" if conn.account else p.name)
    return g


async def known(db: AsyncSession) -> dict[str, str]:
    """全部连接当前存着的 access token（只解密、不续期）→ {打码名: 值}：command_env.load 并进打码表，
    别的进程（worker 读后台任务日志）也能把借出去的 Token 抹掉。解不开的跳过。"""
    out: dict[str, str] = {}
    for c in (await db.scalars(select(Connection))).all():
        try:
            tok = json.loads(vault.decrypt(c.ciphertext)).get("access_token")
        except Exception:  # noqa: BLE001 — VAULT_KEY 换了：当不存在
            continue
        if tok:
            out[env_names(c.provider)[0]] = tok
    return out


def note(g: Grant) -> str:
    """给模型的一句（成功 + 失败都说）。"""
    parts = []
    if g.labels:
        vars_ = "、".join(f"${n}" for n in g.env if not n.startswith("GIT_"))
        git = "；git 访问 github.com 已免密" if "GIT_CONFIG_COUNT" in g.env else ""
        parts.append(f"已用 {'、'.join(g.labels)}认证（{vars_}{git}；值在输出里会显示成 [$变量名]）")
    if g.missing:
        parts.append("没借到：" + "；".join(g.missing))
    return "（" + "。".join(parts) + "）" if parts else ""


def labels(providers: list[str]) -> list[str]:
    """卡片上显示的服务名（不含账户；任务卡只说“用 GitHub 账户”）。"""
    return [PROVIDERS[p].name for p in providers if p in PROVIDERS]


def prompt(providers: list[str]) -> str:
    """系统提示里一句（稳定段）：已连接的服务可以借给命令。"""
    if not providers:
        return ""
    names = "、".join(f"{PROVIDERS[p].name}（\"{p}\"）" for p in providers if p in PROVIDERS)
    return (f"沙盒命令可以借用已连接账户：run_command 加 credentials=[\"github\"] 之类（可借：{names}），"
            "这条命令里就有对应 Token（GitHub：$GH_TOKEN，git 推拉 github.com 免密），别的命令拿不到；"
            "别把 Token 打印或写进文件。")
