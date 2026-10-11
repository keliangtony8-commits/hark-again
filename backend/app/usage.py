"""用量与花费：模型调用记账的唯一入口。

写：llm.py 每次调用拿到 usage 后调 record()——自己开一个短会话写一行，和调用方的事务无关
（聊天被取消、工具回滚都不影响记账）；记账失败只吞掉，绝不让聊天因为记账出错。
归属：runner 用 scope(conversation_id) 把当前对话放进 contextvar，深处的 llm 调用（滚动摘要、
记忆向量）自动带上，不用一路传参。worker 也走 run_turn，所以定时任务同样记在它的对话上。
读：report() 按用户时区出“今天 / 本月”的汇总、本月逐日序列（daily，1 号到今天，没用量的天补 0）
和本月最花钱的对话（conversations，前 TOP_CONVERSATIONS 个，带标题；对话已删 title=null），
供 GET /api/usage；conversation_report() 出单个对话的
累计，供 GET /api/conversations/{id}/usage（聊天页顶栏的“本对话用量”）；day_report() 出某一天（用户时区）
的按模型拆分，供 GET /api/usage/days/{date}（用量图上点某天）。三者同一个 _aggregate 形状。
提醒：每记一笔后 check_budget() 看本月花费有没有跨过 MONTHLY_BUDGET 的某一档（BUDGET_ALERTS），
跨过就在 Home 放一张 action 卡（target="usage"，客户端显示“查看用量”）。每月每档每个预算值只发一次，
去重靠 alerts_sent 表（主键冲突 = 发过，并发两笔同时跨档也只有一张）；新的一档会把旧的预算卡收起。
已知缺口：中途停止的那次流式调用拿不到 usage（供应商在最后一个包才给），不记。"""
import calendar
import contextlib
import logging
from contextvars import ContextVar
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .blocks import text_to_blocks
from .config import settings
from .db import SessionLocal
from .models import AlertSent, Conversation, HomeCard, UsageRecord

log = logging.getLogger(__name__)
_conversation: ContextVar[str | None] = ContextVar("usage_conversation", default=None)


@contextlib.contextmanager
def scope(conversation_id: str | None):
    token = _conversation.set(conversation_id)
    try:
        yield
    finally:
        _conversation.reset(token)


def cost_of(model: str, prompt: int, completion: int) -> float:
    p = settings.model_prices.get(model)
    if not p:
        return 0.0
    inp, out = (list(p) + [0.0, 0.0])[:2]
    return (prompt * inp + completion * out) / 1_000_000


async def record(model: str, kind: str, prompt: int, completion: int) -> None:
    if not prompt and not completion:
        return
    try:
        async with SessionLocal() as db:
            db.add(UsageRecord(model=model, kind=kind, conversation_id=_conversation.get(),
                               prompt_tokens=prompt, completion_tokens=completion,
                               cost=cost_of(model, prompt, completion)))
            await db.commit()
    except Exception:  # 记账永远不能打断正事
        log.exception("usage record failed")
        return
    try:
        async with SessionLocal() as db:
            await check_budget(db)
    except Exception:
        log.exception("budget check failed")


def _money(v: float) -> str:
    sign = {"CNY": "¥", "USD": "$", "EUR": "€"}.get(settings.currency)
    return f"{sign}{v:.2f}" if sign else f"{v:.2f} {settings.currency}"


def _budget_card(level: float, cost: float, budget: float, local: datetime) -> HomeCard:
    pct = round(cost / budget * 100)
    if level >= 1:
        title = "本月模型花费已超出预算"
        text = (f"本月已用 **{_money(cost)}**，预算 {_money(budget)}（{pct}%）。\n\n"
                "调用不会被拦截。想省一点，可以把常用对话切回快速模型，或少用浏览器类工具。")
    else:
        days = calendar.monthrange(local.year, local.month)[1]
        elapsed = max((local - local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)).total_seconds() / 86400, 1)
        text = (f"本月已用 **{_money(cost)}**，预算 {_money(budget)}（{pct}%）。\n\n"
                f"照这个速度，月底大约 {_money(cost / elapsed * days)}。")
        title = f"本月模型花费已到预算的 {round(level * 100)}%"
    return HomeCard(kind="action", title=title, blocks=text_to_blocks(text), target="usage", unread=True,
                    action_prompt="看看我这个月的模型花费主要花在哪些模型和对话上，给我三条具体的省钱建议。")


async def check_budget(db: AsyncSession, now: datetime | None = None) -> HomeCard | None:
    """本月花费跨过最高的那一档且还没提醒过 → 放一张卡并返回它；否则返回 None。"""
    budget = settings.monthly_budget
    if budget <= 0 or not settings.budget_alerts:
        return None
    now = now or datetime.now(timezone.utc)
    since = _periods(now)["month"]
    cost = float(await db.scalar(select(func.sum(UsageRecord.cost)).where(UsageRecord.created_at >= since)) or 0)
    level = next((r for r in sorted(settings.budget_alerts, reverse=True) if r > 0 and cost >= budget * r), None)
    if level is None:
        return None
    local = now.astimezone(ZoneInfo(settings.timezone))
    key = f"budget:{local:%Y-%m}:{round(level * 100)}:{budget:g}"  # 改了预算 = 新的一组档位
    if await db.get(AlertSent, key):
        return None
    try:
        db.add(AlertSent(key=key))
        await db.flush()
    except IntegrityError:  # 并发的另一笔已经发了
        await db.rollback()
        return None
    await db.execute(update(HomeCard).where(HomeCard.kind == "action", HomeCard.target == "usage",
                                            HomeCard.dismissed.is_(False)).values(dismissed=True))
    card = _budget_card(level, cost, budget, local)
    db.add(card)
    await db.commit()
    return card


def _periods(now: datetime) -> dict[str, datetime]:
    """今天 / 本月的起点（用户时区的零点），转成 UTC 去比较（库里存的是 UTC）。"""
    local = now.astimezone(ZoneInfo(settings.timezone))
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return {"today": day.astimezone(timezone.utc), "month": day.replace(day=1).astimezone(timezone.utc)}


async def _aggregate(db: AsyncSession, *where) -> dict:
    """按模型汇总一组用量行：报表的“今天/本月”和单个对话共用这一个形状。"""
    rows = (await db.execute(
        select(UsageRecord.model, func.count(), func.sum(UsageRecord.prompt_tokens),
               func.sum(UsageRecord.completion_tokens), func.sum(UsageRecord.cost))
        .where(*where)
        .group_by(UsageRecord.model)
    )).all()
    models = sorted(({"model": m, "calls": n, "prompt_tokens": int(p or 0), "completion_tokens": int(c or 0),
                      "cost": round(float(k or 0), 4)} for m, n, p, c, k in rows),
                    key=lambda r: (-r["cost"], -(r["prompt_tokens"] + r["completion_tokens"])))
    return {"calls": sum(r["calls"] for r in models),
            "tokens": sum(r["prompt_tokens"] + r["completion_tokens"] for r in models),
            "cost": round(sum(r["cost"] for r in models), 4), "models": models}


def _head() -> dict:
    return {"currency": settings.currency, "priced": sorted(settings.model_prices)}


async def _daily(db: AsyncSession, since: datetime, now: datetime) -> list[dict]:
    """本月逐日：[{date: "YYYY-MM-DD", calls, tokens, cost}]，从 1 号到今天（用户时区），空天补 0。
    分桶在 Python 里做：按“本地日期”在 SQL 里 group by 要写两套方言（SQLite / Postgres），
    而一个人一个月的用量行最多几千行，只取三列，代价可以忽略。"""
    tz = ZoneInfo(settings.timezone)
    rows = (await db.execute(
        select(UsageRecord.created_at, UsageRecord.prompt_tokens + UsageRecord.completion_tokens, UsageRecord.cost)
        .where(UsageRecord.created_at >= since)
    )).all()
    first, today = since.astimezone(tz).date(), now.astimezone(tz).date()
    days = {first + timedelta(d): {"calls": 0, "tokens": 0, "cost": 0.0} for d in range((today - first).days + 1)}
    for at, tokens, cost in rows:
        at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)  # SQLite 读回来不带时区，存的是 UTC
        bucket = days.get(at.astimezone(tz).date())
        if bucket is None:  # 时钟比 now 还晚的行（测试或时钟漂移）：不画
            continue
        bucket["calls"] += 1
        bucket["tokens"] += int(tokens or 0)
        bucket["cost"] += float(cost or 0)
    return [{"date": d.isoformat(), **v, "cost": round(v["cost"], 4)} for d, v in days.items()]


TOP_CONVERSATIONS = 5


async def _top_conversations(db: AsyncSession, since: datetime, until: datetime | None = None,
                             limit: int = TOP_CONVERSATIONS) -> list[dict]:
    """[since, until) 窗口里按花费（再按 token）排的前几个对话：[{id, title|null, calls, tokens, cost}]。
    报表用“本月至今”（until=None），某天明细用那天的本地 [0 点, 次日 0 点)。
    没有对话归属的调用（如登录前的记忆向量）不进这张表；对话删了用量还在，title 给 null，
    客户端显示“已删除的对话”且不可点。外连接一次查完，不给每行再查标题。"""
    tokens = func.sum(UsageRecord.prompt_tokens + UsageRecord.completion_tokens)
    cost = func.sum(UsageRecord.cost)
    rows = (await db.execute(
        select(UsageRecord.conversation_id, Conversation.title, func.count(), tokens, cost)
        .outerjoin(Conversation, Conversation.id == UsageRecord.conversation_id)
        .where(UsageRecord.created_at >= since, UsageRecord.conversation_id.is_not(None),
               *([UsageRecord.created_at < until] if until is not None else []))
        .group_by(UsageRecord.conversation_id, Conversation.title)
        .order_by(cost.desc(), tokens.desc(), UsageRecord.conversation_id)
        .limit(limit)
    )).all()
    return [{"id": cid, "title": title, "calls": n, "tokens": int(t or 0), "cost": round(float(k or 0), 4)}
            for cid, title, n, t, k in rows]


async def _totals(db: AsyncSession, since: datetime, until: datetime) -> dict:
    """[since, until) 窗口的合计 {calls, tokens, cost}（不按模型拆，一条聚合查询）。"""
    n, t, k = (await db.execute(
        select(func.count(), func.sum(UsageRecord.prompt_tokens + UsageRecord.completion_tokens), func.sum(UsageRecord.cost))
        .where(UsageRecord.created_at >= since, UsageRecord.created_at < until)
    )).one()
    return {"calls": int(n or 0), "tokens": int(t or 0), "cost": round(float(k or 0), 4)}


async def _last_month(db: AsyncSession, now: datetime) -> dict:
    """上个月：全月合计 + “同期”合计 to_date（上月 1 号 0 点到上月同一天同一时刻，用户时区）。
    同期按日历对齐而不是按经过的秒数：10 月 11 日 07:30 对比 9 月 11 日 07:30。
    上月没有这一天（3 月 31 日对 2 月）就截到上月月底 = 全月。客户端拿“本月至今 vs 上月同期”算涨跌，
    这样月初不会因为本月才过了几天而永远显示“大降”。"""
    tz = ZoneInfo(settings.timezone)
    local = now.astimezone(tz)
    this_start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_start = (this_start - timedelta(days=1)).replace(day=1)
    prev_days = calendar.monthrange(prev_start.year, prev_start.month)[1]
    if local.day > prev_days:
        cutoff = this_start
    else:
        cutoff = datetime.combine(prev_start.date().replace(day=local.day), local.timetz().replace(tzinfo=None), tz)
    since, until = prev_start.astimezone(timezone.utc), this_start.astimezone(timezone.utc)
    whole = await _totals(db, since, until)
    return {**whole, "to_date": await _totals(db, since, min(cutoff.astimezone(timezone.utc), until))}


async def report(db: AsyncSession, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    out: dict = {**_head(), "budget": settings.monthly_budget or None}
    periods = _periods(now)
    for name, since in periods.items():
        out[name] = await _aggregate(db, UsageRecord.created_at >= since)
    out["daily"] = await _daily(db, periods["month"], now)
    out["conversations"] = await _top_conversations(db, periods["month"])
    out["last_month"] = await _last_month(db, now)
    return out


async def conversation_report(db: AsyncSession, conversation_id: str) -> dict:
    """单个对话从头到现在的用量（含它的滚动摘要、记忆向量等深处调用）。
    对话删了用量行还在（没有外键），所以月度总账不受影响；这里只按 id 查。"""
    return {**_head(), "total": await _aggregate(db, UsageRecord.conversation_id == conversation_id)}


async def day_report(db: AsyncSession, day: date) -> dict:
    """某一天（用户时区的本地日期）的明细：{currency, priced, date, total, conversations}，
    total 同 _aggregate（按模型拆分），conversations 同报表的 conversations（那天最花钱的前几个对话）。
    窗口是本地 [0 点, 次日 0 点) 换成 UTC 去比较，和 report() 的 daily 分桶同一条边界，
    所以图上那根柱子的数 = 这里 total 的数。哪天都能查（不限本月），没用量就是全 0。"""
    tz = ZoneInfo(settings.timezone)
    start = datetime.combine(day, time(), tz).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(1), time(), tz).astimezone(timezone.utc)
    return {**_head(), "date": day.isoformat(),
            "total": await _aggregate(db, UsageRecord.created_at >= start, UsageRecord.created_at < end),
            "conversations": await _top_conversations(db, start, end)}
