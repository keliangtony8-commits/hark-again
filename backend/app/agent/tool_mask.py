# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
#
# Ported from google-gemini/gemini-cli packages/core/src/context/toolOutputMaskingService.ts (Apache-2.0), modified:
#   "Hybrid Backward Scanned FIFO" translated to Python over OpenAI-style messages.
# 修改：①阈值按我们 128k 窗口缩小（Gemini 50k 保护 + 30k 起批 → 24k + 12k，可配）；②“最新一轮”= 最新一批
#       工具结果（带 tool_calls 的最后一条助手消息之后）；③全文落进工作区 .spill/（spill.save，与长输出同一处、
#       同一套清理），结果里已有落盘说明就沿用那个文件不再存一份；存不下就不遮（绝不丢内容）；
#       ④豁免：use_skill / ask_user / update_plan / delegate，以及 browser_*（旧快照归 supersede.py 管）；
#       ⑤run_command 的预览保留第一行状态（退出码 / 超时），其余首尾各 10 行；单行过长再按字符首尾截（Gemini 只按行）；
#       ⑥说明文字中文，标签 <tool_output_masked> 沿用。
"""一轮里较早的大块工具结果 → 预览 + 全文文件路径（唯一入口）。

长任务里每一步都把前面所有工具结果重新发给模型：几十步命令输出、网页正文、文件内容叠起来，
既费钱也让模型在一堆旧输出里找不到重点。loop 在每次调模型前调用 mask()：从最新往回数，
最新一批工具结果和最近 PROTECT_TOKENS 的工具输出原样保留；更早的累计超过 MIN_TOKENS 才成批
换成“预览 + 全文在 .spill/xxx.txt”——一次换一批，换过的不再变，提示缓存的前缀随后又稳定下来。
和 compact.py 的分工：这里无损（全文在文件里、随时 read_file），平时就做；compact 在上文快满时才剪 / 写摘要。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .. import spill
from ..config import settings
from .compact import approx_tokens

log = logging.getLogger(__name__)

TAG = "tool_output_masked"  # Gemini MASKING_INDICATOR_TAG
EXEMPT = {"use_skill", "ask_user", "update_plan", "delegate"}  # 结果本身就是要点（Gemini EXEMPT_TOOLS）
EXEMPT_PREFIX = ("browser_",)  # 页面快照由 supersede.py 只留最新一份
SHELL = {"run_command", "host_command"}
GENERIC_HEAD = GENERIC_TAIL = 250   # Gemini：普通工具首尾各 250 字
LINES_HEAD = LINES_TAIL = 10        # Gemini formatSimplePreview：首尾各 10 行
LINE_PREVIEW_MAX = 2000             # 我们加的：行预览本身还太长（压缩过的 JS、一整行 JSON）→ 再按字符截
# 存盘前估算省多少用的样例路径：spill.save 的最长文件名（时间戳 + 40 字工具名 + 4 位随机）
_PATH_SAMPLE = f"{spill.SPILL_DIR}/20260101-000000-{'x' * 47}-0000.txt"


@dataclass
class Result:
    masked: int = 0
    saved: int = 0  # 省下的 token（估算）


def enabled() -> bool:
    return settings.tool_mask_protect_tokens >= 0 and settings.tool_mask_min_tokens > 0


def is_masked(content: str) -> bool:
    return f"<{TAG}" in content


def exempt(name: str) -> bool:
    return name in EXEMPT or name.startswith(EXEMPT_PREFIX)


def _chars(text: str, head: int, tail: int) -> str:
    if len(text) <= head + tail:
        return text
    return f"{text[:head]}\n…（截断）…\n{text[-tail:]}"


def simple_preview(text: str) -> str:
    """首尾各 10 行（Gemini formatSimplePreview），过长再按字符首尾截。"""
    lines = text.split("\n")
    if len(lines) > LINES_HEAD + LINES_TAIL:
        text = "\n".join(lines[:LINES_HEAD]) + f"\n\n…（省略 {len(lines) - LINES_HEAD - LINES_TAIL} 行）…\n\n" \
            + "\n".join(lines[-LINES_TAIL:])
    if len(text) > LINE_PREVIEW_MAX:
        text = _chars(text, LINE_PREVIEW_MAX // 2, LINE_PREVIEW_MAX // 2)
    return text


def preview(name: str, content: str) -> str:
    if name in SHELL:  # 第一行是“退出码 N / 超时被终止”：信号最强，整行保留（Gemini 保留 Exit Code 等小段）
        first, _, rest = content.partition("\n")
        return first + ("\n" + simple_preview(rest) if rest.strip() else "")
    return _chars(content, GENERIC_HEAD, GENERIC_TAIL)


def snippet(body: str, path: str, total: int) -> str:
    return (f"<{TAG}>\n{body}\n\n这份输出太长，已移出上文（全文 {total} 字符）；"
            f"完整内容在 {path}，需要时用 read_file path=\"{path}\" 分段读。\n</{TAG}>")


def _names(messages: list[dict]) -> dict[str, str]:
    """tool_call_id → 工具名（OpenAI 的工具结果消息不带名字，得从前面的助手消息里找）。"""
    out: dict[str, str] = {}
    for m in messages:
        if m.get("role") == "assistant":
            for c in m.get("tool_calls") or ():
                out[c.get("id") or ""] = (c.get("function") or {}).get("name") or ""
    return out


def _latest_batch(messages: list[dict]) -> int:
    """最新一批工具结果的起点（最后一条带 tool_calls 的助手消息之后）；没有 → len。"""
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            return i + 1
    return len(messages)


def mask(messages: list[dict], workspace: str | None, start: int = 0, protect: int | None = None,
         minimum: int | None = None, protect_latest: bool = True) -> Result:
    """原地替换条目（不改原 dict）。start = 这一轮自己的消息从哪开始（之前是历史：上一轮的工具记录已截短，
    每轮重建一次，遮它会每轮重复落盘）。protect / minimum = token；None = 读配置。"""
    if not messages or not workspace:
        return Result()
    protect = settings.tool_mask_protect_tokens if protect is None else protect
    minimum = settings.tool_mask_min_tokens if minimum is None else minimum
    names = _names(messages)
    stop = _latest_batch(messages) if protect_latest else len(messages)
    cumulative, boundary, prunable_total = 0, False, 0
    prunable: list[tuple[int, int, str]] = []  # (下标, token, 工具名)
    for i in range(stop - 1, max(start, 0) - 1, -1):  # 从新往旧扫（backward scan）
        m = messages[i]
        if m.get("role") != "tool" or not isinstance(m.get("content"), str):
            continue
        content = m["content"]
        name = names.get(m.get("tool_call_id") or "", "")
        if not content or exempt(name) or is_masked(content):
            continue
        tokens = approx_tokens(content)
        if not boundary:
            cumulative += tokens
            if cumulative > protect:  # 跨过保护线的这一条本身就可以遮
                boundary = True
                prunable_total += tokens
                prunable.append((i, tokens, name))
        else:
            prunable_total += tokens
            prunable.append((i, tokens, name))
    if prunable_total < minimum:  # 攒够一批才动（每动一次提示缓存就断一次）
        return Result()
    out = Result()
    for i, tokens, name in prunable:
        m = messages[i]
        content = m["content"]
        body = preview(name, content)
        prior = spill.existing(content)  # 落过盘：全文早在那个文件里，沿用
        path, total = prior if prior is not None else (_PATH_SAMPLE, len(content))
        if tokens - approx_tokens(snippet(body, path, total)) <= 0:  # 遮了反而更长（Gemini 同一检查）：先算再存，不白落盘
            continue
        if prior is None:
            try:
                path = spill.save(workspace, f"masked-{name or 'tool'}", content)
            except OSError as e:  # 存不下：这一条不遮，绝不丢内容
                log.warning("tool_mask: save failed: %s", e)
                continue
        new = snippet(body, path, total)
        saved = tokens - approx_tokens(new)
        messages[i] = {**m, "content": new}
        out.masked += 1
        out.saved += saved
    if out.masked:
        log.info("tool_mask: masked %d outputs, ~%d tokens saved", out.masked, out.saved)
    return out
