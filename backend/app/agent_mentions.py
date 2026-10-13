# Portions Copyright 2025 Google LLC — Apache-2.0 (modified).
# Ported from google-gemini/gemini-cli packages/cli/src/ui/hooks/atCommandProcessor.ts (Apache-2.0):
#   categorizeAtCommands（@名字 先按“代理”认，认上了就不再当文件）+ handleAtCommand 的 agentNudge
#   （“用户点名了这些代理，请用对应工具交给它”的 <system_note>），modified:
#   - 我们只有一个通用子助手（delegate 工具），不是代理注册表：认 @子助手 / @agent / @subagent 三个名字；
#   - 提示只给“当前这一问”（Gemini 留在历史里；这里更早的只留一句记录，用户说“继续”时模型不会再派一遍）；
#   - 存成 agent 引用块（同 $技能），气泡上一枚小标签；子助手关掉（SUBAGENT_MAX_TASKS=0）时不认。
"""消息里的 `@子助手`：用户点名“这件事交给子助手做”（学 Gemini CLI 的 @agent）。这是唯一规则。
routes/ws 发消息时用 blocks() 认出来存成引用块；agent/context 渲染时当前这一问给 NUDGE、更早的给 RECORD；
app/file_mentions 先用 blank() 抹掉这些名字（代理优先，不再当文件找）。"""
import re

from .config import settings

NAMES = ("子助手", "subagent", "agent")  # 长的在前：@subagent 不会被 agent 截走（这里各自独立，顺序只为可读）
BLOCK = {"type": "agent", "id": "delegate", "name": "子助手"}

# @ 前面同 file_mentions（邮箱、a@b 不算）；后面紧跟英文名字字符 / 路径字符就不是（@agent.md、@agents、@agent/x 是文件）
_RE = re.compile(r"(?<![A-Za-z0-9_.\\@])@(子助手|subagent|agent)(?![A-Za-z0-9_\-/\\]|\.[A-Za-z0-9_])", re.I)
_CODE = re.compile(r"```.*?(?:```|$)|`[^`\n]*`", re.S)  # 代码里的 @agent（装饰器、包名）不算

NUDGE = ("<system_note>\n用户点名这次交给子助手做：用 delegate 工具把这件事派出去（能拆成互相独立的几块就一次全放进 tasks 并行；"
         "只有一件也交给一个子助手），子助手看不到这段对话，prompt 要写全。等结论回来再整理后告诉用户，不要自己先做一遍。\n</system_note>")
RECORD = "[这一问用户点名交给了子助手]"

# v1.97 续问（卡片上点“追问”）：块带 target = 子助手编号，同一条 delegate 路（Codex resume_agent 冷恢复，规则在 agent/subagent_threads.py）
FOLLOW = ("<system_note>\n用户在子任务卡上点了“追问”，要接着问子助手「{title}」（编号 {target}）：用 delegate 工具，tasks 里放 "
          "{{continue: \"{target}\", prompt: 用户这句话（它看不到这段对话，代词、上下文替它补全）}}。等它的结论回来再整理后告诉用户，不要自己先做一遍。\n</system_note>")
GONE = ("<system_note>\n用户想接着问子助手「{title}」，但它的上下文已经清掉了（或不是这段对话派的）：告诉用户这一点，"
        "然后照常回答——需要的话新派一个子助手，prompt 写全。\n</system_note>")
FOLLOW_RECORD = "[这一问用户追问了子助手「{title}」（编号 {target}）]"
TITLE_MAX = 24


def enabled() -> bool:
    return settings.subagent_max_tasks > 0


def _spans(text: str) -> list[tuple[int, int]]:
    if not isinstance(text, str) or "@" not in text:
        return []
    clean = _CODE.sub(lambda m: " " * len(m.group(0)), text)
    return [m.span() for m in _RE.finditer(clean)]


def found(text: str | None) -> bool:
    """text 里有没有点名子助手（不管开关）。纯函数。"""
    return bool(_spans(text or ""))


def blank(text: str) -> str:
    """把 @子助手 换成等长空白：file_mentions 解析前调用（代理优先，Gemini categorizeAtCommands 的顺序）。"""
    if not (spans := _spans(text)):
        return text
    out = list(text)
    for a, b in spans:
        out[a:b] = " " * (b - a)
    return "".join(out)


def blocks(text: str | None, have: list[dict] | None = None) -> list[dict]:
    """点名了、开关开着、have 里还没有 → [agent 引用块]，否则 []。"""
    if not enabled() or not found(text) or any(b.get("type") == "agent" for b in have or []):
        return []
    return [dict(BLOCK)]


async def follow(db, conversation_id: str | None, target: object, title: object = None) -> list[dict]:
    """用户点“追问”：target 是这段对话派过、上下文还在的子助手 → 带 target / title 的 agent 块；不在了 → gone 块（模型照实说）；
    开关关着 / target 不像编号 → []（当普通消息）。"""
    from .agent import subagent_threads as threads
    if not enabled() or not threads.valid_id(target):
        return []
    row = await threads.load(db, conversation_id, target)
    name = row.title if row is not None else " ".join(str(title or "").split())[:TITLE_MAX]
    out = {**BLOCK, "target": target, "title": name or "子任务"}
    return [out if row is not None else {**out, "gone": True}]


def render(current: bool, b: dict | None = None) -> str:
    """给模型看的样子：当前这一问 = Gemini agentNudge（续问 = FOLLOW / GONE）；更早的 = 一句记录。"""
    if b and b.get("target"):
        fill = {"title": b.get("title") or "子任务", "target": b["target"]}
        if not current:
            return FOLLOW_RECORD.format(**fill)
        return (GONE if b.get("gone") else FOLLOW).format(**fill)
    return NUDGE if current else RECORD
