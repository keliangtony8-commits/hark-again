# MIT License — Copyright (c) 2026 DeepSeek
# Ported from deepseek-harness/packages/llm/llm/src/retry-policy.ts, llm/src/error.ts,
# llm-deepseek/src/transport.ts, llm-pi-ai/src/stream.ts (classifyPiAiError) and
# llm-retry/src/index.ts (localDelay, Retry-After bound) (MIT), adapted to Python / the OpenAI SDK.
# Grafts: Codex responses_retry.rs (server advice never extends the retry budget; the UI is told
# "Reconnecting n/m" instead of staring at a frozen screen) and Gemini CLI retry.ts (onPersistent429 →
# fall back to another model, attempts reset) (Apache-2.0, modified).
"""模型调用失败怎么办的唯一规则：分类 → 要不要重试、等多久 → 重试用完换不换备用模型 → 给用户看的话。

只做判断，不做调用：流式对话的重试在 agent/loop.py（要先撤回半截文字、告诉客户端），
一次性补全的重试在 llm.complete（retry_call）。"""
import asyncio
import random as _random
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

from .config import settings

# ---- 分类（deepseek-harness 的稳定错误码：按码路由，不解析 message） ----
AUTH, QUOTA, RATE_LIMIT, CONTEXT, INVALID = "AUTH", "QUOTA", "RATE_LIMIT", "CONTEXT_WINDOW_EXCEEDED", "INVALID_REQUEST"
SERVER, TIMEOUT, TRANSPORT, EMPTY = "SERVER", "TIMEOUT", "TRANSPORT", "EMPTY_RESPONSE"

RETRYABLE = frozenset({EMPTY, RATE_LIMIT, SERVER, TIMEOUT, TRANSPORT})  # DEFAULT_RETRYABLE_CODES
# 重试用完后可以换备用模型的码（Gemini：容量/额度/找不到模型 → 换 flash）。AUTH/INVALID/CONTEXT 换模型也一样会错
FALLBACK = RETRYABLE | {QUOTA, "HTTP_404"}

DEFAULT_JITTER = 0.1

# error.ts：明确说“上文超长”的措辞（结构化码 + 常见英文句式），外加中文供应商的说法
_STRUCTURED_CONTEXT = re.compile(r"(?:^|[^a-z0-9])context[\s_-](?:length|window)[\s_-]"
                                 r"(?:exceed(?:ed|s)?|overflow(?:ed)?|limit[\s_-]exceeded)(?:$|[^a-z0-9])", re.I)
_TOO_LARGE_FOR_CONTEXT = re.compile(r"\b(?:request|prompt|input|messages?)\s+(?:is\s+|are\s+)?too\s+(?:large|long)\s+for\s+"
                                    r"(?:(?:this|the)\s+)?(?:model(?:'s)?\s+)?context(?:\s+window)?\b", re.I)
_EXCEEDS_CONTEXT = re.compile(r"\b(?:input|prompt|request|messages?)\b.{0,40}\b(?:exceed(?:s|ed)?|overflows?|is\s+larger\s+than)\b"
                              r".{0,40}\b(?:the\s+)?(?:model(?:'s)?\s+)?context(?:\s+(?:length|window))?\b", re.I)
_MAX_CONTEXT = re.compile(r"\b(?:maximum|max)(?:\s+(?:allowed|supported))?\s+context\s+(?:length|window)\b", re.I)
_TOO_LONG_FOR_MODEL = re.compile(r"\b(?:input|prompt|request)\s+(?:is\s+)?too\s+(?:long|large)\s+for\s+(?:this|the)\s+model\b", re.I)
_CONTEXT_ZH = re.compile(r"上下文(?:长度)?(?:超|过)|超出上下文|超过.{0,6}(?:最大)?上下文|输入(?:过|太)长")

# error.ts isQuotaExceededError：额度/余额用完（不是一时限流）
_QUOTA = (re.compile(r"\binsufficient[\s_-]+(?:quota|balance|credits?)\b", re.I),
          re.compile(r"\b(?:quota|usage[\s_-]+limit)[\s_-]+(?:exceeded|exhausted|reached)\b", re.I),
          re.compile(r"\bexceed(?:ed|s)?[\s_-]+(?:(?:your|the)[\s_-]+)?(?:current[\s_-]+)?quota\b", re.I),
          re.compile(r"\b(?:balance|credits?)[\s_-]+(?:exhausted|depleted)\b", re.I),
          re.compile(r"\bout[\s_-]+of[\s_-]+(?:credits?|budget)\b", re.I),
          re.compile(r"余额不足|额度(?:已)?(?:用完|用尽|不足)|欠费"))

# classifyPiAiError：没有状态码时只能看措辞（流中途断开的各种说法）
_TIMEOUT_TEXT = re.compile(r"\btime(?:d)?\s*out\b|timeout", re.I)
_TRANSPORT_TEXT = re.compile(r"stream ended (?:before|without)\b|\b(?:network|connection|socket|fetch)\b|\bECONN[A-Z]+\b"
                             r"|other side closed|peer closed|incomplete chunked read|HTTP2 request did not get a response"
                             r"|\bterminated\b|premature close|server disconnected", re.I)


def is_context_exceeded(detail: str) -> bool:
    return bool(_STRUCTURED_CONTEXT.search(detail) or _MAX_CONTEXT.search(detail) or _TOO_LARGE_FOR_CONTEXT.search(detail)
                or _TOO_LONG_FOR_MODEL.search(detail) or _EXCEEDS_CONTEXT.search(detail) or _CONTEXT_ZH.search(detail))


def is_quota_exceeded(detail: str) -> bool:
    return any(p.search(detail) for p in _QUOTA)


class EmptyResponse(RuntimeError):
    """模型正常结束却一个字、一个工具调用都没给（deepseek EMPTY_RESPONSE：什么都没产出，重来是安全的）。"""


@dataclass(frozen=True)
class Failure:
    code: str
    status: int | None = None
    retry_after_ms: float | None = None  # 供应商给的 Retry-After（毫秒，>0 才有）
    message: str = ""


def retry_after_ms(value: str | None, now: float | None = None) -> float | None:
    """Retry-After 头：秒数或 HTTP 日期（transport.ts）；非正、解析不了 → None。"""
    if value is None:
        return None
    value = value.strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        ms = float(value) * 1000
    else:
        try:
            ms = parsedate_to_datetime(value).timestamp() * 1000 - (time.time() if now is None else now) * 1000
        except (TypeError, ValueError, IndexError, OverflowError):
            return None
    return ms if ms > 0 and ms == ms and ms != float("inf") else None


def _detail(e: BaseException) -> tuple[str, str]:
    """(type/code/message 拼成的一句, message)：只取错误体里这三个字段（providerErrorDetail）。"""
    body = getattr(e, "body", None)
    err = body.get("error") if isinstance(body, dict) and isinstance(body.get("error"), dict) else body
    fields = [str(err.get(k)) for k in ("type", "code", "message") if isinstance(err, dict) and isinstance(err.get(k), (str, int))]
    message = str(err.get("message")) if isinstance(err, dict) and isinstance(err.get("message"), str) else str(e)
    code = getattr(e, "code", None)
    return " ".join([*fields, str(code) if isinstance(code, str) else "", str(e)]), message


def classify(e: BaseException) -> Failure:
    """任何调用异常 → Failure（transport.ts providerError 的顺序：鉴权 > 额度 > 限流 > 超长 > 坏请求 > 服务器）。"""
    if isinstance(e, EmptyResponse):
        return Failure(EMPTY, message=str(e))
    detail, message = _detail(e)
    status = getattr(e, "status_code", None)
    status = status if isinstance(status, int) else None
    headers = getattr(getattr(e, "response", None), "headers", None)
    after = None
    if headers is not None:
        try:
            after = retry_after_ms(headers.get("retry-after"))
        except Exception:  # noqa: BLE001 — 头部对象形状不一
            after = None
    kind = type(e).__name__
    etype = ""
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        err = body.get("error") if isinstance(body.get("error"), dict) else body
        etype = str(err.get("type") or "") if isinstance(err, dict) else ""
    if status in (401, 403) or etype in ("authentication_error", "permission_error"):
        code = AUTH
    elif status == 402 or is_quota_exceeded(detail):
        code = QUOTA
    elif status == 429 or etype == "rate_limit_error":
        code = RATE_LIMIT
    elif is_context_exceeded(detail) or "context_length_exceeded" in detail:
        code = CONTEXT
    elif status in (400, 413, 422) or etype == "invalid_request_error":
        code = INVALID
    elif (status is not None and status >= 500) or etype in ("api_error", "overloaded_error", "server_error"):
        code = SERVER
    elif status is not None:
        code = f"HTTP_{status}"
    elif "Timeout" in kind or isinstance(e, (asyncio.TimeoutError, TimeoutError)) or _TIMEOUT_TEXT.search(detail):
        code = TIMEOUT  # openai.APITimeoutError / httpx.ReadTimeout（流式空闲超时）
    elif "Connection" in kind or "Protocol" in kind or "Network" in kind or isinstance(e, (ConnectionError, OSError)) \
            or _TRANSPORT_TEXT.search(detail):
        code = TRANSPORT  # openai.APIConnectionError / httpx.RemoteProtocolError（中途断开）
    elif kind == "APIError":
        code = SERVER  # 流里带来的错误事件，没有状态码（transport.ts：status undefined → SERVER）
    else:
        code = "UNKNOWN"
    return Failure(code, status, after, message[:300])


# ---- 退避（retry-policy.ts + llm-retry localDelay） ----
@dataclass(frozen=True)
class Policy:
    max_retries: int = 5
    initial_ms: float = 500
    max_ms: float = 10_000
    jitter: float = DEFAULT_JITTER
    codes: frozenset = RETRYABLE

    def __post_init__(self):
        if not isinstance(self.max_retries, int) or self.max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        if not (0 < self.initial_ms <= self.max_ms):
            raise ValueError("initial_ms must be positive and ≤ max_ms")
        if not (0 <= self.jitter <= 1):
            raise ValueError("jitter must be between 0 and 1")
        if not self.codes:
            raise ValueError("codes must not be empty")


def policy() -> Policy:
    """当前配置；配置不合法就用默认（不能因为一个配置项让所有对话都起不来）。"""
    try:
        return Policy(max(0, int(settings.llm_max_retries)), float(settings.llm_retry_initial_ms),
                      float(settings.llm_retry_max_ms))
    except (ValueError, TypeError):
        return Policy()


def local_delay(p: Policy, retry: int, rand: Callable[[], float] = _random.random) -> float:
    """第 retry 次重试（从 1 起）的本地退避毫秒：initial × 2^(retry−1) 封顶 max，再乘 [1−j, 1+j] 抖动，仍不超过 max。"""
    exponent = min(retry - 1, 60)  # 原版 1024（JS 溢出成 Infinity）；Python 浮点 2**1024 会抛 OverflowError
    exponential = min(p.initial_ms * (2.0 ** exponent), p.max_ms)
    jitter = 1 - p.jitter + 2 * p.jitter * rand()
    return min(exponential * jitter, p.max_ms)


def next_delay(p: Policy, f: Failure, retry: int, rand: Callable[[], float] = _random.random) -> float | None:
    """第 retry 次重试要等的毫秒；None = 不重试（码不在可重试集、预算用完、供应商要等的比上限还久）。
    供应商的 Retry-After 只决定“等多久”，不增加次数（Codex：server advice controls timing without extending limits）。"""
    if f.code not in p.codes or retry > p.max_retries:
        return None
    if f.retry_after_ms is not None:
        return None if f.retry_after_ms > p.max_ms else f.retry_after_ms
    return local_delay(p, retry, rand)


def fallback_for(alias: str | None, tried: set[str] | frozenset = frozenset()) -> str | None:
    """重试用完后这一轮改用的备用别名（MODEL_FALLBACKS）；没配、配成自己、已经换过的都不算。"""
    if not alias:
        return None
    fb = settings.model_fallbacks.get(alias)
    return fb if fb and fb != alias and fb not in tried else None


def can_fall_back(f: Failure) -> bool:
    return f.code in FALLBACK


# ---- 给人看的话 ----
REASONS = {RATE_LIMIT: "模型那边限流了", SERVER: "模型服务器出错了", TIMEOUT: "模型太久没回应",
           TRANSPORT: "连接模型的网络断了", EMPTY: "模型回了个空答复"}


def reason(f: Failure) -> str:
    return REASONS.get(f.code, "模型调用出错了")


def user_text(e: BaseException) -> str:
    """重试也救不回来时，聊天里那条错误提示（不把供应商的英文原文糊给用户，原文只取一小段放括号里）。"""
    f = classify(e)
    tail = f"（{f.message[:120]}）" if f.message and f.code not in RETRYABLE else ""
    match f.code:
        case "AUTH":
            return "模型密钥无效或没有权限，检查服务器 .env 里的模型密钥。" + tail
        case "QUOTA":
            return "模型账户的额度或余额用完了，充值后再试。" + tail
        case "CONTEXT_WINDOW_EXCEEDED":
            return "这段对话太长，模型装不下了。开个新对话，或者让我先总结一下再继续。"
        case "INVALID_REQUEST":
            return "模型拒绝了这次请求" + (tail or "。") + "换个说法，或点重试。"
        case "HTTP_404":
            return "找不到配置的模型，检查 MODEL_MAP / 网关里的模型名。" + tail
        case code if code in RETRYABLE:
            return f"{reason(f)}，自动重试了几次还是不行，稍后点重试。"
    return f"模型调用失败：{f.message or e}"


async def retry_call(make: Callable[[], Awaitable], p: Policy | None = None,
                     sleep: Callable[[float], Awaitable] = asyncio.sleep):
    """一次性调用（没有半截输出要撤回）：按策略重试，用完把最后一个异常原样抛出（上层还要据它判断超长等）。"""
    p = p or policy()
    retry = 0
    while True:
        try:
            return await make()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            retry += 1
            delay = next_delay(p, classify(e), retry)
            if delay is None:
                raise
            await sleep(delay / 1000)
