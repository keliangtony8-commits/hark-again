# 思路取自 openai/codex codex-rs/core/src/tools/handlers/tool_search.rs + tool_search_spec.rs（Apache-2.0）：
#   “不常用的工具不预先给模型，用一个工具去发现它们”。没有逐行移植：Codex 搜到后把工具塞进下一次请求的 tools，
#   会让工具段每次变、提示缓存失效；这里换成目录 + describe + call（工具段逐字不变），搜索用简单的词命中排序代替 BM25
#   （按需工具只有十来个）。见 docs/core-research.md BRAIN (ar)。
"""按需加载的工具：唯一入口（哪些不进工具列表、目录怎么写、call 怎么拆成真正的调用，都只在这里）。

每次调模型都要把全部工具的说明和参数发一遍（六十多个 ≈ 1.2 万 token）。很少用到的工具（读视频字幕、Home 建议卡、
分享对话、发布网页……）标 deferred=True：不进工具列表，只在 deferred_tool 的说明里占一行目录。模型要用时
  - list：列出 / 按关键词找按需工具；
  - describe：看某个工具的完整说明和参数；
  - call：tool + arguments 直接调用。
call 在 loop 里先拆成对那个工具的普通调用（unwrap）：审批卡、表单、计划模式、子助手白名单、并行、时间线、参数校验全都照旧，
跟模型直接调它没有区别；模型照系统提示 / 技能里的名字直接调按需工具也照常执行。
工具段对同一段对话逐字不变（目录按注册顺序、只随可用范围变），提示缓存照样命中。
"""
from __future__ import annotations

import json
import re

from ..config import settings
from ..llm import ToolCall
from . import tool_args
from .tools import DEFERRED_META as META
from .tools import REGISTRY, Tool, ToolContext, ToolResult, tool

ACTIONS = ("list", "describe", "call")
SUMMARY_MAX = 60     # 目录里每个工具一行说明的长度上限（字）
LIST_MAX = 30        # list 最多列几个（按需工具本来就少，防目录失控）
_SENTENCE = re.compile(r"[。！？!?\n]|\.\s")


def enabled() -> bool:
    return settings.defer_tools


def deferred(t: Tool) -> bool:
    """这个工具现在是不是按需（开关关掉 = 全部直接给模型）。"""
    return t.deferred and enabled()


def visible(ctx: ToolContext) -> list[Tool]:
    """当前上下文能用的按需工具，按注册顺序（= 模块名顺序，固定）。"""
    return [t for t in REGISTRY.values() if deferred(t) and t.available(ctx)]


def listed(t: Tool, ctx: ToolContext) -> bool:
    """t 要不要进这次请求的工具列表。"""
    if t.name == META:
        return enabled() and t.available(ctx)
    return t.available(ctx) and not deferred(t)


def summary(t: Tool) -> str:
    """目录里的一行：说明的第一句，太长截断。"""
    text = " ".join(t.description.split())
    m = _SENTENCE.search(text)
    first = text[:m.start()] if m else text
    first = first.strip(" ：:；;，,") or t.label
    return first if len(first) <= SUMMARY_MAX else first[:SUMMARY_MAX] + "…"


def catalog(tools: list[Tool]) -> str:
    return "\n".join(f"- {t.name}：{summary(t)}" for t in tools)


def description(ctx: ToolContext) -> str:
    """deferred_tool 的说明（含目录）：同一段对话里逐字不变。"""
    return (
        "按需工具的入口：下面这些工具没有放进工具列表（省 token），要用时通过本工具调用。"
        "系统提示或技能里提到、但工具列表里找不到的工具就在这里。\n"
        "- action=list：列出按需工具（可给 query 关键词筛选）；\n"
        "- action=describe + tool：看它的完整说明和参数——第一次用某个工具先 describe；\n"
        "- action=call + tool + arguments（对象，按 describe 给的参数写）：调用它，结果、审批卡、表单都和直接调用一样。"
        "已经知道参数（同一段对话里 describe 过、技能里写明了）就直接 call。\n"
        "按需工具：\n" + catalog(visible(ctx))
    )


def _find(name: str, ctx: ToolContext) -> Tool | None:
    t = REGISTRY.get(name.strip())
    if t is None or t.name == META or not t.available(ctx):
        return None
    return t


def unwrap(call: ToolCall, parsed: tool_args.Parsed, ctx: ToolContext) -> tuple[ToolCall, tool_args.Parsed] | None:
    """deferred_tool(action=call, tool=X, arguments=…) → 对 X 的普通调用（同一个 call id，结果照样对上这条调用）。
    拆不了（不是 call、工具不存在 / 不可用、arguments 不是对象）→ None：交给 deferred_tool 自己回话。
    arguments 写坏了照样拆：由 X 的参数解析报错（带完整参数签名），和直接调用 X 写错一样计数。"""
    if call.name != META or parsed.args is None or parsed.args.get("action") != "call":
        return None
    t = _find(str(parsed.args.get("tool") or ""), ctx)
    if t is None:
        return None
    inner = parsed.args.get("arguments")
    if inner is None:
        raw = "{}"
    elif isinstance(inner, dict):
        raw = json.dumps(inner, ensure_ascii=False)
    elif isinstance(inner, str):
        raw = inner  # 有的模型把对象再编码成字符串
    else:
        return None
    return ToolCall(call.id, t.name, raw), tool_args.parse(raw)


def _terms(query: str) -> list[str]:
    return [w for w in re.split(r"[\s,，、;；/]+", query.lower()) if w]


def search(tools: list[Tool], query: str) -> list[Tool]:
    """按关键词命中数排序（名字命中算两次）；一个都没命中 → 全部（目录本来就短，宁可多给）。"""
    terms = _terms(query)
    if not terms:
        return tools
    scored = []
    for i, t in enumerate(tools):
        name, body = t.name.lower(), f"{t.label} {t.description}".lower()
        score = sum(2 * (w in name) + (w in body) for w in terms)
        if score:
            scored.append((-score, i, t))
    return [t for _, _, t in sorted(scored)] or tools


def describe(t: Tool) -> str:
    schema = json.dumps(t.parameters, ensure_ascii=False, separators=(",", ":"))
    return (f"{t.name}（{t.label}）\n{t.description}\n\n参数（JSON Schema）：{schema}\n\n"
            f"调用：deferred_tool(action=\"call\", tool=\"{t.name}\", arguments={{…}})")


def signature(t: Tool) -> str:
    """按需工具参数写错时附上的完整签名（模型多半没 describe 过，第一次就给，不等连错三次）。"""
    return "\n" + tool_args.signature(t.name, t.parameters)


@tool(
    META, "查看可用工具",
    "（说明在请求里按当前可用的按需工具生成：agent/deferred.description）",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(ACTIONS), "description": "list / describe / call"},
            "tool": {"type": "string", "description": "describe、call 必填：工具名"},
            # 不写 type：写错类型时由这里回“要是对象”+ 完整说明，而不是通用的类型报错
            "arguments": {"description": "call 用：传给该工具的参数对象（JSON object）"},
            "query": {"type": "string", "description": "list 可选：关键词，筛出相关的按需工具"},
        },
        "required": ["action"],
    },
    quiet=True, parallel=True,
)
async def deferred_tool(ctx: ToolContext, action: str, tool: str = "", arguments: object = None,
                        query: str = "") -> ToolResult:
    tools = visible(ctx)
    if action == "list":
        found = search(tools, query)
        more = f"\n（还有 {len(found) - LIST_MAX} 个没列出，换个关键词）" if len(found) > LIST_MAX else ""
        if not found:
            return ToolResult("现在没有可用的按需工具。")
        return ToolResult("按需工具（用 describe 看参数，call 调用）：\n" + catalog(found[:LIST_MAX]) + more)
    if action not in ACTIONS:
        return ToolResult(f"action 只能是 {' / '.join(ACTIONS)}。", failed="action 不对")
    if not tool.strip():
        return ToolResult(f"action={action} 要给 tool（工具名）。", failed="缺工具名")
    t = _find(tool, ctx)
    if t is None:
        names = [x.name for x in tools]
        hint = tool_args.suggest(tool.strip(), names)
        return ToolResult(f"没有可用的工具 {tool.strip()}。{hint}".rstrip() + "\n可用的按需工具：\n" + catalog(tools),
                          failed="没有这个工具")
    if action == "describe":
        return ToolResult(describe(t))
    # 走到这里的 call 都是拆不了的（拆得了的已经在 loop 里变成对 t 的调用）：只剩 arguments 类型不对
    return ToolResult(f"arguments 要是参数对象（JSON object），例如 {{\"url\": \"…\"}}。\n" + describe(t),
                      failed="arguments 不是对象")
