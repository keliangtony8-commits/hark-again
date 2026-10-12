# Semantics ported from openai/codex (Apache-2.0, Copyright OpenAI) — modified:
#   codex-rs/core/src/session/turn_input.rs steer_input (only into an active, steerable turn; empty input refused)
#   codex-rs/core/src/session/turn.rs run_turn (pending input drained before each sampling request;
#   needs_follow_up = model_needs_follow_up || has_pending_input, so a steer never gets dropped at the end).
"""回答途中补充（v1.83，学 Codex steer）：助手正在干活时用户再发一句，不用等它答完——这句话在下一次调模型前
并进这一轮（模型看到的就是一条新的用户消息），模型本来要收尾了也会再来一圈把它读进去。

唯一入口：只有本模块决定“一句话能不能插进正在跑的一轮”、插进去的话什么时候被读走。
- 收件箱按对话登记：调用方（routes/ws._answer）登记（open_inbox），runner 拼好历史、开跑模型的那一刻才开始收
  （start；早了会和刚落库的历史重复），收尾时关上（close）。关上那一刻还没被读走的
  （模型已经交代完、或预算到头 / 被叫停）交还给调用方，由它另起一轮回答（routes/ws._answer）。
- 能插的只有纯文字：带附件、@文件、$技能、!命令 的走原来的排队（ws 判断后调 offer）。
- 消息照常存成用户消息（status = STEER，客户端在气泡下标“回答途中补充”），created_at 取收下那一刻：
  早于这一轮的回复（回复在收尾时才落库），历史顺序 = 提问 → 补充 → 回复，和模型实际看到的一致。
- 单线程 asyncio：push / take / close 都不 await，彼此之间没有竞争。"""
from dataclasses import dataclass, field
from datetime import datetime, timezone

STEER = "steer"        # 用户消息的 status：回答途中补充进来的
STEER_MAX = 5          # 一轮里最多插几句（再多就排队成下一轮）
STEER_CHARS = 4000     # 一句最长多少字（更长的走排队：那是一条新任务，不是补充）


@dataclass
class Item:
    text: str
    message_id: str
    at: datetime


@dataclass
class Inbox:
    conversation_id: str
    live: bool = False  # 正在收：runner 开跑模型时 start()，close() 关
    taken: int = 0
    items: list[Item] = field(default_factory=list)

    def start(self) -> None:
        self.live = True

    def pending(self) -> bool:
        return bool(self.items)

    def take(self) -> list[Item]:
        """loop 在每次调模型前取走：每句变成一条用户消息。"""
        out, self.items = self.items, []
        self.taken += len(out)
        return out


_open: dict[str, Inbox] = {}


def open_inbox(conversation_id: str) -> Inbox:
    """登记这个对话的收件箱（同一对话一次只跑一轮，后登记的替换先登记的）；runner 开跑模型时才 start。"""
    box = Inbox(conversation_id)
    _open[conversation_id] = box
    return box


def close(box: Inbox | None) -> list[Item]:
    """收尾：不再收；返回没被读走的（调用方另起一轮回答）。"""
    if box is None:
        return []
    box.live = False
    if _open.get(box.conversation_id) is box:
        _open.pop(box.conversation_id, None)
    return box.take()


def reason(text: str, *, files: bool = False, skills: bool = False, command: bool = False) -> str | None:
    """这句话为什么不能插（None = 能插）。"""
    if not text.strip():
        return "empty"
    if files or skills or command:
        return "rich"
    if len(text) > STEER_CHARS:
        return "long"
    return None


def offer(conversation_id: str | None, text: str, message_id: str) -> Item | None:
    """把一句话交给正在跑的那一轮；没在跑 / 已收尾 / 这一轮插满了 → None（调用方排队成下一轮）。"""
    box = _open.get(conversation_id or "")
    if box is None or not box.live or box.taken + len(box.items) >= STEER_MAX:
        return None
    item = Item(text.strip(), message_id, datetime.now(timezone.utc))
    box.items.append(item)
    return item


def active(conversation_id: str | None) -> bool:
    box = _open.get(conversation_id or "")
    return box is not None and box.live
