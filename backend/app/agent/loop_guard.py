# Copyright 2025 Google LLC
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
#
# Ported from google-gemini/gemini-cli packages/core/src/services/loopDetectionService.ts (Apache-2.0), modified:
#   checkToolCallLoop（周期 1..5、各重复 5 次）、checkContentLoop / truncateAndUpdate / analyzeContentChunksForLoop /
#   isLoopDetectedForChunk（50 字块滑窗、10 次、平均间距 ≤ 5 块、周期种类 ≤ 5、代码块/表格/列表/标题/引用/分隔线重置）、
#   “第一次提醒、第二次停下”（client.ts _recoverFromLoop / clearDetection）原样翻译为 Python。
# 修改：①工具调用的指纹 = 工具名 + 参数（键排序后的 JSON）+ 结果原文——Gemini 自己的 LLM 判官把“循环”定义为
#       参数相同且结果相同；把结果算进去，轮询后台任务（每次有新输出）、等页面加载这类“调用一样但有进展”的不再误判；
#       代价是在执行之后才判断（第 5 次已经执行过）。②不做 LLM 判官（每 10 步多一次模型调用，费 token）。
#       ③recovered() 时清掉文字计数（见该方法）；分隔线正则修掉原版字符区间的缺陷（见 _DIVIDER）；④telemetry、按会话关闭、配置开关不需要，去掉。
"""一轮回复里的“原地打转”检测（唯一入口）：同样的工具调用得到同样的结果反复出现，或者回复文字在复读。

用法（loop.py）：每个文字片段 content(text)、每次工具调用结束 tool(name, args, result)；返回非 0 = 检测到，
数值是这一轮第几次检测到。第一次：给模型一条提醒，清掉标记（recovered）继续；第二次：停下，告诉用户。
"""
import hashlib
import json
import re

TOOL_CALL_LOOP_THRESHOLD = 5
CONTENT_LOOP_THRESHOLD = 10
CONTENT_CHUNK_SIZE = 50
MAX_HISTORY_LENGTH = 5000

_TABLE = re.compile(r"(^|\n)\s*(\|.*\||[|+\-]{3,})")
_LIST = (re.compile(r"(^|\n)\s*[*\-+]\s"), re.compile(r"(^|\n)\s*\d+\.\s"))
_HEADING = re.compile(r"(^|\n)#+\s")
_QUOTE = re.compile(r"(^|\n)>\s")
# JS 原式 /^[+-_=*\u2500-\u257F]+$/ 里 "+-_" 成了 + 到 _ 的区间（数字、大写字母都算“分隔线”，"OK"、"2026" 这样的
# 片段会被跳过不计）——这是原版的缺陷，这里把 - 转义，只认真正的分隔线字符
_DIVIDER = re.compile(r"^[+\-_=*\u2500-\u257F]+$")


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "surrogatepass")).hexdigest()


def tool_key(name: str, args: object, result: str = "") -> str:
    try:
        a = json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        a = repr(args)
    return _hash(f"{name}:{a}\n{result}")


class LoopGuard:
    def __init__(self) -> None:
        self.tool_history: list[str] = []
        self.stream = ""
        self.stats: dict[str, list[int]] = {}
        self.last_index = 0
        self.in_code = False
        self.detected = False
        self.count = 0
        self.kind = ""    # tool | content
        self.detail = ""

    # —— 公共入口 ——
    def tool(self, name: str, args: object, result: str = "") -> int:
        if self.detected:
            return self.count
        self.reset_content()  # 复读只发生在同一段文字里：中间有工具调用就重新计
        if self._tool_loop(tool_key(name, args, result)):
            a = json.dumps(args, ensure_ascii=False)[:200]
            return self._hit("tool", f"重复调用 {name}，参数 {a}，结果每次都一样")
        return 0

    def content(self, text: str) -> int:
        if self.detected:
            return self.count
        if self._content_loop(text):
            start = max(0, self.last_index - 20)
            snippet = self.stream[start:self.last_index + CONTENT_CHUNK_SIZE].strip()
            return self._hit("content", f"回复文字在重复：“{snippet}…”")
        return 0

    def recovered(self) -> None:
        """第一次检测到、已经提醒过模型：放行下一步，但次数保留（再检测到就是第 2 次）。
        文字计数清零：提醒之后模型的下一次回复是新的一段话（原版不清，滑窗会接着处理被掐断前的复读文字，
        模型改口说的第一句就又被判成复读）。"""
        self.detected = False
        self.reset_content()

    def reset_content(self) -> None:
        self.stream = ""
        self.stats.clear()
        self.last_index = 0

    # —— 以下照 Gemini 翻译 ——
    def _hit(self, kind: str, detail: str) -> int:
        self.detected, self.kind, self.detail = True, kind, detail
        self.count += 1
        return self.count

    def _tool_loop(self, key: str) -> bool:
        self.tool_history.append(key)
        R = TOOL_CALL_LOOP_THRESHOLD
        if len(self.tool_history) > 5 * R:
            self.tool_history = self.tool_history[-5 * R:]
        h, n = self.tool_history, len(self.tool_history)
        for k in range(1, 6):  # 周期长度 1..5，最近 k*R 个调用按周期 k 重复
            need = k * R
            if n < need:
                continue
            cycle = h[-k:]
            if all(h[n - need + i] == cycle[i % k] for i in range(need)):
                return True
        return False

    def _content_loop(self, content: str) -> bool:
        fences = content.count("```")
        divider = bool(_DIVIDER.match(content))
        if fences or _TABLE.search(content) or any(p.search(content) for p in _LIST) \
                or _HEADING.search(content) or _QUOTE.search(content) or divider:
            self.reset_content()  # 换了一种排版元素：不跨元素分析
        was = self.in_code
        if fences % 2:
            self.in_code = not self.in_code
        if was or self.in_code or divider:
            return False
        self.stream += content
        self._truncate()
        return self._analyze()

    def _truncate(self) -> None:
        if len(self.stream) <= MAX_HISTORY_LENGTH:
            return
        cut = len(self.stream) - MAX_HISTORY_LENGTH
        self.stream = self.stream[cut:]
        self.last_index = max(0, self.last_index - cut)
        for h in list(self.stats):
            kept = [i - cut for i in self.stats[h] if i - cut >= 0]
            if kept:
                self.stats[h] = kept
            else:
                del self.stats[h]

    def _analyze(self) -> bool:
        while self.last_index + CONTENT_CHUNK_SIZE <= len(self.stream):
            chunk = self.stream[self.last_index:self.last_index + CONTENT_CHUNK_SIZE]
            if self._chunk_loops(chunk, _hash(chunk)):
                return True
            self.last_index += 1
        return False

    def _chunk_loops(self, chunk: str, h: str) -> bool:
        seen = self.stats.get(h)
        if seen is None:
            self.stats[h] = [self.last_index]
            return False
        if self.stream[seen[0]:seen[0] + CONTENT_CHUNK_SIZE] != chunk:  # 哈希碰撞
            return False
        seen.append(self.last_index)
        if len(seen) < CONTENT_LOOP_THRESHOLD:
            return False
        recent = seen[-CONTENT_LOOP_THRESHOLD:]
        if (recent[-1] - recent[0]) / (CONTENT_LOOP_THRESHOLD - 1) > CONTENT_CHUNK_SIZE * 5:
            return False
        # 真复读：两次出现之间的那段（周期）种类很少；种类多 = 只是共用前缀的列表
        periods = {self.stream[recent[i]:recent[i + 1]] for i in range(len(recent) - 1)}
        return len(periods) <= CONTENT_LOOP_THRESHOLD // 2


def nudge(detail: str) -> str:
    """第一次检测到时给模型的提醒（Gemini _recoverFromLoop 的 feedbackText，译成中文）。"""
    return (f"[系统提示] 可能在原地打转：{detail}。请先停一下，确认自己是否在推进。如果没有，回顾之前的操作，"
            "换一种思路解决；不要再重复同样的工具调用或同样的话。")


STOP_NOTE = "（我好像在原地打转，先停在这里，免得白白耗用量。可以告诉我换个思路，或者补充一点信息再让我继续。）"
