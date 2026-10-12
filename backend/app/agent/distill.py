# Copyright 2026 Google LLC
# SPDX-License-Identifier: Apache-2.0
#
# Ported from google-gemini/gemini-cli packages/core/src/context/toolDistillationService.ts (Apache-2.0), modified:
# - 只对“日志型”工具（命令、主机命令、后台任务、接口、MCP）生效，读文件 / 网页 / 浏览器另有分页或快照规则；
# - 先在本地从“被省略的中间段”挑信号行（报错、失败、退出码、文件:行号、测试计数），零调用就能补上首尾截断看不到的报错；
# - 只有全文很大（settings.tool_distill_chars，默认 80k 字 ≈ Gemini summarizationThresholdTokens 20k）且模式为 auto 时，
#   才把 开头 + 信号行 + 结尾（≤ INPUT_MAX）交给便宜模型（summary_model）摘要，提示词照 Gemini 原文翻译；
#   超过 MAX_SOURCE（Gemini MAX_DISTILLATION_SIZE 1,000,000）不调模型；模型失败 / 超时 → 退回信号行（Gemini 退回无）；
# - 结果总长仍严格 ≤ 上限：先给摘录预留位置再截断（Gemini 是截完再追加，可能超）。
"""超长工具输出的“要点摘录”：首尾截断之外，把中间段里的报错 / 结论补给模型。

一条规则（只在这里）：
- 只管 TOOLS 里的工具，且只在结果确实被截断（或沙盒已截断并落盘）时动作；
- 信号行只取被省略的中间段（首尾模型已看到），每行带全文字符位置，模型可以 read_file offset=… 回去看；
- 模型摘要只在 auto 且全文 ≥ settings.tool_distill_chars、≤ MAX_SOURCE 时调用一次，失败就用信号行；
- 摘录放在截断结果末尾，结果总长 ≤ limit。settings.tool_distill = auto | rules | off。
"""
from __future__ import annotations

import asyncio
import logging
import re

from .. import llm, spill
from ..config import settings
from ..storage import project_dir

log = logging.getLogger(__name__)

TOOLS = {"run_command", "host_command", "job_status", "api_request", "mcp_call"}
MODES = ("auto", "rules", "off")
RESERVE = 1800        # 截断时给摘录预留的字数
SIGNAL_LINES = 30     # 信号行最多几行（前 1/3 + 后 2/3：报错多在后面）
LINE_MAX = 200        # 单行最多字数
INPUT_MAX = 24_000    # 交给模型的最大字数（开头 + 信号行 + 结尾）
SUMMARY_MAX = 1200    # 模型摘要最多保留字数
MAX_SOURCE = 1_000_000  # Gemini MAX_DISTILLATION_SIZE：更大不调模型
SCAN_MAX = 8_000_000  # 落盘全文超过这么多字节不读回来（只用结果里已有的部分）
TIMEOUT_S = 15        # Gemini 15 s
HEAD = "\n\n— 中间段里的要点（{how}）—\n"

SIGNAL_RE = re.compile(
    r"error|\berr\b|fail(?:ed|ure|s)?\b|exception|traceback|fatal|panic|warn(?:ing)?\b|denied|refused|not found|"
    r"no such file|cannot|can't|unable|undefined|segmentation|killed|out of memory|\boom\b|timed? ?out|"
    r"exit (?:code|status)|returned non-zero|\b\d+ (?:passed|failed|errors?|warnings?|tests?)\b|"
    r"错误|失败|异常|警告|拒绝|找不到|不存在|超时|"
    r"[\w./-]+\.\w{1,6}:\d+",
    re.IGNORECASE)

PROMPT = """工具 {tool} 的输出很长，已被截断。从下面的输出里提取最关键的事实，让主助手不丢失上下文。
只关注具体数据：
1. 原样的报错信息、异常类型或退出码；
2. 提到的具体文件路径或行号；
3. 明确的结果（比如“编译成功”“3 个测试失败”）。
不要揣测意图。不超过 10 行，必要时原样引用。

输出（开头、中间挑出的行、结尾）：
{body}"""


def mode() -> str:
    m = (settings.tool_distill or "").strip().lower()
    return m if m in MODES else "auto"


def signals(full: str, start: int, end: int) -> list[str]:
    """full[start:end]（被省略的中间段）里的信号行：'@字符位置 行'；相同的行合并成 ×N；超量保留前 1/3 + 后 2/3。"""
    out: list[str] = []
    seen: dict[str, int] = {}
    pos = start
    if start > 0 and full[start - 1] != "\n":  # 中间段从行中间开始：跳到下一行
        nl = full.find("\n", start)
        pos = end if nl < 0 else nl + 1
    while pos < end:
        nl = full.find("\n", pos, end)
        stop = end if nl < 0 else nl
        line = full[pos:stop].strip()
        if line and SIGNAL_RE.search(line):
            key = line[:LINE_MAX]
            if key in seen:
                seen[key] += 1
            else:
                seen[key] = 1
                out.append((pos, key))
        pos = stop + 1
    lines = [f"@{p} {k}" + (f"（×{seen[k]}）" if seen[k] > 1 else "") for p, k in out]
    if len(lines) > SIGNAL_LINES:
        a = SIGNAL_LINES // 3
        b = SIGNAL_LINES - a
        lines = lines[:a] + [f"…（还有 {len(lines) - SIGNAL_LINES} 行类似的）…"] + lines[-b:]
    return lines


def excerpt(lines: list[str], budget: int) -> str:
    """信号行拼成摘录，整行放不下就停。"""
    out, used = [], 0
    for ln in lines:
        if used + len(ln) + 1 > budget:
            break
        out.append(ln)
        used += len(ln) + 1
    return "\n".join(out)


def model_input(full: str, lines: list[str]) -> str:
    """开头 1/6 + 信号行 + 结尾，总长 ≤ INPUT_MAX。"""
    sig = "\n".join(lines)[: INPUT_MAX // 3]
    room = INPUT_MAX - len(sig) - 20
    head, tail = full[: room // 3], full[-(room - room // 3):] if room > 0 else ""
    return f"{head}\n…\n{sig}\n…\n{tail}"


async def summarize(tool: str, full: str, lines: list[str]) -> str | None:
    try:
        raw = await asyncio.wait_for(llm.complete([
            {"role": "user", "content": PROMPT.format(tool=tool, body=model_input(full, lines))},
        ], settings.summary_model, kind="distill", max_tokens=500), TIMEOUT_S)
    except Exception as e:  # noqa: BLE001 —— 摘要只是锦上添花（Gemini 同）
        log.warning("tool output distill failed: %s", e)
        return None
    text = (raw or "").strip()
    return text[:SUMMARY_MAX] if text else None


def _full(content: str, workspace: str | None) -> tuple[str, int, int] | None:
    """(全文, 中间段起点, 中间段终点)：结果里已有落盘说明 → 读回落盘全文；否则就是 content 本身（中间段待截断后定）。"""
    loc = spill.located(content)
    if loc is None:
        return None
    start, end, path, total = loc
    if not workspace:
        return None
    try:
        p = project_dir(workspace) / path
        if p.stat().st_size > SCAN_MAX:
            return None
        full = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    tail = len(content) - end
    return full, min(start, len(full)), max(min(start, len(full)), len(full) - tail)


async def bound(content: str, limit: int, workspace: str | None, tool: str, db=None) -> str:
    """spill.bound 的增强版：日志型工具的超长输出，末尾补上中间段的要点。其它情况与 spill.bound 完全一样。"""
    m = mode()
    if m == "off" or tool not in TOOLS or limit <= RESERVE * 2:
        return spill.bound(content, limit, workspace, tool)
    prior = _full(content, workspace)
    if prior is None and len(content) <= limit:
        return content  # 没截断、也没落过盘：什么都不做
    if prior is not None:  # 沙盒已截断并落盘：结果是 首 + 说明 + 尾
        full, start, end = prior
        body = content if len(content) <= limit - RESERVE else spill.bound(content, limit - RESERVE, workspace, tool)
    else:  # 我们来截：先预留摘录位置
        full = content
        body = spill.bound(content, limit - RESERVE, workspace, tool)
        loc = spill.located(body)
        if loc is None:  # 说明都放不下等极端情况：照旧（不再存第二份）
            return body
        start, end = loc[0], len(full) - (len(body) - loc[1])
    lines = signals(full, start, end)
    text, how = None, "本地挑出的报错 / 结论行，@ 后是全文字符位置"
    if m == "auto" and settings.tool_distill_chars and settings.tool_distill_chars <= len(full) <= MAX_SOURCE:
        if db is not None:
            try:
                await db.commit()  # SQLite：工具的写入先提交，再调模型（记账另开连接）
            except Exception:  # noqa: BLE001
                pass
        if (s := await summarize(tool, full, lines)) is not None:
            text, how = s, "便宜模型从全文摘的"
    if text is None:
        if not lines:
            return body
        text = excerpt(lines, RESERVE - len(HEAD) - 40)
    out = body + HEAD.format(how=how) + text
    return out if len(out) <= limit else out[:limit]
