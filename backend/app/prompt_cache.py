# Cached-token accounting ported from deepseek-harness packages/llm/token-meter/src/turn-usage.ts
# (normalizeUsage: only safe non-negative integer counts, a cache bucket never exceeds the prompt)
# and packages/llm/llm/src/types.ts TokenUsage (MIT, Copyright (c) DeepSeek).
# prompt_cache_key per conversation (subagents share the parent's key) grafted from
# openai/codex codex-rs/core/src/client.rs prompt_cache_key (Apache-2.0, modified).
"""提示缓存（省钱）的唯一规则：系统提示怎么排、缓存命中怎么读、要不要带 prompt_cache_key。

为什么：供应商（OpenAI / DeepSeek / 阶跃等 OpenAI 兼容接口）按“请求开头逐字相同的部分”自动缓存，
命中部分按便宜很多的价格计（常见 1/10～1/4）。一轮里助手调十几次模型，每次都重发同一段系统提示 + 工具定义 + 历史，
只要开头不变，后面每次都几乎全是命中。deepseek-harness 把“前缀稳定”当成头号约束（request-cache.e2e：
第一请求之后每次都必须 cacheReadTokens > 0）。我们之前把“现在几点（精确到分钟）”和“按这句话挑的记忆”放在系统提示
第二、三段，等于每次都从第二段开始失效。

一、排版：Prompt(stable, volatile)。stable = 几乎不变的段（人设、并行提示、技能目录、授权服务、MCP、项目/工作区、
    AGENTS.md、主机模式、子助手角色），volatile = 每轮会变的段（当前时间、相关记忆、滚动摘要、压下的任务结论），
    text() 一律 stable 在前、volatile 在后。加段只能经 add(kind, text)，调用方不再自己 `system +=`。
二、读命中：cached_of(usage) → int。字段名各家不一：prompt_tokens_details.cached_tokens（OpenAI / 阶跃 / LiteLLM）、
    prompt_cache_hit_tokens（DeepSeek）、cached_tokens（部分网关放在顶层）、cache_read_input_tokens（Anthropic 风格网关）。
    deepseek 的口径：只认安全的非负整数，命中数大于输入总数 = 数据矛盾 → 当 0（不让账面出现负的“未命中”）。
三、prompt_cache_key：settings.prompt_cache_key=True 时按对话发 "conv-<id>"（Codex 用会话 id 做缓存亲和；子助手、
    滚动摘要和上文压缩都在同一个 usage.scope 里，自然共用父对话的键）。默认关：不是每家都认这个参数；
    开了而供应商回 400 说不认 → 本进程内对这个别名不再发（和 reasoning 同一种退路）。
"""
import logging
import re
from dataclasses import dataclass, field

from .config import settings

log = logging.getLogger(__name__)

STABLE, VOLATILE = "stable", "volatile"
PARAM = "prompt_cache_key"
KEY_PREFIX = "conv-"
KEY_MAX = 64  # OpenAI 文档：prompt_cache_key 不超过 64 字符


@dataclass
class Prompt:
    """系统提示：先放稳定段再放易变段。空段不收。"""
    stable: list[str] = field(default_factory=list)
    volatile: list[str] = field(default_factory=list)

    def add(self, kind: str, text: str | None) -> "Prompt":
        if text and text.strip():
            (self.stable if kind == STABLE else self.volatile).append(text)
        return self

    def prefix(self) -> str:
        """稳定前缀（冒烟用来断言两轮之间逐字相同）。"""
        return "\n\n".join(self.stable)

    def text(self) -> str:
        return "\n\n".join([*self.stable, *self.volatile])


def _count(v) -> int | None:
    """deepseek isCount：安全非负整数；bool 不算（Python 里 True 是 int）。"""
    if isinstance(v, bool) or not isinstance(v, int) or v < 0 or v > 2 ** 53 - 1:
        return None
    return v


def _get(obj, name):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    v = getattr(obj, name, None)
    if v is None:
        extra = getattr(obj, "model_extra", None) or {}
        v = extra.get(name)
    return v


def cached_of(usage) -> int:
    """一次调用里命中缓存的输入 token 数（拿不到 / 不可信 → 0）。"""
    if usage is None:
        return 0
    prompt = _count(_get(usage, "prompt_tokens"))
    for v in (_get(_get(usage, "prompt_tokens_details"), "cached_tokens"),
              _get(usage, "prompt_cache_hit_tokens"),
              _get(usage, "cached_tokens"),
              _get(usage, "cache_read_input_tokens")):
        n = _count(v)
        if n is None:
            continue
        if prompt is not None and n > prompt:  # 矛盾的数据：不信（deepseek normalizeUsage 同样整笔作废）
            return 0
        return n
    return 0


def cost(prices: list[float] | None, prompt: int, completion: int, cached: int = 0) -> float:
    """按单价算钱：prices = [输入, 输出, 命中输入?]（每百万 token）。没配命中价 = 命中也按输入价（不虚报省了多少）。"""
    if not prices:
        return 0.0
    vals = list(prices)
    inp = vals[0] if len(vals) > 0 else 0.0
    out = vals[1] if len(vals) > 1 else 0.0
    hit = vals[2] if len(vals) > 2 else inp
    cached = min(max(cached, 0), prompt)
    return ((prompt - cached) * inp + cached * hit + completion * out) / 1_000_000


# —— prompt_cache_key ——
_unsupported: set[str] = set()
_REJECT = re.compile(r"prompt_cache_key", re.I)
_REJECT_WORD = re.compile(r"unsupported|not support|unknown|unrecogni[sz]ed|invalid|extra|not (?:permitted|allowed)|"
                          r"does not accept|不支持|无效|未知", re.I)


def key_for(conversation_id: str | None) -> str | None:
    if not conversation_id:
        return None
    return (KEY_PREFIX + conversation_id)[:KEY_MAX]


def kwargs(alias: str, conversation_id: str | None) -> dict:
    """要并进请求的参数（走 extra_body：老版本 SDK 不认这个具名参数也不会在本地报错）。"""
    key = key_for(conversation_id)
    if not settings.prompt_cache_key or not key or alias in _unsupported:
        return {}
    return {"extra_body": {PARAM: key}}


def rejected(e: BaseException) -> bool:
    if getattr(e, "status_code", None) not in (400, 422):
        return False
    text = f"{e} {getattr(e, 'body', None) or ''}"
    return bool(_REJECT.search(text) and _REJECT_WORD.search(text))


def mark_unsupported(alias: str) -> None:
    if alias not in _unsupported:
        log.warning("模型 %s 不接受 %s，本进程内不再发", alias, PARAM)
    _unsupported.add(alias)
