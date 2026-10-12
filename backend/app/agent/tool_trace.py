# Portions ported from openai/codex (Apache-2.0), modified:
#   codex-rs/core/src/context_manager/normalize.rs (ensure_call_outputs_present / remove_orphan_outputs)
#   codex-rs/utils/output-truncation/src/lib.rs (formatted_truncate_text: record-time middle truncation + header)
"""跨轮保留工具轨迹的唯一规则（v1.55）。

以前每轮结束只存回复的块（文字 + 卡片），模型下一轮看不到自己上一轮调过什么工具、拿到过什么结果，
用户说“刚才那个命令再跑一次”“把你刚读的文件第 3 行改掉”时只能重新摸索。Codex / Gemini CLI / deepseek-harness
都把工具调用和结果留在历史里；这里取 Codex 的做法：

- record(messages, base)：一轮跑完（含被停下）时，从内核的消息列表里取这一轮新增的 assistant tool_calls + tool 结果，
  按 Codex normalize 的配对规则清洗（调用缺结果 → 补 ABORTED；没有调用的结果 → 丢；轮内的提醒/图片/检查点等 user 消息 → 丢），
  落库前截断（Codex 在 record_items 时按 TruncationPolicy 截 function output，而不是等到发送时）：
  每个结果中间截到 OUTPUT_MAX，头部注明原长与行数；参数里过长的字符串截到 ARG_MAX（write_file 的整份内容不重复存）；
  页面快照下一轮一定过期 → supersede 占位；疑似密钥的行打码（file_edit.SECRET_LINE）；
  整轮超过 settings.history_trace_chars 时从最早的调用批次丢起（至少留最新一批）。
- replay(trace)：build_history 把最近 settings.history_trace_turns 条回复的轨迹原样放回去：
  [assistant tool_calls, tool…, …, assistant 回复文字]。只放结构，不放轮内的叙述文字（回复块里已经有了，不重复花 token）。
- digest(steps)：更早的回复（以及没有轨迹的老消息 / 被打断的回复）只附一行“这轮用过的工具”，来自时间线 steps，
  也喂给滚动摘要，所以摘要里也知道做过什么。
"""
import json

from ..config import settings
from ..file_edit import SECRET_LINE
from . import supersede

OUTPUT_MAX = 1500   # 每个工具结果最多留多少字（头尾各半）
ARG_MAX = 300       # 参数里每个字符串最多留多少字
DIGEST_MAX = 400    # 一行工具摘要最多多少字
ABORTED = "（这次调用没有结果：这一轮在它完成前被停下或出错了，不确定是否执行过。）"  # Codex 补的是 "aborted"
MASK = "***"
SECRET_KEYS = {"text", "stdin", "password", "secret", "token", "code", "value"}  # browser_type 的 text 可能是用户的私密输入


def _mask(text: str) -> str:
    return "\n".join(SECRET_LINE.sub(lambda m: m.group(1) + MASK, ln) for ln in text.split("\n"))


def clip(text: str, limit: int = OUTPUT_MAX) -> str:
    """中间截断（Codex formatted_truncate_text）：超长时头部写明原长和行数，切口标出省略了多少字。"""
    if len(text) <= limit:
        return text
    head, tail = text[:(limit + 1) // 2], text[len(text) - limit // 2:]
    lines = text.count("\n") + 1
    return f"[原结果 {len(text)} 字、{lines} 行，存进历史时截短了]\n{head}\n…（省略 {len(text) - len(head) - len(tail)} 字）…\n{tail}"


def _shrink(value, key: str = ""):
    if isinstance(value, str):
        if key in SECRET_KEYS and value:
            return MASK
        return value if len(value) <= ARG_MAX else value[:ARG_MAX] + f"…（共 {len(value)} 字，已省略）"
    if isinstance(value, dict):
        return {k: _shrink(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_shrink(v, key) for v in value]
    return value


def _args(raw: str) -> str:
    """参数存成合法 JSON（重放时供应商要能解析）：解析不了就存 {}。"""
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return "{}"
    return json.dumps(_shrink(value), ensure_ascii=False)


def _output(content) -> str:
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    if supersede.start(text) is not None:
        text = supersede.stale(text)
    return clip(_mask(text))


def _groups(items: list[dict]) -> list[list[dict]]:
    """[[assistant tool_calls, tool…], …]：Codex normalize——缺结果补 ABORTED，孤儿结果丢弃，其它角色丢弃。"""
    out: list[list[dict]] = []
    current: list[dict] | None = None
    answered: dict[str, dict] = {}
    for m in items:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            current = [{"role": "assistant", "content": None, "tool_calls": [
                {"id": c["id"], "type": "function",
                 "function": {"name": c["function"]["name"], "arguments": _args(c["function"].get("arguments", ""))}}
                for c in m["tool_calls"] if c.get("id") and c.get("function", {}).get("name")]}]
            if not current[0]["tool_calls"]:
                current = None
                continue
            answered = {}
            out.append(current)
        elif role == "tool" and current is not None:
            ids = {c["id"] for c in current[0]["tool_calls"]}
            cid = m.get("tool_call_id")
            if cid in ids and cid not in answered:
                answered[cid] = {"role": "tool", "tool_call_id": cid, "content": _output(m.get("content", ""))}
                current[1:] = [answered[c["id"]] for c in current[0]["tool_calls"] if c["id"] in answered]
        elif role == "assistant":
            current = None  # 一段纯文字之后再出现的 tool 结果不属于任何调用
    for g in out:  # 补齐缺的结果，顺序跟调用一致
        have = {t["tool_call_id"]: t for t in g[1:]}
        g[1:] = [have.get(c["id"]) or {"role": "tool", "tool_call_id": c["id"], "content": ABORTED}
                 for c in g[0]["tool_calls"]]
    return out


def size(trace: list[dict]) -> int:
    """估算重放时占多少字（和 history_chars 同一把尺子）。"""
    total = 0
    for m in trace:
        total += len(m.get("content") or "")
        for c in m.get("tool_calls") or []:
            total += len(c["function"]["name"]) + len(c["function"]["arguments"])
    return total


def record(messages: list[dict], base: int, limit: int | None = None) -> list[dict]:
    """这一轮新增的工具轨迹（扁平的 OpenAI 消息列表），超 limit 从最早的批次丢起，至少留最新一批。"""
    limit = settings.history_trace_chars if limit is None else limit
    if limit <= 0:
        return []
    groups = _groups(messages[base:])
    kept: list[list[dict]] = []
    total = 0
    for g in reversed(groups):
        n = size(g)
        if kept and total + n > limit:
            break
        kept.insert(0, g)
        total += n
    return [m for g in kept for m in g]


def valid(trace) -> bool:
    """库里读出来的轨迹能不能原样重放（防御：手改过 / 老格式 → 不放，退回 digest）。"""
    if not isinstance(trace, list) or not trace:
        return False
    pending: set[str] = set()
    for m in trace:
        if not isinstance(m, dict):
            return False
        if m.get("role") == "assistant" and m.get("tool_calls"):
            if pending:
                return False
            pending = {c.get("id") for c in m["tool_calls"]}
        elif m.get("role") == "tool" and m.get("tool_call_id") in pending:
            pending.discard(m["tool_call_id"])
        else:
            return False
    return not pending


def replay(trace: list[dict], text: str) -> list[dict]:
    return [*(dict(m) for m in trace), {"role": "assistant", "content": text}]


def digest(steps: list[dict] | None) -> str:
    """一行“这轮用过的工具”（时间线 steps：标题 + 摘要；没结果的标出来）。没有步骤 → 空串。"""
    parts = []
    for s in steps or []:
        if not isinstance(s, dict) or s.get("tool") == "compact_context":
            continue
        piece = s.get("title") or s.get("tool") or ""
        if s.get("detail"):
            piece += f" {s['detail']}"
        state = s.get("state")
        if state == "error":
            piece += "（失败）"
        elif state == "denied":
            piece += "（没批准）"
        elif state in ("stopped", "running"):
            piece += "（没做完）"
        if piece:
            parts.append(piece)
    if not parts:
        return ""
    line = "；".join(parts)
    if len(line) > DIGEST_MAX:
        line = line[:DIGEST_MAX] + f"…（共 {len(parts)} 步）"
    return f"\n\n[这一轮用过的工具：{line}]"
