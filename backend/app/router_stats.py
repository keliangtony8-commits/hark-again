# Event shape ported from google-gemini/gemini-cli packages/core/src/telemetry/types.ts ModelRoutingEvent
#   + metrics.ts recordModelRoutingMetrics (Apache-2.0), modified: 存进库（routings 表）而不是遥测，按月汇总给用量页；
#   加了“省了多少”的估算（Gemini 没有）。
"""“自动选模型的账”的唯一规则（用量页“自动选模型”一节）。

写：runner._route 每个 auto 轮调 record(db, cid, decision)（一行 routings，和对话的 routed_model 同一次提交）；
    这一轮的模型调用由 usage.routing(complexity) 打上档位（usage.route）。
读：month(db, since) → None（本月一轮“自动”都没有）| {
      turns, simple, complex,                      # 轮数（routings 行）
      free,                                        # 零调用就判掉的轮（rules / sticky）——没花分类器的钱
      classifier: {turns, cost, ms},               # 问了分类器的轮数、分类器调用的花费（usage.kind=router）、平均毫秒
      simple_cost,                                 # 简单档模型在简单档轮里实花
      saved | null,                                # 同样的 token 按复杂档单价重算 − 实花（复杂档没定价 → null）
      net | null,                                  # saved − classifier.cost（可能为负：分类器比省下的还贵）
    }
只算“简单档轮里、简单档模型的 chat 调用”：同一轮里备用模型、子助手用别的模型的调用不算省也不算亏
（换模型的那部分是别的规则定的）。估算假设复杂档会用同样多的 token——真实会不同，客户端写“约”。"""
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import model_router, prompt_cache
from .config import settings
from .models import Routing, UsageRecord

FREE_SOURCES = ("rules", "sticky")


def source_of(source: str) -> str:
    """"router/classifier" → "classifier"（存的时候去掉链名前缀）。"""
    return (source or "").rsplit("/", 1)[-1][:32] or "default"


async def record(db: AsyncSession, cid: str | None, d: "model_router.Decision") -> None:
    """只 add 不提交：调用方（runner._route）和 routed_model 一起提交。override 不记（不是自动轮）。"""
    src = source_of(d.source)
    if src == "override":
        return
    db.add(Routing(conversation_id=cid, model=d.model, complexity=d.complexity or "", source=src, ms=max(int(d.ms or 0), 0)))


def what_if(prompt: int, completion: int, cached: int) -> float | None:
    """这些 token 换成复杂档要花多少；复杂档没定价 → None。"""
    price = settings.model_prices.get(settings.router_complex)
    return prompt_cache.cost(price, prompt, completion, cached) if price else None


async def month(db: AsyncSession, since: datetime) -> dict | None:
    rows = (await db.execute(
        select(Routing.complexity, Routing.source, func.count(), func.sum(Routing.ms))
        .where(Routing.created_at >= since).group_by(Routing.complexity, Routing.source))).all()
    turns = sum(n for _, _, n, _ in rows)
    if not turns:
        return None
    simple = sum(n for c, _, n, _ in rows if c == model_router.SIMPLE)
    complex_ = sum(n for c, _, n, _ in rows if c == model_router.COMPLEX)
    free = sum(n for _, s, n, _ in rows if s in FREE_SOURCES)
    asked = [(n, ms) for _, s, n, ms in rows if s == "classifier"]
    asked_n = sum(n for n, _ in asked)
    asked_ms = round(sum(int(ms or 0) for _, ms in asked) / asked_n) if asked_n else 0
    classifier_cost = float((await db.execute(
        select(func.sum(UsageRecord.cost)).where(UsageRecord.created_at >= since, UsageRecord.kind == "router"))).scalar() or 0)
    p, c, h, k = (await db.execute(
        select(func.sum(UsageRecord.prompt_tokens), func.sum(UsageRecord.completion_tokens),
               func.sum(UsageRecord.cached_tokens), func.sum(UsageRecord.cost))
        .where(UsageRecord.created_at >= since, UsageRecord.route == model_router.SIMPLE,
               UsageRecord.kind == "chat", UsageRecord.model == settings.router_simple))).one()
    spent = float(k or 0)
    alt = what_if(int(p or 0), int(c or 0), int(h or 0))
    saved = round(max(alt - spent, 0.0), 4) if alt is not None else None
    return {"turns": turns, "simple": simple, "complex": complex_, "free": free,
            "classifier": {"turns": asked_n, "cost": round(classifier_cost, 4), "ms": asked_ms},
            "simple_cost": round(spent, 4), "saved": saved,
            "net": round(saved - classifier_cost, 4) if saved is not None else None,
            "simple_model": model_router.label_of(settings.router_simple),
            "complex_model": model_router.label_of(settings.router_complex)}
