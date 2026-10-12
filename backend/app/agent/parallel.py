# Ported from deepseek-harness/packages/core/agent-loop/src/tool-calls.ts and
# deepseek-harness/packages/core/tools/src/index.ts (executionMode) (MIT), modified.
# Copyright (c) 2026 DeepSeek — MIT License, see assistant/NOTICE.
"""同一步里多个工具调用的并行调度：唯一规则在这里（loop.run 只管把结果按模型顺序放回）。

移植自 deepseek-harness 的 tool-calls 调度器：
- 失败即独占（fail-closed）：只有工具明确声明 parallel（或它的判定函数对这次参数返回 True）才并行；
  不认识的工具、参数解析不了、要审批 / 表单 / 授权选项的、控制类（quiet）工具、判定函数抛错 —— 一律独占。
- 连续的可并行调用组成一组，独占调用自成一道“屏障”：前面的组全部结束，它才开始，它结束后面的才开始。
- 组内滚动池：同时最多 settings.agent_parallel_tools 个（deepseek 默认 10，我们 4G 小机器取 8；≤1 = 关）。
- 事件随到随交（时间线上几步同时亮），结果由调用方按模型顺序提交（工具结果顺序 = assistant tool_calls 顺序）。
- 被取消（用户点停止）：已开始的一起取消，调用方照旧用 steps(stopped=True) / trace() 收尾。
嫁接：Codex 的系统提示“能并行就并行，尤其是读文件”（PROMPT）；没取 Gemini 的“默认都并行、只排除编辑类”（fail-open）。
"""
import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import aclosing
from dataclasses import dataclass, replace

from ..config import settings
from .tool_args import Parsed
from .tools import REGISTRY, Tool, ToolContext, ToolResult

PROMPT = ("互不依赖的只读查询（read_file、list_files、glob、grep、web_search、web_fetch）可以在同一步里一起发，"
          "它们会同时执行，比一个个来快得多；有先后依赖的（要先看结果才知道下一步）照常分步。")


def limit() -> int:
    """组内最多同时跑几个；≤1 = 不并行（每个调用都独占）。"""
    return max(1, int(settings.agent_parallel_tools or 1))


def prompt() -> str:
    return PROMPT if limit() > 1 else ""


def mode(t: Tool | None, args: object) -> bool:
    """这一次调用能不能并行（deepseek executionMode：只有确切的 True 才算，其余一律独占）。"""
    if t is None or not isinstance(args, dict) or t.risk or t.form or t.quiet or t.grants:
        return False
    p = t.parallel
    if p is True:
        return True
    if callable(p):
        try:
            return p(args) is True
        except Exception:
            return False
    return False


def eligible(name: str, parsed: Parsed | None, ctx: ToolContext) -> bool:
    t = REGISTRY.get(name)
    if t is None or not t.available(ctx) or parsed is None:
        return False
    return mode(t, parsed.args)


def groups(flags: list[bool]) -> list[list[int]]:
    """按模型顺序切组：连续可并行的成一组；独占的一个一组。并行关掉时每个都独占。"""
    out: list[list[int]] = []
    on = limit() > 1
    for i, f in enumerate(flags):
        if on and f and out and flags[out[-1][-1]]:  # 组里只会全是可并行的（独占的自成一组）
            out[-1].append(i)
        else:
            out.append([i])
    return out


def isolated(ctx: ToolContext) -> ToolContext:
    """并行时每个调用一份浅拷贝的 ctx：ctx.live 由内核在执行期间挂上，几个调用共用一个会互相覆盖。
    并行工具不碰 ctx.db（共用的 AsyncSession 不能并发），这是声明 parallel 的前提。"""
    return replace(ctx)


@dataclass
class Settled:
    """组内第 index 个调用结束了（index 是组内下标）。"""
    index: int
    result: ToolResult


@dataclass
class _Failed:
    index: int
    error: BaseException


async def pool(n: int, start: Callable[[int], AsyncIterator], cap: int | None = None) -> AsyncIterator:
    """滚动池跑 n 个调用：start(k) 返回一个事件生成器，最后一个是 ToolResult。
    逐个交出中间事件；某个调用结束交出 Settled(k, result)。工具自身的异常已由 _call_tool 变成结果，
    这里再出异常（内核 bug）就取消其余、原样抛出（deepseek：调度失败先排空已开始的，再拒绝）。"""
    cap = cap or limit()
    q: asyncio.Queue = asyncio.Queue()

    async def worker(k: int) -> None:
        try:
            result = ToolResult("")
            async with aclosing(start(k)) as events:
                async for ev in events:
                    if isinstance(ev, ToolResult):
                        result = ev
                    else:
                        q.put_nowait(ev)
            q.put_nowait(Settled(k, result))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — 交给消费方抛出
            q.put_nowait(_Failed(k, e))

    running: dict[int, asyncio.Task] = {}
    nxt = done = 0
    try:
        while done < n:
            while nxt < n and len(running) < cap:
                running[nxt] = asyncio.create_task(worker(nxt))
                nxt += 1
            item = await q.get()
            if isinstance(item, Settled):
                running.pop(item.index, None)
                done += 1
                yield item
            elif isinstance(item, _Failed):
                running.pop(item.index, None)
                raise item.error
            else:
                yield item
    finally:
        for task in running.values():
            task.cancel()
        if running:
            await asyncio.gather(*running.values(), return_exceptions=True)
