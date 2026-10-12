# Copyright (c) 2026 DeepSeek — MIT License.
# Ported from deepseek-ai/deepseek-harness packages/llm/llm/src/index.ts (normalizeModelInfo reasoning + resolveCallWithInfo)
# and llm-deepseek/src/model-info.ts (MIT), modified; grafts: openai/codex protocol/src/openai_models.rs
# (supported_reasoning_levels + default, children inherit; Apache-2.0, modified) and Gemini CLI
# packages/core/src/config/defaultModelConfigs.ts (helper calls think least; Apache-2.0, modified).
"""思考强度（reasoning_effort）的唯一规则：哪个模型别名能调、默认几档、对话的选择最后发什么。

配置 MODEL_REASONING（按别名）：{"smart": {"levels": ["low", "medium", "high"], "default": "medium"}}，
也可简写成列表 {"smart": ["low", "medium", "high"]}（默认取 medium，没有就取中间那档）。
levels 从“想得最少”排到“想得最多”（deepseek：efforts from least to greatest），重复 / 未知档 / 默认不在 levels 里
→ 启动时报错（deepseek normalizeModelInfo 的“配置错了大声失败”）。没配的别名 = 不发这个参数，用供应商自己的默认。

对话存的选择可能比配置活得久（换了模型、改了 .env）：选的档这个模型没有 → 用它的默认（Codex 换模型时回到该模型默认），
不像 deepseek 那样直接拒绝——那是请求时的显式参数，我们这是存下来的偏好。
后台小活（摘要、记忆整理、看图描述）用最低一档（Gemini 给 summarizer / classifier 配 thinkingBudget 0~512）。
供应商回 400 说不认这个参数 → 这个别名本进程内不再发（unsupported），这次去掉参数重发一次（llm.py）。"""
import logging
import re

from .config import settings

log = logging.getLogger(__name__)

# 认识的档位（OpenAI / LiteLLM 的 reasoning_effort 取值，Codex ReasoningEffort 的子集），顺序 = 从少到多
EFFORTS: dict[str, tuple[str, str]] = {
    "minimal": ("最少", "几乎不想，最快"),
    "low": ("低", "想得少，回得快"),
    "medium": ("中", "速度和深度兼顾"),
    "high": ("高", "难题想得更深，更慢也更费 token"),
    "xhigh": ("极高", "最难的问题才用，很慢很费 token"),
}
PARAM = "reasoning_effort"  # Chat Completions 的字段名；LiteLLM 会翻成各家的 thinking 预算


class ReasoningConfigError(ValueError):
    """MODEL_REASONING 写错了：启动时就报，别等用户点到才发现。"""


def _parse(raw: dict) -> dict[str, tuple[tuple[str, ...], str]]:
    out: dict[str, tuple[tuple[str, ...], str]] = {}
    for alias, spec in (raw or {}).items():
        if isinstance(spec, (list, tuple)):
            levels, default = list(spec), None
        elif isinstance(spec, dict):
            levels, default = list(spec.get("levels") or []), spec.get("default")
        else:
            raise ReasoningConfigError(f"MODEL_REASONING.{alias} 要么是档位列表，要么是 {{levels, default}}")
        if not levels:
            raise ReasoningConfigError(f"MODEL_REASONING.{alias} 至少要一档")
        seen: set[str] = set()
        for lv in levels:
            if lv not in EFFORTS or lv in seen:
                raise ReasoningConfigError(f"MODEL_REASONING.{alias} 的档位 {lv!r} 不认识或重复了（可选 {', '.join(EFFORTS)}）")
            seen.add(lv)
        order = list(EFFORTS)
        if [order.index(x) for x in levels] != sorted(order.index(x) for x in levels):
            raise ReasoningConfigError(f"MODEL_REASONING.{alias} 的档位要从少到多排")
        if default is None:
            default = "medium" if "medium" in levels else levels[len(levels) // 2]
        if default not in seen:
            raise ReasoningConfigError(f"MODEL_REASONING.{alias} 的默认档 {default!r} 不在 levels 里")
        out[alias] = (tuple(levels), default)
    return out


_table = _parse(settings.model_reasoning)
_unsupported: set[str] = set()  # 供应商明确不认这个参数的别名（本进程内记住，重启再试）


def reload() -> None:
    """测试 / 改了 settings 之后重读。"""
    global _table
    _table = _parse(settings.model_reasoning)
    _unsupported.clear()


def levels(alias: str) -> tuple[str, ...]:
    """这个别名能选的档（从少到多）；空 = 不能调。"""
    if alias in _unsupported:
        return ()
    return _table.get(alias, ((), ""))[0]


def default_for(alias: str) -> str | None:
    return _table[alias][1] if levels(alias) else None


def valid(choice: object) -> bool:
    """存到对话上的值合不合法（只看认不认识，不看当前模型有没有——换模型后可能又有了）。"""
    return isinstance(choice, str) and choice in EFFORTS


def resolve(alias: str, choice: str | None) -> str | None:
    """对话的选择 → 这次实际发的档：能调且选了它有的档 → 那档；否则 → 默认；不能调 → None（不发参数）。"""
    lv = levels(alias)
    if not lv:
        return None
    return choice if choice in lv else _table[alias][1]


def for_helper(alias: str) -> str | None:
    """后台小活（摘要 / 记忆整理 / 看图描述）：最低一档，省 token。"""
    lv = levels(alias)
    return lv[0] if lv else None


def kwargs(effort: str | None) -> dict:
    return {PARAM: effort} if effort else {}


_REJECT_PARAM = re.compile(r"reasoning[_ ]?effort|\breasoning\b|thinking", re.I)
_REJECT_WORD = re.compile(r"unsupported|not support|unknown|unrecogni[sz]ed|invalid|extra|not (?:permitted|allowed)|"
                          r"does not accept|不支持|无效|未知", re.I)


def rejected(e: BaseException) -> bool:
    """这个错误是不是“供应商不认 reasoning_effort”：400/422 且错误文字里同时提到参数名和拒绝词。"""
    status = getattr(e, "status_code", None)
    if status not in (400, 422):
        return False
    body = getattr(e, "body", None)
    text = f"{e} {body or ''}"
    return bool(_REJECT_PARAM.search(text) and _REJECT_WORD.search(text))


def mark_unsupported(alias: str) -> None:
    if alias not in _unsupported:
        log.warning("模型 %s 不接受 %s，本进程内不再发", alias, PARAM)
    _unsupported.add(alias)


def catalog(alias: str) -> dict:
    """GET /api/catalog/models 里每个模型多带的两项：efforts（可选档，从少到多）+ effort（默认）。不能调 → 空。"""
    lv = levels(alias)
    if not lv:
        return {}
    return {"efforts": [{"id": x, "label": EFFORTS[x][0], "description": EFFORTS[x][1]} for x in lv],
            "effort": _table[alias][1]}
