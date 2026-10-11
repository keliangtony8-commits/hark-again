"""Agent 内核：想 → 用工具 → 再想 … → 说完。

只产出事件，不碰传输与存储。事件同时也是消息的“构建日志”：
MessageBuilder 把事件折叠成最终的块列表，存库与前端渲染用的是同一套块。
"""
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from ..llm import Turn, stream_turn
from .tools import REGISTRY, ToolContext, schemas

MAX_STEPS = 6  # 防止工具死循环烧钱


@dataclass
class BlockStart:
    index: int
    block: dict


@dataclass
class TextDelta:
    index: int
    text: str


@dataclass
class BlockUpdate:
    index: int
    block: dict


@dataclass
class ToolStatus:
    id: str
    name: str
    label: str
    state: str  # running | done | error


@dataclass
class Done:
    blocks: list[dict]


Event = BlockStart | BlockUpdate | TextDelta | ToolStatus | Done


@dataclass
class MessageBuilder:
    blocks: list[dict] = field(default_factory=list)
    _text_open: bool = False

    def text(self, delta: str) -> list[Event]:
        out: list[Event] = []
        if not self._text_open:
            self.blocks.append({"type": "text", "text": ""})
            self._text_open = True
            out.append(BlockStart(len(self.blocks) - 1, self.blocks[-1].copy()))
        self.blocks[-1]["text"] += delta
        out.append(TextDelta(len(self.blocks) - 1, delta))
        return out

    SINGLETONS = {"browser"}  # 一条回复里只需要一张的卡片（如浏览器实时画面）

    def has(self, block: dict) -> bool:
        return block["type"] in self.SINGLETONS and any(b["type"] == block["type"] for b in self.blocks)

    def add(self, block: dict) -> Event:
        self.blocks.append(block)
        self._text_open = False
        return BlockStart(len(self.blocks) - 1, block)

    def update(self, index: int, **changes) -> Event:
        self.blocks[index] = {**self.blocks[index], **changes}
        return BlockUpdate(index, self.blocks[index])

    def break_text(self) -> None:
        self._text_open = False

    def partial(self) -> list[dict]:
        """被打断时能落库的块：去掉空文字块，还在等的审批卡标为 expired（它再也等不到答复了）。"""
        out = []
        for b in self.blocks:
            if b["type"] == "text" and not b["text"].strip():
                continue
            out.append({**b, "state": "expired"} if b["type"] == "approval" and b.get("state") == "pending" else b)
        return out


async def run(system: str, history: list[dict], ctx: ToolContext,
              builder: MessageBuilder | None = None, model: str | None = None) -> AsyncIterator[Event]:
    """model = 实际调用的别名（None = 默认）。builder 可由调用方传入：中途被取消（用户点停止）时，调用方还能拿到已生成的半截块。"""
    messages = [{"role": "system", "content": system}, *history]
    builder = builder if builder is not None else MessageBuilder()
    tools = schemas(ctx)

    for step in range(MAX_STEPS):
        turn: Turn | None = None
        # 最后一步不给工具，强制模型收尾作答
        async for item in stream_turn(messages, tools if step < MAX_STEPS - 1 else None, model):
            if isinstance(item, Turn):
                turn = item
            else:
                for ev in builder.text(item):
                    yield ev
        assert turn is not None
        if not turn.tool_calls:
            break

        builder.break_text()
        messages.append({"role": "assistant", "content": turn.text or None, "tool_calls": [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
            for c in turn.tool_calls]})
        for call in turn.tool_calls:
            content = ""
            async for ev in _call_tool(call, ctx, builder):
                if isinstance(ev, str):
                    content = ev
                else:
                    yield ev
            messages.append({"role": "tool", "tool_call_id": call.id, "content": content})

    yield Done(builder.blocks)



async def _call_tool(call, ctx: ToolContext, builder: MessageBuilder):
    """执行一次工具调用：查表 → (需要时)审批 → 执行 → 产出事件，最后产出给模型的结果文本(str)。"""
    t = REGISTRY.get(call.name)
    if not t or not t.available(ctx):
        yield f"没有可用的工具 {call.name}。"
        return
    try:
        args = json.loads(call.arguments or "{}")
    except json.JSONDecodeError:
        yield "参数不是合法 JSON，请重试。"
        return

    if t.risk and (reason := t.risk(args)):
        approved = False
        async for ev in _ask_approval(builder, ctx, reason, args):
            if isinstance(ev, bool):
                approved = ev
            else:
                yield ev
        if not approved:
            yield "用户没有批准这个操作，已取消。不要换方式绕过，告诉用户即可。"
            return

    yield ToolStatus(call.id, call.name, t.label, "running")
    try:
        result = await t.run(ctx, **args)
    except Exception as e:  # 工具失败交给模型处理（换方法或如实告知）
        yield ToolStatus(call.id, call.name, t.label, "error")
        yield f"工具出错：{e}"
        return
    for b in result.blocks:
        if not builder.has(b):
            yield builder.add(b)
    yield ToolStatus(call.id, call.name, t.label, "done")
    yield result.content

async def _ask_approval(builder: MessageBuilder, ctx: ToolContext, reason: str, args: dict):
    """插入审批卡 → 等用户决定 → 更新卡片状态。最后产出 bool。"""
    aid = uuid.uuid4().hex
    detail = args.get("command") or json.dumps(args, ensure_ascii=False)[:500]
    yield builder.add({"type": "approval", "id": aid, "title": f"需要你批准：{reason}", "detail": detail, "state": "pending"})
    index = len(builder.blocks) - 1
    approved = await ctx.approve(aid, reason, detail)
    yield builder.update(index, state="approved" if approved else "rejected")
    yield approved
