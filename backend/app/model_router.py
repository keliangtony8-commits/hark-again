# Copyright 2025 Google LLC
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
#
# Ported from google-gemini/gemini-cli packages/core/src/routing/{modelRouterService.ts, routingStrategy.ts,
#   strategies/compositeStrategy.ts, strategies/overrideStrategy.ts, strategies/classifierStrategy.ts,
#   strategies/defaultStrategy.ts} (Apache-2.0), modified:
#   照搬：责任链（非终结策略依次试，返回 None = 让给下一个，抛异常 = 记日志后继续；最后一个是终结策略必须给结论）、
#   Decision{model, source, reason, ms}、source 带链名前缀（"router/classifier"）、显式选了模型 → override 直接用、
#   classifier 的二选一 rubric（4 步以上 / 规划设计 / 范围大要调查 / 查不明原因的毛病 → 复杂；具体、有边界、1–3 步 → 简单；
#   “操作上简单压过措辞上的宏大”）、只给最近 HISTORY_TURNS 4 条不含工具的上文 + 这一问、回答 JSON {reasoning, model_choice}、
#   分类失败 → 让给下一个策略、终结策略 = 默认（强模型）、一轮只路由一次（client.ts currentSequenceModel：同一轮里不换）。
# 修改：①先过本地规则（rules，零调用）：只有图而简单档看不了图 → 复杂；“继续 / 好的”这类接话 → 沿用上一轮路由的模型（sticky，
#       Gemini 只在一轮内粘）；寒暄道谢 → 简单；贴了代码块 / 报错堆栈 / 很长 → 复杂。②系统事件触发的一轮（后台任务结束）不问分类器
#       （Gemini：function response 绕过分类器），沿用上一轮或默认。③rubric 改成中文、面向通用助手（查资料、开网页办事、写文件…），
#       例子换成我们的场景。④分类器用最便宜的别名（router_model，空 = summary_model）、最低思考档、6 秒超时。
#       ⑤模式 settings.model_router：auto（规则 + 分类器）/ rules（规则不确定就用默认强模型，零调用）/ off（不提供“自动”）。
#       ⑥没有 fallback / approval / numerical / gemma 策略：备用模型已由 llm_retry 管（v1.50），其余是 Gemini 专有。
"""“自动选模型”的唯一规则：对话选了 auto 时，每轮开头决定这一轮用简单档（router_simple，便宜快）还是复杂档（router_complex）。

用法：runner 每轮开头 `decision = await route(choice, text, history, previous, has_images, notice)`，
choice = llm.chat_model(conv.model) 的结果；不是 AUTO 就原样返回（override）。
choosable(alias) = 客户端 / 任务能选的模型（含 auto）——所有“这个模型能不能选”的检查都走它。
"""
import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass

from .config import settings

log = logging.getLogger(__name__)

AUTO = "auto"
MODES = ("auto", "rules", "off")
LABEL = "自动"
SIMPLE, COMPLEX = "simple", "complex"

HISTORY_TURNS = 4        # Gemini HISTORY_TURNS_FOR_CONTEXT
HISTORY_WINDOW = 20      # Gemini HISTORY_SEARCH_WINDOW：只在最近 20 条里找
TURN_MAX = 600           # 每条上文最多给分类器多少字
REQUEST_MAX = 2000       # 这一问最多给多少字
TIMEOUT_S = 6.0
LONG_REQUEST = 2000      # 这一问超过这么长 → 复杂（规则）

CONTINUE_RE = re.compile(r"^(继续|接着|接着做|继续吧|好|好的|好滴|嗯|嗯嗯|可以|行|没问题|ok|okay|go|continue|yes|是的|对|就这样|开始吧)[\s!！。.~～,，]*$", re.I)
GREETING_RE = re.compile(r"^(你好|您好|嗨|哈喽|hi|hello|hey|在吗|在不在|早|早上好|中午好|下午好|晚上好|晚安|谢谢|谢了|多谢|感谢|thanks|thank you|thx|辛苦了|拜拜|再见|bye)[\s!！。.~～,，呀啊哦哈]*$", re.I)
TRACE_RE = re.compile(r"Traceback \(most recent call last\)|^\s+at .*\S+:\d+:\d+\)?$|^\s*File \".+\", line \d+", re.M)

CLASSIFIER_PROMPT = f"""你是一个专门做“任务分流”的 AI，唯一的工作是判断用户这次请求的复杂度，在 `{SIMPLE}`（简单）和 `{COMPLEX}`（复杂）之间二选一。
1. `{SIMPLE}`：又快又省的模型，适合明确、有边界的小事。
2. `{COMPLEX}`：更强的模型，适合复杂、开放、要多步完成的事。
<complexity_rubric>
满足下面任意一条就是复杂（选 `{COMPLEX}`）：
1. 操作多（预计 4 步 / 4 次工具调用以上）：前后依赖的多个动作、要好好规划、或者要协调改好几处。
2. 规划与设计：问“怎么做才好”“为什么”，要给建议、方案、架构或长远打算。
3. 含糊或范围大：说得很宽泛，需要大量调查、搜集、比较。
4. 深度排错：从症状出发找不明原因的问题。
简单（选 `{SIMPLE}`）= 具体、有边界、操作少（预计 1–3 步）。操作上简单压过措辞上的宏大。
</complexity_rubric>
只用 JSON 回答，不要输出 JSON 以外的任何文字：
{{"reasoning": "一两句理由，对照上面的标准", "model_choice": "{SIMPLE} 或 {COMPLEX}"}}
--- 例子 ---
用户：“帮我规划一下下个月去日本十天的行程，预算一万”
{{"reasoning": "要调查、比较并规划多天行程，属于规划与设计、范围大。", "model_choice": "{COMPLEX}"}}
用户：“列一下工作区里有哪些文件”
{{"reasoning": "一次工具调用就能完成，操作少。", "model_choice": "{SIMPLE}"}}
用户：“把 notes.md 里的日期都改成 2026 年，再生成一份 PDF 发给我，顺便把旧文件归档”
{{"reasoning": "多个前后依赖的步骤，操作多。", "model_choice": "{COMPLEX}"}}
用户：“明天上海天气怎么样”
{{"reasoning": "查一次就能回答，具体有边界。", "model_choice": "{SIMPLE}"}}
用户：“我的网站点保存按钮就报错 Cannot read property 'map' of undefined，帮我修好”
{{"reasoning": "只有症状、原因未知，需要排查，属于深度排错。", "model_choice": "{COMPLEX}"}}
用户：“把 utils.js 里的变量 data 改名叫 userData，最好的办法是什么？”
{{"reasoning": "虽然问“最好的办法”，实际是一处局部修改，操作少。", "model_choice": "{SIMPLE}"}}
"""


@dataclass
class Decision:
    model: str           # 这一轮实际用的别名
    source: str          # 谁定的："router/override" | "router/rules" | "router/sticky" | "router/classifier" | "router/default" | …
    reason: str = ""     # 给人看的一句理由（分类器的 reasoning / 规则名）
    ms: int = 0
    complexity: str = ""  # simple | complex | ""（override）


def mode() -> str:
    m = (settings.model_router or "").strip().lower()
    return m if m in MODES else "auto"


def enabled() -> bool:
    """能不能选“自动”：没关、两档都是聊天里真有的别名、而且不是同一个。"""
    s, c = settings.router_simple, settings.router_complex
    return mode() != "off" and s in settings.chat_models and c in settings.chat_models and s != c


def choosable(alias: object) -> bool:
    """客户端 / 定时任务能不能选这个模型（含 auto）。"""
    return isinstance(alias, str) and (alias in settings.chat_models or (alias == AUTO and enabled()))


def default_choice() -> str:
    """没选模型的对话用什么：router_default 开着且能自动 → auto，否则 default_model。"""
    return AUTO if settings.router_default and enabled() else settings.default_model


def alias_for(complexity: str) -> str:
    return settings.router_simple if complexity == SIMPLE else settings.router_complex


def catalog_entry() -> dict | None:
    """模型列表里“自动”这一项（GET /api/catalog/models）；routes 告诉客户端两档各是谁。"""
    if not enabled():
        return None
    return {"id": AUTO, "label": LABEL, "auto": True,
            "routes": {SIMPLE: settings.router_simple, COMPLEX: settings.router_complex}}


def view(choice: str) -> str:
    """组装上文时按哪个别名决定“这一问的图片发原图还是描述”（context.build_history）：auto 按复杂档——
    复杂档能看图就留原图，rules 再保证“简单档看不了图”时不会路由过去；复杂档也看不了图 → 描述，两档都能收。"""
    return settings.router_complex if choice == AUTO else choice


def label_of(alias: str) -> str:
    return settings.chat_models.get(alias, alias)


# ---------- 策略：每个返回 Decision | None（None = 让给下一个） ----------

def _text_of(content) -> str:
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return content if isinstance(content, str) else ""


def rules(text: str, history: list[dict], previous: str | None, has_images: bool, notice: bool) -> Decision | None:
    """零调用的本地规则（我们加的）；不确定 → None。"""
    t = (text or "").strip()
    sticky = previous if previous in (settings.router_simple, settings.router_complex) else None
    if notice:  # 系统事件触发的一轮：没有新的用户请求可分，沿用上一轮（Gemini：function response 不过分类器）
        return Decision(sticky, "sticky", "系统事件，沿用上一轮", complexity=_complexity(sticky)) if sticky else None
    if has_images and settings.router_simple not in settings.vision_models:
        return Decision(settings.router_complex, "rules", "带了图片，简单档看不了图", complexity=COMPLEX)
    if not t:
        return None
    if CONTINUE_RE.match(t):
        if sticky:
            return Decision(sticky, "sticky", "接着上一轮做", complexity=_complexity(sticky))
        return None
    if GREETING_RE.match(t):
        return Decision(settings.router_simple, "rules", "寒暄", complexity=SIMPLE)
    if len(t) > LONG_REQUEST or "```" in t or TRACE_RE.search(t):
        return Decision(settings.router_complex, "rules", "长内容 / 代码 / 报错堆栈", complexity=COMPLEX)
    return None


def _complexity(alias: str | None) -> str:
    return SIMPLE if alias == settings.router_simple else COMPLEX if alias == settings.router_complex else ""


def context_for(history: list[dict]) -> list[dict]:
    """给分类器的上文：最近 HISTORY_WINDOW 条里去掉工具调用 / 工具结果 / 内部提示，取最后 HISTORY_TURNS 条，每条截断。
    最后一条用户消息（这一问本身）不算在内，由调用方单独给。"""
    window = history[-HISTORY_WINDOW:]
    if window and window[-1].get("role") == "user":
        window = window[:-1]
    clean = []
    for m in window:
        role = m.get("role")
        if role not in ("user", "assistant") or m.get("tool_calls"):
            continue
        t = _text_of(m.get("content")).strip()
        if not t or t.startswith("[系统提示]"):
            continue
        clean.append({"role": role, "content": t[:TURN_MAX] + ("…" if len(t) > TURN_MAX else "")})
    return clean[-HISTORY_TURNS:]


def parse(raw: str) -> tuple[str, str] | None:
    """分类器的回复 → (complexity, reasoning)；答非所问 → None（Gemini zod 校验失败 = 让给下一个）。"""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", s)
    start = s.find("{")
    if start < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(s[start:])
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    choice, why = obj.get("model_choice"), obj.get("reasoning")
    if choice not in (SIMPLE, COMPLEX) or not isinstance(why, str):
        return None
    return choice, why.strip()[:200]


async def classify(text: str, history: list[dict]) -> Decision | None:
    """问最便宜的模型这一问是简单还是复杂；任何失败 → None（让给默认）。"""
    from . import llm  # llm 也 import 本模块（chat_model 走 choosable），这里延迟导入
    t = (text or "").strip()
    if not t:
        return None
    request = t[:REQUEST_MAX] + ("…" if len(t) > REQUEST_MAX else "")
    messages = [{"role": "system", "content": CLASSIFIER_PROMPT}, *context_for(history),
                {"role": "user", "content": f"请判断这次请求：\n{request}"}]
    try:
        raw = await asyncio.wait_for(
            llm.complete(messages, settings.router_model or settings.summary_model, kind="router", max_tokens=200),
            TIMEOUT_S)
    except Exception as e:  # noqa: BLE001 —— 分类失败不影响这一轮：用默认
        log.warning("model router classifier failed: %s", e)
        return None
    got = parse(raw)
    if got is None:
        log.warning("model router classifier answered off-schema: %.200s", raw)
        return None
    complexity, why = got
    return Decision(alias_for(complexity), "classifier", why, complexity=complexity)


async def route(choice: str, text: str, history: list[dict], previous: str | None = None,
                has_images: bool = False, notice: bool = False, chain: str = "router") -> Decision:
    """决定这一轮用哪个别名（终结：一定给结论）。choice 不是 AUTO → override。"""
    started = time.monotonic()

    def done(d: Decision) -> Decision:
        d.source = f"{chain}/{d.source}"
        d.ms = d.ms or round((time.monotonic() - started) * 1000)
        return d

    if choice != AUTO:
        return done(Decision(choice, "override"))
    if not enabled():  # 配置改了、auto 不再可选：和别的失效选择一样回落到默认模型
        return done(Decision(settings.default_model, "default", "自动选模型没开"))
    try:
        d = rules(text, history, previous, has_images, notice)
    except Exception as e:  # noqa: BLE001 —— Gemini composite：一个策略出错，继续下一个
        log.warning("model router rules failed: %s", e)
        d = None
    if d is None and mode() == "auto" and not notice:
        d = await classify(text, history)
    if d is None:
        d = Decision(settings.router_complex, "default", "拿不准，用复杂档", complexity=COMPLEX)
    return done(d)


def wire(d: Decision) -> dict:
    """turn.model 事件（这一轮开头推给客户端，“自动 · 快速”）。"""
    return {"type": "turn.model", "model": d.model, "label": label_of(d.model),
            "complexity": d.complexity, "source": d.source, "reason": d.reason}
