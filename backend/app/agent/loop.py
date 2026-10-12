"""Agent 内核：想 → 用工具 → 再想 … → 说完。

只产出事件，不碰传输与存储。事件同时也是消息的“构建日志”：
MessageBuilder 把事件折叠成最终的块列表，存库与前端渲染用的是同一套块。
"""
import asyncio
import inspect
import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass, field

from .. import activity, browser_files, llm_retry, plan, plan_mode, spill, steering, vision
from ..config import settings
from ..llm import Reasoning, Turn, stream_turn
from . import approvals, compact, distill, loop_guard, next_speaker, parallel, supersede, tool_args, tool_mask, tool_trace
from .tools import REGISTRY, Approval, ToolContext, ToolResult, no_live, schemas

# 预算到了的最后一步：收掉工具，让模型交代进度（用户回“继续”就能接着做——上文里有这一轮做过的事）
WRAP_UP = ("[系统提示] 这一轮的步数/用量预算用完了，不能再调用工具。请直接回复用户：已经完成了什么、"
           "还差哪些没做、下一步打算怎么做；告诉用户回复“继续”你就接着做。")


@dataclass
class Limits:
    """一轮的预算。默认取 settings 的主助手预算；子助手（agent/subagent.py）给更小的步数 / token，外加截止时间。
    到了就走同一条收尾路：最后一步收掉工具 + wrap_up 提示（Gemini local-executor 的 final warning turn）。wrapped = 真的收尾过。"""
    max_steps: int = 0
    turn_tokens: int = 0
    deadline: float | None = None  # time.monotonic() 截止；None = 不按时间
    wrap_up: str = WRAP_UP
    wrapped: bool = False

    @classmethod
    def default(cls) -> "Limits":
        return cls(settings.agent_max_steps, settings.agent_turn_tokens)


SKIPPED = "没有执行：同一批里前面的调用已被判定为原地打转。"
SKIPPED_BAD = "没有执行：前面已经连续多次写错参数，这一轮先停下。"
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
class Retry:
    """模型调用失败、正在自动重试（llm_retry.py）：只给客户端一行临时提示，不进 MessageBuilder、不落库。
    attempt/max = 第几次 / 最多几次；delay_ms = 等多久再试；fallback = 重试用完、这一轮改用的备用模型别名（此时 attempt=0）。"""
    attempt: int
    max: int
    delay_ms: int
    reason: str
    code: str
    fallback: str | None = None


# 一轮怎么结束的（Done.ended → 消息 status；客户端据此给“继续”）：done 正常说完 / wrapped 预算用完收尾 / looped 原地打转被叫停
ENDINGS = ("done", "wrapped", "looped")


@dataclass
class Done:
    blocks: list[dict]
    ended: str = "done"


Event = BlockStart | BlockUpdate | TextDelta | ToolStatus | Thinking | Retry | Done


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


def settle_blocks(blocks: list[dict]) -> list[dict]:
    """被打断的回复能落库的块（用户停止、断线，以及 turn_journal 崩溃恢复共用这一条规则）：
    去掉空文字块，还在等的审批卡（含订单卡）标为 expired（它再也等不到答复了），
    还在跑的实时块去掉 live（命令已随这一轮被停掉），浏览器卡上还在等的接管条标 expired。"""
    out = []
    for b in blocks:
        if b["type"] == "text" and not b["text"].strip():
            continue
        if b.get("live"):
            b = {k: v for k, v in b.items() if k != "live"}
        if isinstance(h := b.get("handoff"), dict) and h.get("state") == "pending":
            b = {**b, "handoff": {**h, "state": "expired"}}  # 等用户接管的条：这一轮停了，再也等不到交还
        b = plan.settle(b)  # 计划卡定格：没做完的步骤不再闪“进行中”
        if b.get("type") == "delegate":  # 子任务卡：还在做的随这一轮一起停了（subagent.run_all 的取消可能还没轮到）
            b = {**b, "tasks": [{**{k: v for k, v in t.items() if k != "now"}, "state": "stopped"}
                                if t.get("state") == "running" else t for t in b.get("tasks") or []]}
        out.append({**b, "state": "expired"} if b.get("state") == "pending" and "id" in b else b)
    return out


@dataclass
class MessageBuilder:
    blocks: list[dict] = field(default_factory=list)
    _text_open: bool = False
    timeline: activity.Recorder = field(default_factory=activity.Recorder)  # 这条回复的工具步骤（随回复落库）
    transcript: list[dict] | None = None  # run() 的消息列表本身（引用）：收尾时 tool_trace.record 从 base 起取这一轮的工具轨迹
    base: int = 0

    def text(self, delta: str) -> list[Event]:
        out: list[Event] = []
        if not self._text_open:
            self.blocks.append({"type": "text", "text": ""})
            self._text_open = True
            out.append(BlockStart(len(self.blocks) - 1, self.blocks[-1].copy()))
        self.blocks[-1]["text"] += delta
        out.append(TextDelta(len(self.blocks) - 1, delta))
        return out

    SINGLETONS = {"browser", "plan"}  # 一条回复里只需要一张的卡片：浏览器实时画面（按 session 区分）、计划清单（plan.py）

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

    def mark(self) -> tuple[int, str, bool]:
        """一次模型调用开始前的文字状态：调用失败要重试时，据它撤回这次已经吐出去的半截文字（rollback）。"""
        last = self.blocks[-1]["text"] if self._text_open and self.blocks else ""
        return len(self.blocks), last, self._text_open

    def rollback(self, mark: tuple[int, str, bool]) -> list[Event]:
        """撤回 mark 之后流出来的文字（失败的半截输出不进回复、不回传模型——deepseek-harness llm-retry）。
        客户端已按下标收到块，不能删块：新开的文字块清空并保持打开（重试的文字接着写进同一块），
        原来开着的块恢复成当时的文字。流式期间只会产生文字，不会有别的块。"""
        count, last, was_open = mark
        out: list[Event] = []
        if len(self.blocks) > count:  # 这次新开了一个文字块
            for i in range(count, len(self.blocks)):
                if self.blocks[i]["type"] == "text" and self.blocks[i]["text"]:
                    self.blocks[i] = {"type": "text", "text": ""}
                    out.append(BlockUpdate(i, dict(self.blocks[i])))
            self._text_open = self.blocks[-1]["type"] == "text"
        elif was_open and self.blocks and self.blocks[-1]["text"] != last:
            self.blocks[-1] = {**self.blocks[-1], "text": last}
            out.append(BlockUpdate(len(self.blocks) - 1, dict(self.blocks[-1])))
        return out

    def final(self) -> list[dict]:
        """正常说完时落库的块：去掉空文字块（重试撤回后可能留下的空壳）。"""
        return [b for b in self.blocks if not (b["type"] == "text" and not b["text"].strip())]

    def partial(self) -> list[dict]:
        """被打断时能落库的块（规则见 settle_blocks）。"""
        return settle_blocks(self.blocks)

    def settle(self) -> list[Event]:
        """这一轮正常说完：计划卡定格（plan.settle）。"""
        out: list[Event] = []
        for i, b in enumerate(self.blocks):
            if b.get("type") == "plan" and not b.get("settled"):
                self.blocks[i] = plan.settle(b)
                out.append(BlockUpdate(i, self.blocks[i]))
        return out

    def steps(self, stopped: bool = False) -> list[dict]:
        return self.timeline.partial() if stopped else [dict(s) for s in self.timeline.steps]

    def trace(self, missing=tool_trace.ABORTED) -> list[dict]:
        """这一轮的工具轨迹（跨轮保留，规则在 tool_trace.py）；missing 见 tool_trace.record（崩溃检查点用）。"""
        return tool_trace.record(self.transcript, self.base, missing=missing) if self.transcript is not None else []


async def run(system: str, history: list[dict], ctx: ToolContext,
              builder: MessageBuilder | None = None, model: str | None = None,
              limits: Limits | None = None, inbox: steering.Inbox | None = None) -> AsyncIterator[Event]:
    """model = 实际调用的别名（None = 默认）。limits = 这一轮的预算（None = 主助手默认）。builder 可由调用方传入：中途被取消（用户点停止）时，调用方还能拿到已生成的半截块。
    inbox = 用户回答途中补充的话（steering.py）：每次调模型前读进来；模型要收尾时还有没读的就再来一圈（Codex needs_follow_up）。"""
    messages = [{"role": "system", "content": system}, *history]
    builder = builder if builder is not None else MessageBuilder()
    builder.transcript, builder.base = messages, len(messages)  # 被停下时调用方也能拿到已经发生的调用
    limits = limits or Limits.default()
    if ctx.model is None:
        ctx.model = model or settings.default_model
    tools = schemas(ctx)
    seen = supersede.Tracker()  # 旧页面快照 / 截图只留最新一份（supersede.py）

    streak = tool_args.Streak()  # 连续写错参数：第 3 次附完整签名，第 6 次停下（tool_args.py）
    guard = loop_guard.LoopGuard()  # 原地打转：第一次提醒模型，第二次停下（loop_guard.py）
    squeeze = compact.Compactor(len(messages), model, tools,
                                pinned=lambda: plan.pinned(builder.blocks), effort=ctx.effort)  # 上文快满：剪长工具结果 / 压成检查点（compact.py）
    overflowed = False  # 供应商报“上文超长”时强制压一次再重试；成功调用一次后复位
    retry_policy, retries, tried = llm_retry.policy(), 0, {model or settings.default_model}  # 调用失败的重试（llm_retry.py）
    max_steps, spent, step = max(1, limits.max_steps), 0, 0
    ended = "done"
    nudges, used_tools = next_speaker.limit(), False  # 话说一半就停：替用户补“继续”的剩余次数（next_speaker.py）
    while True:
        if inbox is not None and inbox.pending():  # 用户在途中补了话：作为新的用户消息接在后面（Codex pending input）
            builder.break_text()
            messages += [{"role": "user", "content": it.text} for it in inbox.take()]
        over = step >= max_steps - 1 or 0 < limits.turn_tokens <= spent \
            or (limits.deadline is not None and time.monotonic() >= limits.deadline)
        if over and step:  # 预算到了：最后一步不给工具，让模型交代进度（第一步就是最后一步时不用交代）
            messages.append({"role": "user", "content": limits.wrap_up})
            limits.wrapped = True
        if ctx.plan is not None and ctx.plan.lifted:  # 方案刚被批准：系统提示里的计划模式规则拿掉（plan_mode.lift_prompt）
            plan_mode.lift_prompt(messages)
            ctx.plan.lifted = False
        seen.apply(messages)
        if tool_mask.enabled():  # 较早的大块工具结果 → 预览 + 全文文件（tool_mask.py，无损；攒够一批才动）
            tool_mask.mask(messages, ctx.workspace, builder.base)
        if squeeze.due(messages):
            async for ev in _compact(squeeze, messages, seen, builder):
                yield ev
        turn: Turn | None = None
        said, chant = "", 0
        at = len(messages)
        mark = builder.mark()
        try:
            async with aclosing(stream_turn(messages, None if over else tools, model, ctx.effort)) as items:
                async for item in items:
                    if isinstance(item, Turn):
                        turn = item
                    elif isinstance(item, Reasoning):
                        yield Thinking(item.text)
                    else:
                        said += item
                        for ev in builder.text(item):
                            yield ev
                        if chant := guard.content(item):
                            break  # 复读：不等它说完（关闭流，已花的 token 照记）
        except Exception as e:
            failure = llm_retry.classify(e)
            if failure.code != llm_retry.CONTEXT and not compact.is_overflow(e):
                retries += 1
                delay = llm_retry.next_delay(retry_policy, failure, retries)
                fallback = None if delay is not None else \
                    (llm_retry.fallback_for(model or settings.default_model, tried) if llm_retry.can_fall_back(failure) else None)
                if delay is None and fallback is None:
                    if failure.code == llm_retry.EMPTY:  # 空答复重试用完：照旧收下（这一步什么也没说），不当成错误
                        turn = Turn()
                    else:
                        raise
                else:
                    for ev in builder.rollback(mark):  # 半截输出撤回（Codex/deepseek：失败的部分不留在回复和上文里）
                        yield ev
                    guard.recovered()
                    if over and step:
                        messages.pop()  # WRAP_UP 下一圈会重新加
                    if fallback:  # Gemini onPersistent429：换备用模型，次数清零
                        model, retries = fallback, 0
                        tried.add(fallback)
                        ctx.model = fallback
                        squeeze.model = fallback  # 换了模型：思考强度按备用模型的档位重新解析（reasoning.resolve）
                        yield Retry(0, retry_policy.max_retries, 0, llm_retry.reason(failure), failure.code, fallback)
                    else:
                        yield Retry(retries, retry_policy.max_retries, int(delay), llm_retry.reason(failure), failure.code)
                        await asyncio.sleep(delay / 1000)  # 用户点停止 = 任务取消，这里直接结束
                    continue
            elif overflowed or said:
                raise
            else:
                overflowed = True  # 上文超长：强制压一次，压动了就重试这一步（deepseek-harness overflow recovery）
                out: dict = {}
                async for ev in _compact(squeeze, messages, seen, builder, force=True, out=out):
                    yield ev
                if not out.get("changed"):
                    raise
                if over and step:
                    messages.pop()  # WRAP_UP 下一圈会重新加
                continue
        overflowed, retries = False, 0
        step += 1
        if chant:
            builder.break_text()
            if chant > 1 or over:
                for ev in builder.text(loop_guard.STOP_NOTE):
                    yield ev
                ended = "looped"
                break
            guard.recovered()
            messages += [{"role": "assistant", "content": said},
                         {"role": "user", "content": loop_guard.nudge(guard.detail)}]
            continue
        assert turn is not None
        spent += turn.tokens
        squeeze.observe(turn.prompt, at)
        if not turn.tool_calls or over:
            if not over and inbox is not None and inbox.pending():  # 正要收尾时用户补了话：再来一圈读它（没读的不会被丢）
                if said.strip():
                    messages.append({"role": "assistant", "content": said})
                continue
            if not turn.tool_calls and not over and nudges > 0 and step < max_steps - 1 \
                    and await next_speaker.decide(said, turn.cut, used_tools, messages):
                nudges -= 1  # 说了要做却没做 / 被截断 / 用完工具一句没说：补一句“继续”再来一圈（Gemini client.ts）
                builder.break_text()
                if said.strip():
                    messages.append({"role": "assistant", "content": said})
                messages.append({"role": "user", "content": next_speaker.CONTINUE})
                continue
            break
        used_tools = True

        builder.break_text()
        parsed = {c.id: tool_args.parse(c.arguments, turn.cut) for c in turn.tool_calls}
        messages.append({"role": "assistant", "content": turn.text or None, "tool_calls": [
            {"id": c.id, "type": "function",
             "function": {"name": c.name, "arguments": tool_args.wire(parsed[c.id]) or c.arguments}}
            for c in turn.tool_calls]})
        images, browser_only, hit = [], True, 0
        calls = turn.tool_calls
        # 连续的只读调用一组同时跑，其余一个一组按顺序（agent/parallel.py）；结果一律按模型顺序放回
        for group in parallel.groups([parallel.eligible(c.name, parsed[c.id], ctx) for c in calls]):
            if hit or streak.stopped:  # 已判定打转 / 连续写错：后面的调用不再执行（每个调用仍要有一条结果）
                messages += [{"role": "tool", "tool_call_id": calls[i].id, "content": SKIPPED if hit else SKIPPED_BAD}
                             for i in group]
                continue
            results: dict[int, ToolResult] = {}
            if len(group) == 1:
                call = calls[group[0]]
                results[group[0]] = ToolResult("")
                async for ev in _call_tool(call, ctx, builder, parsed[call.id], streak):
                    if isinstance(ev, ToolResult):
                        results[group[0]] = ev
                    else:
                        yield ev
            else:
                def start(k: int, group=group):
                    c = calls[group[k]]
                    return _call_tool(c, parallel.isolated(ctx), builder, parsed[c.id], streak)
                async with aclosing(parallel.pool(len(group), start)) as events:
                    async for ev in events:
                        if isinstance(ev, parallel.Settled):
                            results[group[ev.index]] = ev.result
                        else:
                            yield ev
            for i in group:  # 同一组的都已经真跑过：全部按顺序提交；打转判定只看到第一次命中为止
                call, result = calls[i], results[i]
                images += result.images
                browser_only &= not result.images or call.name.startswith("browser_")
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result.content})
                seen.note(messages, len(messages) - 1, call.name)
                if not hit:
                    hit = guard.tool(call.name, _args(call.arguments), result.content)
        if images:  # 工具给了图：原图补一条消息，或描述并进最后一个工具结果（vision.for_tool 决定）
            note, msg = await vision.for_tool(images, model or settings.default_model)
            if note:
                messages[-1]["content"] += "\n\n" + note
            if msg:
                messages.append(msg)
                if browser_only:
                    seen.note_image(len(messages) - 1)
        if hit > 1 or streak.stopped:
            for ev in builder.text(loop_guard.STOP_NOTE if hit > 1 else tool_args.STOP_NOTE):
                yield ev
            ended = "looped"
            break
        if hit:
            guard.recovered()
            messages.append({"role": "user", "content": loop_guard.nudge(guard.detail)})

    for ev in builder.settle():
        yield ev
    if ended == "done" and limits.wrapped:
        ended = "wrapped"
    yield Done(builder.blocks, ended)



async def _compact(squeeze: compact.Compactor, messages: list[dict], seen: supersede.Tracker,
                   builder: MessageBuilder, force: bool = False, out: dict | None = None):
    """压一次上文；时间线上一步“整理上文”（写摘要要十几秒，先亮 running）。out["changed"] = 是否真的压动了。"""
    sid = f"compact-{uuid.uuid4().hex[:8]}"
    rec = builder.timeline
    yield ToolStatus(sid, "compact_context", "正在整理上文", "running",
                     rec.start(sid, "compact_context", "正在整理上文", {"reason": "上文快满了，整理较早的步骤"}))
    info = await squeeze.maybe(messages, force=force)
    if info and info["folded"]:
        seen.splice(info["start"], info["end"])
    if out is not None:
        out["changed"] = info is not None
    detail = compact.describe(info) if info else "上文已经很精简，没有可整理的"
    yield ToolStatus(sid, "compact_context", "正在整理上文", "done", rec.finish(sid, "done", detail=detail) or {})


def _args(raw: str) -> object:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return raw


async def _call_tool(call, ctx: ToolContext, builder: MessageBuilder, parsed: tool_args.Parsed | None = None,
                     streak: tool_args.Streak | None = None):
    """执行一次工具调用：查表 → 参数解析与校验（agent/tool_args.py）→ (需要时)审批 → 执行 → 产出事件，
    最后产出给模型的 ToolResult（文字 + 图）。参数不对不进审批、不进时间线：直接把原因还给模型改。"""
    t = REGISTRY.get(call.name)
    if not t or not t.available(ctx):
        names = [x.name for x in REGISTRY.values() if x.available(ctx)]
        hint = streak.fail(call.name, names=names) if streak else ""
        yield ToolResult(f"没有可用的工具 {call.name}。{tool_args.suggest(call.name, names)}".rstrip() + hint)
        return
    streak = streak or tool_args.Streak()
    parsed = parsed or tool_args.parse(call.arguments)
    if parsed.args is None:
        yield ToolResult(parsed.error + streak.fail(call.name, t.parameters))
        return
    args = dict(parsed.args)
    args.pop("grant", None)  # 批准范围只能来自用户在卡上的选择，不能来自模型
    if t.form:
        args.pop("form", None)  # 表单值只能来自用户，不能来自模型
    checked = tool_args.check(t.parameters, args, t.accepts)
    if checked.error:
        yield ToolResult(checked.error + streak.fail(call.name, t.parameters))
        return
    streak.ok(call.name)
    args = checked.args
    notes = ([parsed.repaired] if parsed.repaired else []) + checked.notes
    rec = builder.timeline

    def denied(note: str) -> ToolStatus:
        return ToolStatus(call.id, call.name, t.label, "denied", rec.denied(call.id, call.name, t.label, args, note))

    if why := plan_mode.refusal(call.name, args, ctx.plan):  # 计划模式只放只读工具（Gemini plan.toml 硬拦，不靠模型自觉）
        if call.name != plan_mode.TOOL:
            yield denied("计划模式下不执行")
        yield ToolResult(why)
        return
    gate = t.risk(args, ctx) if t.risk else None
    if inspect.isawaitable(gate):  # 要查库才知道问不问的（主机命令的已存规则）
        gate = await gate
    card_at = None  # 用户批准过的卡在回复里的位置：执行结果要补进卡的字段（ToolResult.card）合并到它
    if gate:
        ask = gate if isinstance(gate, Approval) else Approval(gate)
        try:
            card = ask.card if ask.card is not None else (t.card(args) if t.card else None)
        except (ValueError, TypeError) as e:  # 卡片画不出来 = 参数不对，先让模型改，不打扰用户
            yield ToolResult(f"参数有误：{e}")
            return
        grant = None
        async for ev in _ask_approval(builder, ctx, ask.reason, args, card):
            if isinstance(ev, Granted):
                grant, card_at = ev.option, ev.index
            else:
                yield ev
        if grant is None:
            yield denied("你没有批准")
            yield ToolResult(ask.rejected or "用户没有批准这个操作，已取消。不要换方式绕过，告诉用户即可。")
            return
        if t.grants:
            args["grant"] = grant

    if t.form:
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

    if t.quiet:  # 控制类工具：不进时间线，结果块直接上卡（同单例原地换）
        async for ev in _quiet(t, call, ctx, builder, args, card_at):
            yield ToolResult(_with_notes(ev.content, notes), ev.blocks, ev.images) if isinstance(ev, ToolResult) else ev
        return
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
    if result.card and card_at is not None:
        yield builder.update(card_at, **result.card)
    state = "error" if result.failed else "done"
    yield ToolStatus(call.id, call.name, t.label, state, rec.finish(call.id, state, result.failed, result.change) or {})
    content = _with_notes(result.content, notes)
    if call.name not in SELF_PAGED:  # 太长：开头 + 结尾给模型，全文落盘（spill.py）；日志型再补中间段要点（distill.py）
        content = await distill.bound(content, settings.tool_result_max, ctx.workspace, call.name, ctx.db)
    yield ToolResult(content, images=result.images)

def _with_notes(content: str, notes: list[str]) -> str:
    """参数层（tool_args）做过的修补/丢弃附在结果末尾，模型下次就会写对。"""
    return f"{content}\n\n（{'；'.join(notes)}）" if notes else content


async def _quiet(t, call, ctx: ToolContext, builder: MessageBuilder, args: dict, card_at: int | None = None):
    try:
        result = await t.run(ctx, **args)
    except Exception as e:
        yield ToolResult(f"工具出错：{e}")
        return
    if result.card and card_at is not None:
        yield builder.update(card_at, **result.card)
    for b in result.blocks:
        i = builder.find(b)
        yield builder.replace(i, b) if i is not None else builder.add(b)
    yield ToolResult(result.content)


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


@dataclass
class Granted:
    index: int   # 卡在回复里的位置（执行后 ToolResult.card 合并进去）
    option: str  # 用户选的批准范围（卡上 options 的 id；没有选项的卡 = "once"）


async def _ask_approval(builder: MessageBuilder, ctx: ToolContext, reason: str, args: dict, card: dict | None = None):
    """插入审批卡（或工具自己的确认卡，如订单卡、主机命令卡）→ 等用户决定 → 更新卡片状态。
    批准了最后产出 Granted(选项)；拒绝/超时什么也不产出。卡上有 options 时用户选的那个记进卡（granted），不在选项里的一律当“仅这一次”。"""
    aid = uuid.uuid4().hex
    detail = args.get("command") or json.dumps(args, ensure_ascii=False)[:500]
    block = {**card, "id": aid, "state": "pending"} if card else \
        {"type": "approval", "id": aid, "title": f"需要你批准：{reason}", "detail": detail, "state": "pending"}
    yield builder.add(block)
    index = len(builder.blocks) - 1
    approved = await ctx.approve(aid, reason, detail)
    choices = [o.get("id") for o in block.get("options") or []]
    option = approvals.take_option(aid)
    if not approved:
        yield builder.update(index, state="rejected")
        return
    option = option if option in choices else (choices[0] if choices else "once")
    yield builder.update(index, state="approved", **({"granted": option} if choices else {}))
    yield Granted(index, option)
