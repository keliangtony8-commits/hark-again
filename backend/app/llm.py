"""模型调用的唯一出口：业务层只认模型别名（fast / smart / …）。

网关模式：别名原样发给 LiteLLM，由它翻译成供应商模型。
直连模式：MODEL_MAP 在这里把别名翻译成上游模型名，直接打供应商的 OpenAI 兼容接口。
记账（usage）始终按别名记，价格表也按别名配。"""
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from openai import AsyncOpenAI

from . import usage
from .config import settings

client = AsyncOpenAI(base_url=settings.llm_base_url,
                     api_key=settings.llm_api_key or settings.litellm_master_key or "none")


def upstream(alias: str) -> str:
    """别名 → 实际发给接口的模型名（直连模式翻译；网关模式原样）。"""
    return settings.model_map.get(alias, alias)


def chat_model(alias: str | None) -> str:
    """对话选的模型 → 实际调用的别名：不在 CHAT_MODELS 里（没选、配置改了）一律回落到默认。"""
    return alias if alias and alias in settings.chat_models else settings.default_model


def chat_models() -> dict:
    """给客户端的可选列表（GET /api/catalog/models）。"""
    return {"default": settings.default_model,
            "models": [{"id": k, "label": v} for k, v in settings.chat_models.items()]}


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str = ""


@dataclass
class Reasoning:
    """推理模型的思考片段：只给客户端临时展示，不进回复、不存库、不回传给模型。"""
    text: str


def reasoning_of(delta) -> str:
    """不同供应商/网关的字段名不一：reasoning_content（LiteLLM、DeepSeek、阶跃）或 reasoning（阶跃、OpenRouter）。"""
    extra = getattr(delta, "model_extra", None) or {}
    return getattr(delta, "reasoning_content", None) or extra.get("reasoning_content") or extra.get("reasoning") or ""


@dataclass
class Turn:
    """一次模型调用的完整结果（流式过程中逐步填满）。"""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens: int = 0  # 这次调用用掉的 token（输入 + 输出；供应商没报用量就是 0）：内核按它管一轮的用量预算
    prompt: int = 0  # 其中输入部分：上文压缩（agent/compact.py）按它量上文有多长


async def stream_turn(messages: list[dict], tools: list[dict] | None = None,
                      model: str | None = None) -> AsyncIterator[str | Reasoning | Turn]:
    """流式产出文本片段(str) / 思考片段(Reasoning)，最后产出一个 Turn（含完整文本与工具调用）。"""
    kwargs = {"tools": tools} if tools else {}
    model = model or settings.default_model
    stream = await client.chat.completions.create(
        model=upstream(model), messages=messages, stream=True, stream_options={"include_usage": True}, **kwargs
    )
    turn = Turn()
    calls: dict[int, ToolCall] = {}
    last_usage = None
    try:
        async for chunk in stream:
            # 有的供应商（阶跃）每个包都带“累计”用量，有的只在最后一个空包带：只记最后一次，避免重复计费
            if getattr(chunk, "usage", None):
                last_usage = chunk.usage
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if thought := reasoning_of(delta):
                yield Reasoning(thought)
            if delta.content:
                turn.text += delta.content
                yield delta.content
            for tc in delta.tool_calls or []:
                call = calls.setdefault(tc.index, ToolCall(id="", name=""))
                if tc.id:
                    call.id = tc.id
                if tc.function and tc.function.name:
                    call.name += tc.function.name
                if tc.function and tc.function.arguments:
                    call.arguments += tc.function.arguments
    finally:  # 用户点停止（生成器被关闭）也要把已经花掉的 token 记上
        if last_usage is not None:
            await usage.record(model, "chat", last_usage.prompt_tokens or 0, last_usage.completion_tokens or 0)
    turn.tool_calls = [calls[i] for i in sorted(calls)]
    if last_usage is not None:
        turn.prompt = last_usage.prompt_tokens or 0
        turn.tokens = turn.prompt + (last_usage.completion_tokens or 0)
    yield turn


class Truncated(RuntimeError):
    """strict 模式下输出被 max_tokens 截断（半截摘要不能用）。"""


async def complete(messages: list[dict], model: str | None = None, kind: str = "summary",
                   tools: list[dict] | None = None, max_tokens: int | None = None, strict: bool = False) -> str:
    """一次性（非流式）补全：后台小活用，比如滚动摘要、上文压缩。kind 只用于记账分类。
    tools：重放带工具调用的上文时照带工具定义（tool_choice=none，只要文字；前缀和对话请求一致，缓存能命中）。
    strict：被截断（finish_reason=length）就抛 Truncated。"""
    model = model or settings.default_model
    kwargs: dict = {"tools": tools, "tool_choice": "none"} if tools else {}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    r = await client.chat.completions.create(model=upstream(model), messages=messages, **kwargs)
    if r.usage:
        await usage.record(model, kind, r.usage.prompt_tokens or 0, r.usage.completion_tokens or 0)
    if strict and r.choices and getattr(r.choices[0], "finish_reason", None) == "length":
        raise Truncated("输出被截断")
    return (r.choices[0].message.content or "").strip()


async def transcribe(filename: str, data: bytes) -> str:
    """语音转文字（gateway 供应商）：OpenAI 音频接口 + 别名 stt。其它供应商见 voice.py。"""
    r = await client.audio.transcriptions.create(model=upstream(settings.stt_model), file=(filename, data))
    return r.text.strip()


async def embed(texts: list[str]) -> list[list[float]]:
    """文本向量（别名 embed），用于记忆检索。"""
    r = await client.embeddings.create(model=upstream(settings.embed_model), input=texts)
    if getattr(r, "usage", None):
        await usage.record(settings.embed_model, "embed", r.usage.prompt_tokens or 0, 0)
    return [d.embedding for d in r.data]
