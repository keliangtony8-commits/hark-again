# Ported from deepseek-ai/deepseek-harness (MIT):
#   packages/compaction/compaction-tool-result-pruner/src/{index,config}.ts  (head/middle/tail pruning, defaults)
#   packages/compaction/compaction-basic/src/region.ts selectCompactableRange (retained tail + tool-balanced cut)
#   packages/compaction/compaction/src/tool-pairing.ts (cut balance)
#   packages/compaction/compaction-basic/src/summarizer.ts (instruction as the LAST user message after the replayed
#   prefix, checkpoint framing, prior-checkpoint merge rule, max-tokens = failure)
# Grafted (Apache-2.0, modified):
#   google-gemini/gemini-cli packages/core/src/context/chatCompressionService.ts — RECENT_TURNS_PROTECTED (newest tool
#   batches never pruned), reject an inflated result, after a failed summary stay prune-only for the rest of the turn.
#   openai/codex codex-rs/core/src/compact.rs — approx tokens = UTF-8 bytes / 4; on context overflow while compacting,
#   drop the oldest item of the summarizer input and retry.
"""一轮回复里的上文压缩（唯一规则）：长任务走几十步时，工具结果把上文越堆越长，迟早超出模型窗口。

时机（deepseek-harness 的 pressure + overflow 两条路）：
- 每次调用模型前量一次上文（上次调用的真实输入 token + 之后新加消息的估算；没报用量就全估算）。
  过了窗口的 COMPACT_RATIO → 压；
- 模型报“上文超长” → 强制压一次再重试（loop 里只重试一次）。

怎么压（先便宜后贵）：
1. 剪工具结果（不调模型）：这一轮里较早的、超过 PRUNE_THRESHOLD 字的工具结果只留开头 + 结尾，中间换成说明。
   最近 PROTECTED_BATCHES 批工具结果不动（Gemini）。剪完够了就到此为止；
2. 写交接摘要（调一次模型）：从这一轮自己的第一条消息起，到“保留尾巴”（≥ 窗口 RETAIN_RATIO 的最近原文）之前，
   切口不能把“助手的工具调用”和“它的结果”拆开；把这段换成一条“检查点”用户消息。
   摘要请求 = 原样重放这段上文 + 最后一条指令（工具定义照带、tool_choice=none，供应商前缀缓存能命中）。
   区间里已有检查点 → 指令要求合并成一份新的（不叠层）。
   摘要比原文还长 / 被截断 / 出错 → 不换；本轮之后只剪不再摘要（强制时除外）。

不动的：系统提示、上几轮对话（context.build_history 已经按预算 + 滚动摘要管着）、当前这一问。
不落库：压缩只改这一轮发给模型的上文；用户看到的回复与时间线上多一步“整理上文”。
"""
import logging
import math
from collections.abc import Callable

from .. import llm, llm_retry
from ..config import settings

log = logging.getLogger(__name__)

# —— 剪工具结果（deepseek-harness DEFAULTS） ——
PRUNE_THRESHOLD = 8192
PRUNE_HEAD = 4096
PRUNE_TAIL = 1024
PRUNE_MARKER = "\n\n[……这段工具结果的中间部分已省略以节省上文；需要时重新读取……]\n\n"
PROTECTED_BATCHES = 3        # 最近几批工具结果保持原样（Gemini RECENT_TURNS_PROTECTED）

# —— 摘要 ——
COMPACT_RATIO = 0.8          # 上文过窗口的这个比例就压（deepseek-harness thresholdRatio）
RETAIN_RATIO = 0.16          # 至少保留窗口这个比例的最近原文（retainedHistoryRatio）
SUMMARY_MAX_TOKENS = 8192
SUMMARY_RETRIES = 3          # 摘要请求本身超长时，从最旧的一段起丢掉再试（Codex）
IMAGE_TOKENS = 1000          # 估算：一张图按这么多 token 算

SUMMARY_OPEN, SUMMARY_CLOSE = "<compacted-summary>", "</compacted-summary>"
CHECKPOINT_PREAMBLE = (
    "[系统提示] 这是自动生成的检查点：这一轮较早的工作已压缩成下面的摘要以腾出上文。"
    "把它当作已经确立的背景继续往下做，不要复述，也不要提到有这个检查点。")
INSTRUCTION = "\n".join([
    "[系统提示] 现在你暂时充当上文压缩器：把上面这一轮的工作压缩成一份检查点，让另一个模型能无缝接着做。",
    "严格按下面的 Markdown 结构输出，每一节都保留、顺序不变；用简短要点，空的一节写“（无）”。",
    "",
    "## 用户的请求与意图",
    "- 用户最初和后来补充的目标；措辞要紧时原文引用",
    "## 关键环境与概念",
    "- 用到的技术、目录结构、约定",
    "## 文件与代码",
    "- 确切路径：为什么重要、改了什么或关键片段",
    "## 出错与解决",
    "- 错误：怎么解决的，以及用户的相关反馈",
    "## 未完成的事",
    "- 用户明确要求但还没做完的",
    "## 正在做的",
    "- 检查点这一刻手上在做什么",
    "## 下一步",
    "- 紧接着要做的一件事，或“（无）”",
    "## 关键上下文",
    "- 决定及理由、约束、用户偏好、待解决的问题、继续所需的数据",
    "",
    "规则：",
    "- 用简洁中文；确切保留文件路径、命令、报错原文、标识符、数字、网址、任务 id、端口。",
    "- 如实记下用户的反馈和明确指示，尤其是纠正。",
    "- 不要提到这次压缩请求，不要调用任何工具，只输出检查点正文。",
    f"- 上文里如果已有 {SUMMARY_OPEN} 块，那是之前的检查点：不要原样照抄，保留仍然成立的、去掉过时的，"
    "把新信息合并进同一份结构里。",
])


def window(model: str | None) -> int:
    """这个别名的上文窗口（token）。"""
    alias = model or settings.default_model
    return settings.model_context.get(alias, settings.context_tokens)


def _text_of(content) -> tuple[str, int]:
    """消息内容 → (文字, 图片张数)。"""
    if content is None:
        return "", 0
    if isinstance(content, str):
        return content, 0
    texts, images = [], 0
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text":
            texts.append(part.get("text") or "")
        else:
            images += 1
    return "\n".join(texts), images


def approx_tokens(text: str) -> int:
    """Codex approx_token_count：UTF-8 字节 / 4（中文 3 字节一个字 ≈ 0.75 token，偏保守）。"""
    return math.ceil(len(text.encode("utf-8")) / 4)


def message_tokens(m: dict) -> int:
    text, images = _text_of(m.get("content"))
    for c in m.get("tool_calls") or ():
        f = c.get("function") or {}
        text += (f.get("name") or "") + (f.get("arguments") or "")
    return approx_tokens(text) + images * IMAGE_TOKENS + 4


def estimate(messages: list[dict]) -> int:
    return sum(message_tokens(m) for m in messages)


def balanced_cuts(messages: list[dict]) -> list[bool]:
    """cuts[i] = 第 i 条消息之前切一刀是否安全（没有悬着的工具调用跨过这一刀）。len = len(messages) + 1。
    deepseek-harness tool-pairing：助手消息带 n 个调用 +n，每条工具结果 −1。"""
    cuts, open_calls = [True], 0
    for m in messages:
        if m.get("role") == "assistant":
            open_calls += len(m.get("tool_calls") or ())
        elif m.get("role") == "tool":
            open_calls = max(0, open_calls - 1)
        cuts.append(open_calls == 0)
    return cuts


def prune_text(text: str) -> str | None:
    """超过阈值 → 开头 + 说明 + 结尾（按字符，Python str 本身就不会拆坏代理对）；没超 → None。"""
    if len(text) <= PRUNE_THRESHOLD:
        return None
    return text[:PRUNE_HEAD] + PRUNE_MARKER + text[len(text) - PRUNE_TAIL:]


def protected_from(messages: list[dict], start: int) -> int:
    """最近 PROTECTED_BATCHES 批工具调用（从带 tool_calls 的助手消息算起）的起点；这之后的工具结果不剪。"""
    batches = [i for i in range(start, len(messages))
               if messages[i].get("role") == "assistant" and messages[i].get("tool_calls")]
    return batches[-PROTECTED_BATCHES] if len(batches) >= PROTECTED_BATCHES else start


def prune(messages: list[dict], start: int) -> int:
    """剪掉 start 之后、保护区之前的长工具结果（替换条目，不改原 dict）。返回剪掉了多少字。"""
    removed, stop = 0, protected_from(messages, start)
    for i in range(start, stop):
        m = messages[i]
        if m.get("role") != "tool" or not isinstance(m.get("content"), str):
            continue
        if (new := prune_text(m["content"])) is not None:
            removed += len(m["content"]) - len(new)
            messages[i] = {**m, "content": new}
    return removed


def select_range(messages: list[dict], start: int, retain: int) -> tuple[int, int] | None:
    """deepseek-harness selectCompactableRange：从末尾往前累计到 ≥ retain，再往前挪到安全切口。
    返回要压的 [start, end)；不值得/切不出来 → None。retain=0 = 尽量多压，但至少留下最新的一个完整单元。"""
    keep = len(messages)
    total = 0
    for i in range(len(messages) - 1, start - 1, -1):
        total += message_tokens(messages[i])
        keep = i
        if total >= retain:
            break
    if retain == 0:
        keep = len(messages) - 1
    if keep <= start:
        return None
    cuts = balanced_cuts(messages)
    while keep > start and not cuts[keep]:
        keep -= 1
    if keep <= start:
        return None
    return start, keep


def is_checkpoint(m: dict) -> bool:
    return m.get("role") == "user" and isinstance(m.get("content"), str) \
        and m["content"].startswith(CHECKPOINT_PREAMBLE)


def checkpoint(summary: str, pinned: str = "") -> dict:
    """检查点消息。pinned = 摘要之后原样钉上的内容（当前计划清单，plan.pinned）：不经摘要模型转述，不会丢。"""
    tail = f"\n\n{pinned.strip()}" if pinned and pinned.strip() else ""
    return {"role": "user",
            "content": f"{CHECKPOINT_PREAMBLE}\n\n{SUMMARY_OPEN}\n{summary.strip()}\n{SUMMARY_CLOSE}{tail}"}


def _no_images(m: dict) -> dict:
    """摘要请求不带图（省钱；摘要只要文字）。"""
    if isinstance(m.get("content"), list):
        text, images = _text_of(m["content"])
        return {**m, "content": text + (f"\n[{images} 张图片已省略]" if images else "")}
    return m


def is_overflow(e: BaseException) -> bool:
    """供应商说“上文超长”（OpenAI 兼容错误码或常见措辞）。"""
    code = str(getattr(e, "code", "") or "")
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        err = body.get("error") if isinstance(body.get("error"), dict) else body
        code += " " + str(err.get("code") or "") + " " + str(err.get("message") or "")
    if llm_retry.is_context_exceeded(code + " " + str(e)):  # deepseek-harness error.ts 的措辞分类（llm_retry.py）
        return True
    text = (code + " " + str(e)).lower()
    return any(k in text for k in ("context_length_exceeded", "context length", "context window", "maximum context",
                                   "too many tokens", "prompt is too long", "input is too long", "上下文长度", "超出上下文"))


async def summarize(prefix: list[dict], tools: list[dict] | None, model: str | None, effort: str | None = None) -> str:
    """重放 prefix（系统提示 … 要压的最后一条）+ 指令，拿检查点正文。超长 → 从这一轮最旧的一段起丢掉再试。"""
    msgs = [_no_images(m) for m in prefix]
    for attempt in range(SUMMARY_RETRIES + 1):
        try:
            text = await llm.complete([*msgs, {"role": "user", "content": INSTRUCTION}], model=model, kind="compact",
                                      tools=tools, max_tokens=SUMMARY_MAX_TOKENS, strict=True,
                                      effort=effort, helper=False)  # 检查点要靠谱：沿用这一轮的思考强度
        except Exception as e:  # noqa: BLE001
            if not is_overflow(e) or attempt == SUMMARY_RETRIES:
                raise
            msgs = _drop_oldest(msgs)
            if msgs is None:
                raise
            continue
        if not text.strip():
            raise ValueError("摘要是空的")
        return text
    raise RuntimeError("unreachable")


def _drop_oldest(msgs: list[dict]) -> list[dict] | None:
    """去掉系统提示之后最旧的一个完整单元（助手调用连同它的结果一起走）。"""
    if len(msgs) <= 2:
        return None
    cuts = balanced_cuts(msgs)
    j = 2
    while j < len(msgs) and not cuts[j]:
        j += 1
    rest = msgs[:1] + msgs[j:]
    return rest if len(rest) > 1 else None


class Compactor:
    """loop 一轮的压缩器。base = 这一轮自己的第一条消息（系统提示 + 历史之后）。"""

    def __init__(self, base: int, model: str | None, tools: list[dict] | None,
                 pinned: Callable[[], str] | None = None, effort: str | None = None):
        """pinned = 写检查点那一刻要原样钉上的文字（loop 传当前计划，plan.pinned）。effort = 这一轮的思考强度选择。"""
        self.base, self.model, self.tools, self.pinned, self.effort = base, model, tools, pinned, effort
        self.limit = int(window(model) * COMPACT_RATIO)
        self.retain = int(window(model) * RETAIN_RATIO)
        self.anchor: tuple[int, int] | None = None  # (上次调用的真实 token, 那时的消息条数)
        self.failed = False
        self.count = 0
        self.stuck: int | None = None  # 上次什么都压不动时的保护区起点：没有新工具批次挪动它之前不再试

    def due(self, messages: list[dict]) -> bool:
        if self.stuck is not None and self.stuck == protected_from(messages, self.base):
            return False
        return self.pressure(messages) >= self.limit

    def observe(self, tokens: int, at: int) -> None:
        """一次模型调用结束：tokens = 供应商报的输入 token（0 = 没报），at = 那次调用时的消息条数。"""
        self.anchor = (tokens, at) if tokens else None

    def pressure(self, messages: list[dict]) -> int:
        est = estimate(messages)
        if self.anchor and self.anchor[1] <= len(messages):
            tokens, at = self.anchor
            return max(est, tokens + estimate(messages[at:]))
        return est

    async def maybe(self, messages: list[dict], force: bool = False) -> dict | None:
        info = await self._maybe(messages, force)
        over = info is None and (force or self.pressure(messages) >= self.limit)
        self.stuck = protected_from(messages, self.base) if over else None
        return info

    async def _maybe(self, messages: list[dict], force: bool = False) -> dict | None:
        """需要时就地压 messages（替换列表里的条目）。返回 {"pruned", "folded", "before", "after", "start", "end"}
        （没动 → None）。folded = 被摘要换掉的消息条数（0 = 只剪了）。"""
        before = self.pressure(messages)
        if not force and before < self.limit:
            return None
        pruned = prune(messages, self.base)
        info = {"pruned": pruned, "folded": 0, "before": before, "after": before, "start": 0, "end": 0}
        if pruned:
            self.anchor = None
            info["after"] = estimate(messages)
            if not force and info["after"] < self.limit:
                return info
        if self.failed and not force:
            return info if pruned else None
        rng = select_range(messages, self.base, 0 if force else self.retain)
        if rng is None:
            return info if pruned else None
        s, e = rng
        try:
            summary = await summarize(messages[:e], self.tools, self.model, self.effort)
        except Exception as ex:  # noqa: BLE001 — 压不了就带着原文继续，不拖垮这一轮
            log.warning("turn compaction failed: %s", ex)
            self.failed = True
            return info if pruned else None
        new = [*messages[:s], checkpoint(summary, self.pinned() if self.pinned else ""), *messages[e:]]
        if estimate(new) >= estimate(messages):  # 摘要反而更长（Gemini inflated）：不换
            self.failed = True
            return info if pruned else None
        messages[:] = new
        self.anchor = None
        self.count += 1
        info.update(folded=e - s, after=estimate(messages), start=s, end=e)
        return info


def describe(info: dict) -> str:
    """时间线这一步的摘要。"""
    if info["folded"]:
        return f"上文太长：把这一轮较早的 {info['folded']} 条消息压成了摘要（约 {info['before']} → {info['after']} token）"
    return f"上文太长：精简了较早的长工具结果（约 {info['before']} → {info['after']} token）"

