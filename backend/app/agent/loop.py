"""Agent 内核：想 → 用工具 → 再想 … → 说完。

只产出事件，不碰传输与存储。事件同时也是消息的“构建日志”：
MessageBuilder 把事件折叠成最终的块列表，存库与前端渲染用的是同一套块。
"""
import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass, field

from .. import activity, browser_files, spill, vision
from ..config import settings
from ..llm import Reasoning, Turn, stream_turn
from .tools import REGISTRY, ToolContext, ToolResult, no_live, schemas

MAX_STEPS = 6  # 防止工具死循环烧钱
SELF_PAGED = {"read_file"}  # 自己按 offset 分页的工具，结果不再落盘截断


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
    state: str  # running | done | error | denied
    step: dict = field(default_factory=dict)  # 活动时间线的这一步（activity.py），客户端据此画时间线


@dataclass
class Thinking:
    """模型的思考片段：只用于“思考中”时给用户看进度，不进 MessageBuilder（不落库、不回传）。"""
    text: str


@dataclass
class Done:
    blocks: list[dict]


Event = BlockStart | BlockUpdate | TextDelta | ToolStatus | Thinking | Done


def carry(old: dict, new: dict) -> dict:
    """同一张单例卡（同会话的浏览器画面）换新时留下的历史：搬过的文件清单合并、接管条（新卡没带时）保留。
    别的块原样返回 new。"""
    if new.get("type") not in MessageBuilder.SINGLETONS or old.get("type") != new.get("type") \
            or old.get("session") != new.get("session"):
        return new
    out = dict(new)
    if old.get("files") or new.get("files"):
        out["files"] = browser_files.card_files(old.get("files"), new.get("files"))
        out["workspace"] = new.get("workspace") or old.get("workspace")
    if "handoff" not in out and old.get("handoff"):
        out["handoff"] = old["handoff"]
    return out


@dataclass
class MessageBuilder:
    blocks: list[dict] = field(default_factory=list)
    _text_open: bool = False
    timeline: activity.Recorder = field(default_factory=activity.Recorder)  # 这条回复的工具步骤（随回复落库）

    def text(self, delta: str) -> list[Event]:
        out: list[Event] = []
        if not self._text_open:
            self.blocks.append({"type": "text", "text": ""})
            self._text_open = True
            out.append(BlockStart(len(self.blocks) - 1, self.blocks[-1].copy()))
        self.blocks[-1]["text"] += delta
        out.append(TextDelta(len(self.blocks) - 1, delta))
        return out

    SINGLETONS = {"browser"}  # 一条回复里同一个会话只需要一张的卡片（浏览器实时画面：按 session 区分）

    def find(self, block: dict) -> int | None:
        """同一张单例卡已在回复里 → 它的位置。"""
        if block["type"] not in self.SINGLETONS:
            return None
        for i, b in enumerate(self.blocks):
            if b["type"] == block["type"] and b.get("session") == block.get("session"):
                return i
        return None

    def has(self, block: dict) -> bool:
        return self.find(block) is not None

    def add(self, block: dict) -> Event:
        self.blocks.append(block)
        self._text_open = False
        return BlockStart(len(self.blocks) - 1, block)

    def update(self, index: int, **changes) -> Event:
        self.blocks[index] = {**self.blocks[index], **changes}
        return BlockUpdate(index, self.blocks[index])

    def replace(self, index: int, block: dict) -> Event:
        """整块换掉（实时块换成最终块：旧字段如 live 不能残留）。单例卡换新时带上旧卡的历史（carry）。"""
        block = carry(self.blocks[index], block)
        self.blocks[index] = block
        self._text_open = False
        return BlockUpdate(index, block)

    def break_text(self) -> None:
        self._text_open = False

    def partial(self) -> list[dict]:
        """被打断时能落库的块：去掉空文字块，还在等的审批卡（含订单卡）标为 expired（它再也等不到答复了），
        还在跑的实时块去掉 live（命令已随这一轮被停掉），浏览器卡上还在等的接管条标 expired。"""
        out = []
        for b in self.blocks:
            if b["type"] == "text" and not b["text"].strip():
                continue
            if b.get("live"):
                b = {k: v for k, v in b.items() if k != "live"}
            if isinstance(h := b.get("handoff"), dict) and h.get("state") == "pending":
                b = {**b, "handoff": {**h, "state": "expired"}}  # 等用户接管的条：这一轮停了，再也等不到交还
            out.append({**b, "state": "expired"} if b.get("state") == "pending" and "id" in b else b)
        return out

    def steps(self, stopped: bool = False) -> list[dict]:
        return self.timeline.partial() if stopped else [dict(s) for s in self.timeline.steps]


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
            elif isinstance(item, Reasoning):
                yield Thinking(item.text)
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
        images = []
        for call in turn.tool_calls:
            result = ToolResult("")
            async for ev in _call_tool(call, ctx, builder):
                if isinstance(ev, ToolResult):
                    result = ev
                else:
                    yield ev
            images += result.images
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result.content})
        if images:  # 工具给了图：原图补一条消息，或描述并进最后一个工具结果（vision.for_tool 决定）
            note, msg = await vision.for_tool(images, model or settings.default_model)
            if note:
                messages[-1]["content"] += "\n\n" + note
            if msg:
                messages.append(msg)

    yield Done(builder.blocks)



async def _call_tool(call, ctx: ToolContext, builder: MessageBuilder):
    """执行一次工具调用：查表 → (需要时)审批 → 执行 → 产出事件，最后产出给模型的 ToolResult（文字 + 图）。"""
    t = REGISTRY.get(call.name)
    if not t or not t.available(ctx):
        yield ToolResult(f"没有可用的工具 {call.name}。")
        return
    try:
        args = json.loads(call.arguments or "{}")
    except json.JSONDecodeError:
        yield ToolResult("参数不是合法 JSON，请重试。")
        return
    if not isinstance(args, dict):
        yield ToolResult("参数要是一个 JSON 对象，请重试。")
        return
    rec = builder.timeline

    def denied(note: str) -> ToolStatus:
        return ToolStatus(call.id, call.name, t.label, "denied", rec.denied(call.id, call.name, t.label, args, note))

    if t.risk and (reason := t.risk(args, ctx)):
        try:
            card = t.card(args) if t.card else None
        except (ValueError, TypeError) as e:  # 卡片画不出来 = 参数不对，先让模型改，不打扰用户
            yield ToolResult(f"参数有误：{e}")
            return
        approved = False
        async for ev in _ask_approval(builder, ctx, reason, args, card):
            if isinstance(ev, bool):
                approved = ev
            else:
                yield ev
        if not approved:
            yield denied("你没有批准")
            yield ToolResult("用户没有批准这个操作，已取消。不要换方式绕过，告诉用户即可。")
            return

    if t.form:
        args.pop("form", None)  # 表单值只能来自用户，不能来自模型
        reply = None
        async for ev in _ask_form(builder, ctx, t, args):
            if isinstance(ev, Asked):
                reply = ev
            else:
                yield ev
        if reply is not None:
            if reply.reply is None:
                yield denied("你没有填写")
                yield ToolResult("用户没有填写，已取消。可以问问用户想怎么办，不要反复弹表单。")
                return
            args["form"] = reply.reply

    yield ToolStatus(call.id, call.name, t.label, "running", rec.start(call.id, call.name, t.label, args))
    live = _Live(builder)
    try:
        async with aclosing(live.run(t.run(ctx, **args), ctx)) as events:
            async for ev in events:
                yield ev
        result = live.result
    except Exception as e:  # 工具失败交给模型处理（换方法或如实告知）
        if (ev := live.settle()) is not None:
            yield ev
        yield ToolStatus(call.id, call.name, t.label, "error", rec.finish(call.id, "error", str(e)) or {})
        yield ToolResult(f"工具出错：{e}")
        return
    blocks = list(result.blocks)
    if (ev := live.settle(blocks.pop(0) if blocks and live.index is not None else None)) is not None:
        yield ev
    for b in blocks:
        if (i := builder.find(b)) is not None:  # 同会话的浏览器卡已在回复里：换成最新状态（carry 保留历史）
            yield builder.replace(i, b)
        else:
            yield builder.add(b)
    state = "error" if result.failed else "done"
    yield ToolStatus(call.id, call.name, t.label, state, rec.finish(call.id, state, result.failed, result.change) or {})
    content = result.content
    if call.name not in SELF_PAGED:  # 太长：开头 + 结尾给模型，全文落盘（spill.py）
        content = spill.bound(content, settings.tool_result_max, ctx.workspace, call.name)
    yield ToolResult(content, images=result.images)

class _Live:
    """一次工具执行期间的实时块：工具 ctx.live(block) 推来的，第一次插入回复，之后原地替换。
    工具协程跑在独立 task 里，这样执行中也能把事件交出去；这一轮被取消时 task 跟着取消（沙盒那头随连接断开杀命令）。"""

    def __init__(self, builder: MessageBuilder):
        self.builder, self.index, self.result = builder, None, ToolResult("")

    async def run(self, coro, ctx: ToolContext):
        q: asyncio.Queue[dict] = asyncio.Queue()
        ctx.live = q.put_nowait
        task = asyncio.create_task(coro)
        try:
            while True:
                getter = asyncio.create_task(q.get())
                await asyncio.wait({task, getter}, return_when=asyncio.FIRST_COMPLETED)
                if not getter.done():
                    getter.cancel()
                    break
                block = getter.result()
                while not q.empty():  # 积压了就只要最新的
                    block = q.get_nowait()
                yield self._show(block)
            self.result = task.result()  # 工具抛的异常从这里出去
        finally:
            ctx.live = no_live
            if not task.done():
                task.cancel()

    def _show(self, block: dict) -> Event:
        if self.index is None and (i := self.builder.find(block)) is not None:
            self.index = i  # 单例卡（同会话的浏览器画面）已经在回复里：原地更新它，不再插第二张
        if self.index is None:
            ev = self.builder.add(block)
            self.index = len(self.builder.blocks) - 1
            return ev
        return self.builder.replace(self.index, block)

    def settle(self, final: dict | None = None) -> Event | None:
        """收尾：有最终块就换上；没有就把最后一次推的去掉 live 留着。没推过实时块 → None。"""
        if self.index is None:
            return None
        if final is None:
            final = {k: v for k, v in self.builder.blocks[self.index].items() if k != "live"}
        return self.builder.replace(self.index, final)


@dataclass
class Asked:
    reply: object  # FormReply | None（None = 取消）


async def _ask_form(builder: MessageBuilder, ctx: ToolContext, t, args: dict):
    """需要时插入表单卡 → 等用户填 → 卡片标 submitted / cancelled。最后产出 Asked；不用问就什么都不产出。
    login / code 卡上只留字段的说明，用户填的值不进卡片；info 卡提交后附上 answers（form_answers）。"""
    spec = await t.form(ctx, args)
    if not spec:
        return
    fid = uuid.uuid4().hex
    yield builder.add({**spec, "id": fid, "state": "pending"})
    index = len(builder.blocks) - 1
    reply = await ctx.ask(fid, builder.blocks[index])
    extra = {"answers": form_answers(spec, reply.values)} if reply is not None and spec.get("purpose") == "info" else {}
    yield builder.update(index, state="submitted" if reply is not None else "cancelled", **extra)
    yield Asked(reply)


def form_answers(spec: dict, values: dict[str, str]) -> list[dict]:
    """info 卡（用户有意告诉助手的）提交后回显在卡片上的问答，按卡上字段顺序；空着的选填不列。
    login / code 卡从不调用它：那些值不能进卡片。"""
    return [{"label": f["label"], "value": values[f["name"]].strip()}
            for f in spec["fields"] if values.get(f["name"], "").strip()]


async def _ask_approval(builder: MessageBuilder, ctx: ToolContext, reason: str, args: dict, card: dict | None = None):
    """插入审批卡（或工具自己的确认卡，如订单卡）→ 等用户决定 → 更新卡片状态。最后产出 bool。"""
    aid = uuid.uuid4().hex
    detail = args.get("command") or json.dumps(args, ensure_ascii=False)[:500]
    block = {**card, "id": aid, "state": "pending"} if card else \
        {"type": "approval", "id": aid, "title": f"需要你批准：{reason}", "detail": detail, "state": "pending"}
    yield builder.add(block)
    index = len(builder.blocks) - 1
    approved = await ctx.approve(aid, reason, detail)
    yield builder.update(index, state="approved" if approved else "rejected")
    yield approved
