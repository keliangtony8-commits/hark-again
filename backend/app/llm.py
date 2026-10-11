"""模型调用的唯一出口：所有请求都走 LiteLLM 网关，业务层只认模型别名。"""
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from openai import AsyncOpenAI

from . import usage
from .config import settings

client = AsyncOpenAI(base_url=settings.llm_base_url, api_key=settings.litellm_master_key)


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
class Turn:
    """一次模型调用的完整结果（流式过程中逐步填满）。"""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


async def stream_turn(messages: list[dict], tools: list[dict] | None = None,
                      model: str | None = None) -> AsyncIterator[str | Turn]:
    """流式产出文本片段(str)，最后产出一个 Turn（含完整文本与工具调用）。"""
    kwargs = {"tools": tools} if tools else {}
    model = model or settings.default_model
    stream = await client.chat.completions.create(
        model=model, messages=messages, stream=True, stream_options={"include_usage": True}, **kwargs
    )
    turn = Turn()
    calls: dict[int, ToolCall] = {}
    async for chunk in stream:
        if getattr(chunk, "usage", None):  # include_usage：最后一个包只带用量、没有 choices
            await usage.record(model, "chat", chunk.usage.prompt_tokens or 0, chunk.usage.completion_tokens or 0)
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
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
    turn.tool_calls = [calls[i] for i in sorted(calls)]
    yield turn


async def complete(messages: list[dict], model: str | None = None, kind: str = "summary") -> str:
    """一次性（非流式）补全：后台小活用，比如滚动摘要。kind 只用于记账分类。"""
    model = model or settings.default_model
    r = await client.chat.completions.create(model=model, messages=messages)
    if r.usage:
        await usage.record(model, kind, r.usage.prompt_tokens or 0, r.usage.completion_tokens or 0)
    return (r.choices[0].message.content or "").strip()


async def transcribe(filename: str, data: bytes) -> str:
    """语音转文字，同样走网关（别名 stt），换供应商只改 LiteLLM 配置。"""
    r = await client.audio.transcriptions.create(model=settings.stt_model, file=(filename, data))
    return r.text.strip()


async def embed(texts: list[str]) -> list[list[float]]:
    """文本向量（别名 embed），用于记忆检索。"""
    r = await client.embeddings.create(model=settings.embed_model, input=texts)
    if getattr(r, "usage", None):
        await usage.record(settings.embed_model, "embed", r.usage.prompt_tokens or 0, 0)
    return [d.embedding for d in r.data]
