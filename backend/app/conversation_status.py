"""v2.91 §N 对话状态——项目对话列表上的胶囊（进行中 / 等你回复 / 已完成），唯一规则在这里。
GET /api/conversations?project_id= 每项带 status；客户端只按值画，不自己推断。

- running：本进程有这段对话的一轮在跑（live_turns 主路或并行路），且没有挂起等用户的卡片；
  或有这段对话开的后台任务在跑（常驻 keep_alive 除外：常驻服务会让对话永远“进行中”），或任务结束、助手还要接着说（followup=pending）。
- waiting：正在跑的那一轮挂着等用户的卡片（审批 / 表单 / 下单确认 / 方案批准 / 浏览器“需要你来”）；
  或不在跑、最后一条是正常结束的回复，且最后一段文字以问号收尾（在问你）。轮次结束时挂起的卡片都会变 expired（agent/loop.py），
  所以静止时只剩“回复本身在提问”这一种等你的信号。
- done：不在跑、最后一条是正常结束（done / wrapped）的回复，没在提问。
- None：其它（没有消息、最后一条是没等到回复的用户消息、回复被停止 / 打断 / 原地打转）——不画胶囊。"""
from __future__ import annotations

from sqlalchemy import func, select

from . import live_turns
from .models import Job, Message

RUNNING, WAITING, DONE = "running", "waiting", "done"
FINISHED = ("done", "wrapped")  # 正常结束的回复（wrapped = 预算到头好好收了尾）
_ASKS = ("？", "?")
_TRAIL = " \t\n*_`>)）】」』\"'”’~～。."  # 问号后面可能跟的 Markdown 收尾符号 / 引号（“…吗？”）


def _pending(block: dict) -> bool:
    if not isinstance(block, dict):
        return False
    if block.get("state") == "pending" and block.get("type") in ("approval", "form", "order", "plan_review"):
        return True
    handoff = block.get("handoff") if block.get("type") == "browser" else None
    return isinstance(handoff, dict) and handoff.get("state") == "pending"


def asks(blocks: list | None) -> bool:
    """回复最后一段文字以问号收尾 = 在问用户。只看最后一个非空文字块的最后一段。"""
    for b in reversed(blocks or []):
        if isinstance(b, dict) and b.get("type") == "text" and (b.get("text") or "").strip():
            last = b["text"].strip().split("\n")[-1].rstrip(_TRAIL)
            return last.endswith(_ASKS)
    return False


def derive(turn_blocks: list[list] | None, job_running: bool, last: tuple[str, str, list] | None) -> str | None:
    """纯规则。turn_blocks = 正在跑的每一轮已产出的块（None = 没在跑）；last = 最后一条消息 (role, status, blocks)。"""
    if turn_blocks is not None:
        return WAITING if any(_pending(b) for blocks in turn_blocks for b in blocks) else RUNNING
    if job_running:
        return RUNNING
    if last is None:
        return None
    role, status, blocks = last
    if role != "assistant" or status not in FINISHED:
        return None
    return WAITING if asks(blocks) else DONE


async def for_list(db, ids: list[str]) -> dict[str, str | None]:
    """一批对话 → {id: status}。两次查询：每段对话的最后一条消息、在跑的后台任务。"""
    if not ids:
        return {}
    newest = (select(Message.conversation_id, func.max(Message.created_at).label("at"))
              .where(Message.conversation_id.in_(ids)).group_by(Message.conversation_id).subquery())
    rows = (await db.execute(select(Message.conversation_id, Message.role, Message.status, Message.blocks)
                             .join(newest, (Message.conversation_id == newest.c.conversation_id) & (Message.created_at == newest.c.at)))).all()
    last = {cid: (role, status, blocks) for cid, role, status, blocks in rows}
    jobs = set((await db.scalars(select(Job.conversation_id).where(
        Job.conversation_id.in_(ids),
        ((Job.state == "running") & Job.keep_alive.is_(False)) | (Job.followup == "pending")))).all())
    busy = live_turns.busy()
    return {cid: derive([t.blocks for t in busy[cid]] if cid in busy else None, cid in jobs, last.get(cid)) for cid in ids}
