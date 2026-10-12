"""服务器主机模式——开关、已存的前缀规则、这段对话里的批准，全在这里（唯一入口）。

- 没装 host agent（settings.host_agent_socket 为空）→ installed() False：工具不出现、开关打不开。
- 装了也默认关：用户在“我的电脑”里打开才给模型 host_command（run_turn 每轮读一次 enabled() 填进 ToolContext.host）。
- 审批卡三个选项（Codex ReviewDecision / Gemini ProceedAlways·ProceedAlwaysAndSave）：
    once    仅这一次（Approved）
    session 这段对话里这条都允许（ApprovedForSession，进程内，重启就忘）
    rule    以后都允许以 X 开头的命令（ApprovedExecpolicyAmendment，存 host_rules，定时任务也认）
"""
from collections import OrderedDict
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import host_policy
from .config import settings
from .models import AppSetting, HostRule
from .wire_time import iso

KEY = "host_mode"
GRANT_ONCE, GRANT_SESSION, GRANT_RULE = "once", "session", "rule"
GRANTS = (GRANT_ONCE, GRANT_SESSION, GRANT_RULE)
RULES_MAX = 100
OWNERS_MAX = 200     # 记住“这段对话都允许”的对话数
KEYS_MAX = 200       # 每段对话最多记几条
_granted: "OrderedDict[str, set[tuple[str, ...]]]" = OrderedDict()


PROMPT = ("服务器主机模式已打开：host_command 在这台 VPS 本机以 root 运行命令——装系统软件（apt）、管服务（systemctl）、"
          "看系统日志（journalctl）、改 nginx 等系统配置、看整机磁盘内存。每条都会弹卡等用户批准（他点过“都允许”的除外），"
          "所以先想清楚、一次跑对，reason 用一句话说明为什么；能在沙盒里做的（写代码、跑项目、pip/npm 装包）仍用 run_command。"
          "不要停掉 Docker 或助手自己的服务；交互式命令会读到 EOF，要加 -y 之类的参数。")


class HostModeError(Exception):
    pass


def installed() -> bool:
    return bool(settings.host_agent_socket)


async def enabled(db: AsyncSession) -> bool:
    if not installed():
        return False
    row = await db.get(AppSetting, KEY)
    return bool(row and row.value.get("enabled"))


async def set_enabled(db: AsyncSession, on: bool) -> None:
    if on and not installed():
        raise HostModeError("服务器上还没装主机代理：在 VPS 上运行 sudo bash deploy/install.sh --host-agent 再来打开。")
    row = await db.get(AppSetting, KEY)
    if row is None:
        db.add(AppSetting(key=KEY, value={"enabled": on}))
    else:
        row.value = {**row.value, "enabled": on}
    if not on:
        _granted.clear()  # 关掉就把这次会话里的批准都忘掉；存下的规则保留（再打开还在，可以单独删）
    await db.commit()


# ---------- 规则 ----------
async def rules(db: AsyncSession) -> list[HostRule]:
    return list((await db.execute(select(HostRule).order_by(HostRule.created_at.desc()))).scalars())


async def prefixes(db: AsyncSession) -> list[list[str]]:
    return [list(r.prefix) for r in await rules(db)]


async def add_rule(db: AsyncSession, prefix: tuple[str, ...]) -> HostRule:
    existing = await rules(db)
    for r in existing:
        if tuple(r.prefix) == tuple(prefix):
            return r
    if len(existing) >= RULES_MAX:
        raise HostModeError(f"已存了 {RULES_MAX} 条规则，先在“我的电脑”里删掉一些不用的。")
    row = HostRule(prefix=list(prefix))
    db.add(row)
    await db.commit()
    return row


async def remove_rule(db: AsyncSession, rid: str) -> bool:
    r = await db.execute(delete(HostRule).where(HostRule.id == rid))
    await db.commit()
    return bool(r.rowcount)


async def used(db: AsyncSession, cmds: list[list[str]] | None) -> None:
    """规则放行了一条命令：记一次（“我的电脑”里能看出哪条规则一直在用、哪条可以删）。"""
    if not cmds:
        return
    now = datetime.now(timezone.utc)
    for r in await rules(db):
        if any(host_policy.matches(r.prefix, c) for c in cmds):
            r.uses = (r.uses or 0) + 1
            r.last_used_at = now
    await db.commit()


def rule_wire(r: HostRule) -> dict:
    return {"id": r.id, "prefix": list(r.prefix), "text": host_policy.describe_rule(r.prefix), "uses": r.uses or 0,
            "created_at": iso(r.created_at), "last_used_at": iso(r.last_used_at) if r.last_used_at else None}


# ---------- 这段对话里的批准 ----------
def owner_of(conversation_id: str | None) -> str | None:
    return f"c:{conversation_id}" if conversation_id else None


def granted(owner: str | None) -> set[tuple[str, ...]]:
    return set(_granted.get(owner, ())) if owner else set()


def grant_session(owner: str | None, key: tuple[str, ...]) -> None:
    if not owner or not key:
        return
    keys = _granted.pop(owner, set())
    if len(keys) < KEYS_MAX:
        keys.add(key)
    _granted[owner] = keys
    while len(_granted) > OWNERS_MAX:
        _granted.popitem(last=False)


async def requirement(db: AsyncSession, command: str, conversation_id: str | None, unattended: bool,
                      proposed: list[str] | None = None) -> host_policy.Requirement:
    return host_policy.evaluate(command, await prefixes(db), granted(owner_of(conversation_id)), unattended, proposed)


def options(req: host_policy.Requirement) -> list[dict]:
    """审批卡上的选项（第一个是默认的“批准”按钮）。"""
    out = [{"id": GRANT_ONCE, "label": "仅这一次"}]
    if req.session:
        out.append({"id": GRANT_SESSION, "label": "这段对话里都允许"})
    if req.rule:
        out.append({"id": GRANT_RULE, "label": f"以后都允许 {host_policy.describe_rule(req.rule)} 开头的命令"})
    return out


def granted_text(grant: str, req: host_policy.Requirement) -> str:
    if grant == GRANT_SESSION:
        return "这段对话里这条命令都允许了"
    if grant == GRANT_RULE and req.rule:
        return f"以后 {host_policy.describe_rule(req.rule)} 开头的命令都允许了"
    return ""


async def remember(db: AsyncSession, grant: str | None, req: host_policy.Requirement, conversation_id: str | None) -> str:
    """用户在卡上选了范围：记下来，返回一句给模型/卡片的话。"""
    if grant == GRANT_SESSION and req.session:
        grant_session(owner_of(conversation_id), req.key)
    elif grant == GRANT_RULE and req.rule:
        await add_rule(db, req.rule)
    else:
        return ""
    return granted_text(grant, req)


def forget_all() -> None:
    _granted.clear()
