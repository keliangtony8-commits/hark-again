# Portions Copyright 2025 OpenAI — Apache-2.0 (modified).
# Ported from openai/codex codex-rs/core/src/tools/handlers/multi_agents/resume_agent.rs (Apache-2.0), modified:
#   子线程结束后按 id 冷恢复：找到它、检查深度、用原来的上下文接着跑；这里不保留活线程（我们一轮内等完），
#   上下文存进 subagent_threads 表，续问时整段读回来再接一句新的用户消息。
# 嫁接 deepseek-harness packages/subagent/subagent（MIT）：只有派它的那段对话（直接父）能续；描述符记下模型供恢复；
#   结束了的子助手留在列表里可以再打开 / 续问。
# 我们加：存之前剪掉没收尾的工具调用（被停 / 超时时最后一步只有调用没有结果，接着发会被供应商拒）、
#   旧工具结果截短（续问不重付大段输出）、每段对话最多留 KEEP 个。
"""子助手的上下文（唯一规则）：哪个子助手还能接着问、接着问时带什么上文。

id 形如 sa_1a2b3c（给模型和卡片看，短）；只能在派它的那段对话里续；同一次 delegate 里不能续同一个两次。
"""
import json
import secrets
from datetime import datetime, timezone

from sqlalchemy import delete, select

from ..models import SubagentThread

KEEP = 20            # 每段对话最多留几个子助手的上下文（最旧的先丢）
TOOL_KEEP = 1500     # 存下来的每条工具结果最多多少字（续问时旧输出只是背景）
HISTORY_MAX = 60000  # 整段上文的字数上限：超了从最早的工具结果开始换成一句占位
CLIPPED = "…（较早的工具输出已截短）"
DROPPED = "（较早的工具输出已省略）"


def new_id() -> str:
    return "sa_" + secrets.token_hex(3)


def valid_id(sid: object) -> bool:
    return isinstance(sid, str) and len(sid) == 9 and sid.startswith("sa_") and all(c in "0123456789abcdef" for c in sid[3:])


def tidy(messages: list[dict]) -> list[dict]:
    """可以接着发的上文：去掉系统提示；截到最后一个“工具调用都有结果”的位置；工具结果截短；总长超了丢最早的工具输出。纯函数。"""
    msgs = [dict(m) for m in messages if isinstance(m, dict) and m.get("role") != "system"]
    pending: set[str] = set()
    cut = 0
    for i, m in enumerate(msgs):
        if m.get("role") == "assistant" and m.get("tool_calls"):
            pending = {c.get("id") for c in m["tool_calls"] if isinstance(c, dict)}
        elif m.get("role") == "tool":
            pending.discard(m.get("tool_call_id"))
        if not pending:
            cut = i + 1
    msgs = msgs[:cut]
    while msgs and msgs[-1].get("role") == "assistant" and not (msgs[-1].get("content") or "").strip() \
            and not msgs[-1].get("tool_calls"):
        msgs.pop()  # 空回复没用
    for m in msgs:
        if m.get("role") == "tool" and isinstance(m.get("content"), str) and len(m["content"]) > TOOL_KEEP:
            m["content"] = m["content"][:TOOL_KEEP] + CLIPPED
        elif m.get("role") == "tool" and not isinstance(m.get("content"), str):
            m["content"] = json.dumps(m.get("content"), ensure_ascii=False)[:TOOL_KEEP]
        elif m.get("role") == "user" and not isinstance(m.get("content"), str):
            m["content"] = " ".join(p.get("text", "") for p in m.get("content") or [] if isinstance(p, dict))
    size = sum(len(_text(m)) for m in msgs)
    for m in msgs:
        if size <= HISTORY_MAX:
            break
        if m.get("role") == "tool" and m["content"] != DROPPED:
            size -= len(m["content"]) - len(DROPPED)
            m["content"] = DROPPED
    return msgs


def _text(m: dict) -> str:
    c = m.get("content")
    return (c if isinstance(c, str) else json.dumps(c, ensure_ascii=False) if c else "") + \
        (json.dumps(m["tool_calls"], ensure_ascii=False) if m.get("tool_calls") else "")


def opening(title: str, prompt: str) -> dict:
    return {"role": "user", "content": f"任务：{title}\n\n{prompt}"}


def follow_up(prompt: str) -> dict:
    return {"role": "user", "content": f"主助手接着问（你之前做的结果它已经收到了）：\n\n{prompt}"}


async def load(db, conversation_id: str | None, sid: str) -> SubagentThread | None:
    """只有派它的那段对话能续（deepseek：直接父）。"""
    if not conversation_id or not valid_id(sid):
        return None
    row = await db.get(SubagentThread, sid)
    return row if row is not None and row.conversation_id == conversation_id else None


def history_of(row: SubagentThread) -> list[dict]:
    try:
        h = json.loads(row.history or "[]")
    except ValueError:
        return []
    return h if isinstance(h, list) else []


async def save(db, conversation_id: str | None, sid: str, title: str, model: str | None, state: str,
               transcript: list[dict], resumed: bool) -> bool:
    """子任务结束时调：留下能接着发的上文；什么也没有（第一步就出错）→ 不存。返回存没存。调用方 commit。"""
    if not conversation_id:
        return False
    history = tidy(transcript)
    if not any(m.get("role") == "assistant" for m in history):
        return False
    now = datetime.now(timezone.utc)
    row = await db.get(SubagentThread, sid)
    if row is not None and row.conversation_id != conversation_id:
        return False  # 防御：编号撞了别的对话的
    if row is None:
        row = SubagentThread(id=sid, conversation_id=conversation_id, title=title[:64], created_at=now, rounds=0)
        db.add(row)
    row.model, row.state, row.history, row.updated_at = model, state, json.dumps(history, ensure_ascii=False), now
    row.rounds = (row.rounds or 0) + 1 if resumed or not row.rounds else row.rounds
    await db.flush()
    keep = select(SubagentThread.id).where(SubagentThread.conversation_id == conversation_id) \
        .order_by(SubagentThread.updated_at.desc()).limit(KEEP)
    await db.execute(delete(SubagentThread).where(SubagentThread.conversation_id == conversation_id,
                                                  SubagentThread.id.not_in(keep)))
    return True

