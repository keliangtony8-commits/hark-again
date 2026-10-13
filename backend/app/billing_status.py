"""“花了多少 / 还剩多少”说给助手听的唯一规则（v2.39 BRAIN bc，对标 Hark 公开的 billing_status：
查账户的套餐、额度和当前用量）。我们没有套餐，“额度”就是用户自己设的：每月预算（只提醒不拦截）+ 工作区磁盘上限。

数从哪来：全用 usage.report / day_report / conversation_report（用量页同一份数，助手说的 = 页面上看到的），
磁盘用 quota.state（“我的电脑”页同一份缓存）。这里只把它们写成给模型看的几行中文，不另查库、不另算钱。

三个范围：
  overview      今天、昨天、本月至今、和上月同期比、预算（百分比 + 照这速度的月底估计）、本月花钱最多的模型 / 对话、
                自动选模型省了多少、没定价的模型（只记 token → 实际花费被低估，要明说）、这个工作区的磁盘
  conversation  这段对话从头到现在
  day           某一天（用户时区的本地日期 YYYY-MM-DD）
金额统一 usage.money()；百分比、估计都只在这里算。
"""
import asyncio
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from . import quota, usage
from .config import settings
from .model_router import label_of

SCOPES = ("overview", "conversation", "day")
TOP_MODELS = 3
TOP_CONVERSATIONS = 3


def _tokens(n: int) -> str:
    """12345 → 1.2 万；整数 token 说给人听。"""
    return f"{n / 10000:.1f}".removesuffix(".0") + " 万" if n >= 10000 else str(n)


def _amount(block: dict) -> str:
    """一段汇总的“花费 + 调用数 + token”。"""
    return f"{usage.money(block['cost'])}（{block['calls']} 次调用，{_tokens(block['tokens'])} token）"


def _models(block: dict, limit: int = TOP_MODELS) -> str | None:
    ms = [m for m in block.get("models", []) if m["calls"]][:limit]
    if not ms:
        return None
    priced = set(settings.model_prices)
    def one(m):
        if m["model"] in priced:
            return f"{label_of(m['model'])} {usage.money(m['cost'])}"
        return f"{label_of(m['model'])} 未定价（{_tokens(m['prompt_tokens'] + m['completion_tokens'])} token）"
    return "；".join(one(m) for m in ms)


def unpriced(block: dict) -> list[str]:
    """用过但没定价的模型（只记了 token 不算钱）：花费会被低估，必须告诉用户。"""
    priced = set(settings.model_prices)
    return [label_of(m["model"]) for m in block.get("models", []) if m["calls"] and m["model"] not in priced]


def _unpriced_line(block: dict) -> str | None:
    if names := unpriced(block):
        return (f"注意：{'、'.join(names)} 没设单价，只记了 token 没算钱——上面的金额比实际少，"
                "跟用户说清楚（单价在服务器配置 MODEL_PRICES 里设）。")
    return None


def _compare(month: dict, last: dict) -> str:
    before = last["to_date"]["cost"]
    if not before:
        return f"上月同期没有花费（上月全月 {usage.money(last['cost'])}）。"
    pct = round((month["cost"] - before) / before * 100)
    trend = f"多 {pct}%" if pct > 0 else f"少 {-pct}%" if pct < 0 else "持平"
    return f"比上月同期（{usage.money(before)}）{trend}；上月全月 {usage.money(last['cost'])}。"


def _budget(cost: float, now: datetime) -> str:
    budget = settings.monthly_budget
    if budget <= 0:
        return "预算：没设每月预算（服务器配置 MONTHLY_BUDGET；设了也只提醒、不拦截调用）。"
    left = budget - cost
    pct = round(cost / budget * 100)
    head = f"预算：每月 {usage.money(budget)}，已用 {pct}%，" + (
        f"还剩 {usage.money(left)}" if left >= 0 else f"已超出 {usage.money(-left)}")
    return f"{head}；照这个速度月底约 {usage.money(usage.month_projection(cost, now))}。只提醒、不拦截调用。"


def _conversations(rows: list[dict], current: str | None) -> str | None:
    rows = rows[:TOP_CONVERSATIONS]
    if not rows:
        return None
    def name(r):
        t = "这段对话" if r["id"] == current else f"「{r['title']}」" if r["title"] else "一段已删除的对话"
        return f"{t} {usage.money(r['cost'])}"
    return "；".join(name(r) for r in rows)


def _router(r: dict | None) -> str | None:
    if not r:
        return None
    line = f"自动选模型：本月 {r['turns']} 轮，{r['simple']} 轮走了 {r['simple_model']}"
    if r["net"] is not None:
        line += f"，比全用 {r['complex_model']} 约省 {usage.money(max(r['net'], 0))}（含分类器 {usage.money(r['classifier']['cost'])}）"
    return line + "。"


def _disk(ws: str) -> str:
    q = quota.state(ws)
    if not q.limit:
        return f"这个工作区磁盘：已用 {quota.size_text(q.used)}，不限上限。"
    pct = round(q.used / q.limit * 100)
    tail = {"full": "，满了：写文件、开后台任务都会被拒绝", "tight": "，快满了"}.get(q.level, "")
    return f"这个工作区磁盘：已用 {quota.size_text(q.used)} / 上限 {quota.size_text(q.limit)}（{pct}%{tail}）。"


def _join(lines) -> str:
    return "\n".join(x for x in lines if x)


async def overview(db: AsyncSession, ws: str, conversation_id: str | None = None,
                   now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    r = await usage.report(db, now=now)
    month = r["month"]
    local = now.astimezone(ZoneInfo(settings.timezone))
    yday = (await usage.day_report(db, local.date() - timedelta(days=1)))["total"]
    top_models = _models(month)
    top_convs = _conversations(r["conversations"], conversation_id)
    return _join([
        f"模型花费（{settings.currency}，按服务器配置的单价估算；用户时区 {local:%Y-%m-%d %H:%M}）",
        f"今天：{_amount(r['today'])}",
        f"昨天（{local.date() - timedelta(days=1):%m-%d}）：{_amount(yday)}",
        f"本月至今（{local.month} 月 1 日起）：{_amount(month)}。{_compare(month, r['last_month'])}",
        _budget(month["cost"], now),
        top_models and f"本月花得最多的模型：{top_models}",
        top_convs and f"本月花得最多的对话：{top_convs}",
        _router(r["router"]),
        _unpriced_line(month),
        await _disk_async(ws),
        "更早某一天：scope=day + date。细账（逐日图）在用量页；用户问到就告诉他在「我」页 → 查看用量。",
    ])


async def _disk_async(ws: str) -> str:
    # 数磁盘碰文件系统（有缓存），放线程里免得卡事件循环
    return await asyncio.to_thread(_disk, ws)


async def conversation(db: AsyncSession, conversation_id: str | None) -> str:
    if not conversation_id:
        return "这一轮不在某段对话里（后台运行），没有“这段对话”的用量；用 scope=overview 看总账。"
    total = (await usage.conversation_report(db, conversation_id))["total"]
    if not total["calls"]:
        return "这段对话还没有记到模型调用。"
    return _join([
        f"这段对话从开始到现在：{_amount(total)}（含滚动摘要、记忆向量等后台调用）",
        (m := _models(total)) and f"按模型：{m}",
        _unpriced_line(total),
    ])


def parse_day(text: str, now: datetime | None = None) -> date:
    """YYYY-MM-DD 或 today / 今天；别的说法（昨天、上周一）让模型先用 resolve_relative_date 算成日期。"""
    s = (text or "").strip().lower()
    if s in ("", "today", "今天"):
        return (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(settings.timezone)).date()
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise ValueError(f"date 要写成 YYYY-MM-DD（收到「{text[:20]}」）；“昨天”这类说法先用 resolve_relative_date 算出日期") from None


async def day(db: AsyncSession, d: date, conversation_id: str | None = None) -> str:
    r = await usage.day_report(db, d)
    total = r["total"]
    if not total["calls"]:
        return f"{d.isoformat()}（用户时区）没有模型调用，花费 {usage.money(0)}。"
    return _join([
        f"{d.isoformat()}（用户时区）：{_amount(total)}",
        (m := _models(total)) and f"按模型：{m}",
        (c := _conversations(r["conversations"], conversation_id)) and f"花得最多的对话：{c}",
        _unpriced_line(total),
    ])
