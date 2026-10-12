# Copyright 2025 Google LLC
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
#
# Ported from google-gemini/gemini-cli packages/core/src/utils/nextSpeakerChecker.ts (Apache-2.0), modified:
#   CHECK_PROMPT 的三条判定规则（模型说了马上要做的下一步 / 明显没说完 → model；以问题结尾 → user；说完了 → user）、
#   RESPONSE_SCHEMA {reasoning, next_speaker ∈ user|model}、“空的模型消息 → model”、判官出错或答非所问 → 不续（null）、
#   client.ts 的“判为 model 就补一句 Please continue. 再来一圈”原样翻译。
# 修改：①先过本地规则闸门（gate）：只有回复结尾像“说要做却没做”（接下来我…、让我…、冒号/省略号结尾）、被长度上限截断、
#       或用过工具之后一句话都没说，才可能续；以问句结尾、在请用户回复的不续。Gemini 每轮都问一次判官（所以默认关掉），
#       我们只在闸门打开时问，平常一轮零额外调用。②判官只看用户最后一问 + 这一步的回复（各自截断），不重放整段上文——
#       省 token；用最便宜的 summary_model、最低思考档。③每轮最多续 settings.next_speaker_max 次（Gemini 靠 MAX_TURNS 兜底）。
#       ④模式 settings.next_speaker_check：auto（闸门 + 判官）/ rules（闸门直接算数，零调用）/ off。⑤提示语改中文并说明“做完了就简短收尾”。
"""一轮回复“话说一半就停了”的检测（唯一入口）：模型说“接下来我去改配置”却没调用工具就结束了，
这时替用户补一句“继续”，让它接着做，而不是把半截回复交给用户。

用法（loop.py）：模型一步没有工具调用、本该结束时，await decide(turn_text, cut, used_tools, history, model)：
返回 True = 续一圈（loop 追加 assistant 文字 + CONTINUE 提示）；每轮次数由调用方按 limit() 计。
"""
import json
import logging
import re

from .. import llm
from ..config import settings

log = logging.getLogger(__name__)

MODES = ("auto", "rules", "off")

# Gemini client.ts: [{ text: 'Please continue.' }]，补上“做完了就收尾”免得它硬编下一步
CONTINUE = ("[系统提示] 你上一条说了接下来要做的事，但没有调用工具就停下了。请直接接着做（需要工具就调用）；"
            "如果其实已经全部做完，简短告诉用户结果即可，不要重复前面说过的话。")

CHECK_PROMPT = """只分析“助手的回复”这一段本身的内容和结构，判断接下来该谁说话：用户（user）还是助手自己（model）。
判定规则（按顺序套用）：
1. 助手继续：回复明确说了助手马上要做的下一步（例如“接下来我会……”“现在我去处理……”“下面开始分析……”，或者表明要调用工具但其实没调用），或者回复明显没说完（话说到一半、没有自然的结尾），则为 model。
2. 问用户：回复以一个直接问用户的问题结尾，则为 user。
3. 等用户：回复已经说完了一个想法、一句陈述或一件事，且不符合规则 1 和规则 2，表示停下来等用户的反应，则为 user。
只输出 JSON：{"reasoning": "依据哪条规则的简短理由", "next_speaker": "user" 或 "model"}"""

QUESTION_MAX = 1500  # 判官看到的用户问题 / 回复各截多少字（取回复的结尾）
REPLY_MAX = 2000
TAIL = 160           # 闸门只看回复最后这么多字

# 结尾像“说要做”：中文常见说法 + Gemini 例句的英文说法
_PROMISE = re.compile(
    r"(接下来|下一步|然后|现在|这就|马上|稍等|稍后)[^。！？!?\n]{0,12}(我|让我|来|去|开始|继续|处理|执行|检查|修改|运行|查看|看看)"
    r"|(让我|我来|我先|我再|我去|我会|我将|我要|我这就|我马上|我现在)[^。！？!?\n]{0,20}(一下|看看|检查|修改|运行|执行|处理|查|改|试|装|写|读|打开|搜索|确认|继续)"
    r"|\b(let me|i'll now|i will now|now i'll|now i will|next,? i(?:'ll| will)|i'm going to|moving on to)\b",
    re.I)
_DANGLING = re.compile(r"(：|:|…|\.\.\.|，|,|、)\s*$")  # 以冒号 / 省略号 / 逗号收尾：后面本该有东西
_ASKS = re.compile(r"[？?]\s*\W*\s*$|回复|告诉我|你(要|想|觉得|看)|需要我|要不要|是否|可以吗|好吗|行吗|确认一下|请(你|您)|let me know|would you|do you want", re.I)
_SENT = re.compile(r"[。！？!?\n]+")


def mode() -> str:
    m = (settings.next_speaker_check or "auto").strip().lower()
    return m if m in MODES else "auto"


def limit() -> int:
    """每轮最多替用户补几次“继续”；0 或模式 off = 不检测。"""
    return 0 if mode() == "off" else max(0, int(settings.next_speaker_max))


def _tail(text: str) -> str:
    return text.strip()[-TAIL:]


def _last_sentence(text: str) -> str:
    parts = [p for p in _SENT.split(text.strip()) if p.strip()]
    return parts[-1].strip() if parts else ""


def gate(text: str, cut: bool = False, used_tools: bool = False) -> str | None:
    """本地规则（零调用）：返回 "model" = 肯定该续（截断 / 用过工具后空答复），"maybe" = 像是说要做（auto 模式交判官），
    None = 不续。以问句结尾或在请用户回复 → None（Gemini 规则 2）。"""
    body = text.strip()
    if cut:
        return "model"   # 被输出长度上限截断：明显没说完（规则 1）
    if not body:
        return "model" if used_tools else None  # Gemini：空的模型消息，用户没什么可回应的 → model
    tail = _tail(body)
    if _ASKS.search(tail):
        return None
    if _DANGLING.search(tail):
        return "maybe"
    last = _last_sentence(tail)
    if last and _PROMISE.search(last):
        return "maybe"
    return None


def _parse(raw: str) -> str | None:
    """判官的回复 → "user" / "model" / None（答非所问；Gemini：缺字段、不是字符串、不在枚举里都算 null）。"""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", s)
    start = s.find("{")
    if start < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(s[start:])
    except ValueError:
        return None
    who = obj.get("next_speaker") if isinstance(obj, dict) else None
    return who if isinstance(who, str) and who in ("user", "model") else None


def last_question(history: list[dict]) -> str:
    """上文里最后一条真正的用户消息（跳过 [系统提示] 一类的内部提示）。"""
    for m in reversed(history):
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, list):
            c = " ".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
        if isinstance(c, str) and c.strip() and not c.lstrip().startswith("[系统提示]"):
            return c.strip()
    return ""


async def judge(question: str, reply: str, model: str | None = None) -> str | None:
    """问最便宜的模型（summary_model）：接下来谁说话。任何异常 → None（不续，Gemini 同）。"""
    q = question[-QUESTION_MAX:] if question else "（无）"
    a = reply.strip()[-REPLY_MAX:]
    try:
        raw = await llm.complete([
            {"role": "system", "content": CHECK_PROMPT},
            {"role": "user", "content": f"用户的问题：\n{q}\n\n助手的回复：\n{a}"},
        ], model or settings.summary_model, kind="next_speaker", max_tokens=200)
    except Exception as e:  # noqa: BLE001 —— 判官失败不影响回复
        log.warning("next speaker check failed: %s", e)
        return None
    return _parse(raw)


async def decide(text: str, cut: bool, used_tools: bool, history: list[dict]) -> bool:
    """这一步没有工具调用、本该结束：要不要替用户补一句“继续”。"""
    m = mode()
    if m == "off":
        return False
    g = gate(text, cut, used_tools)
    if g is None:
        return False
    if g == "model" or m == "rules":
        return True
    return await judge(last_question(history), text) == "model"
