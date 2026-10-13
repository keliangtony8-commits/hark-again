"""一轮对话的完整流程：组装上下文 → 跑内核 → 推事件 → 存回复。
聊天（WebSocket）和定时任务（worker）共用它，区别只在 emit 和审批策略。"""
import asyncio
import contextlib
from collections.abc import Awaitable, Callable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import host_mode, jobs, plan_mode, llm_retry, model_router, reasoning, router_stats, steering, turn_changes, turn_journal, usage, vision
from ..llm import chat_model
from ..blocks import text_to_blocks
from ..config import settings
from ..models import Conversation, Message
from ..storage import project_dir
from ..workspaces import of as workspace_of
from . import loop
from ..prompt_cache import STABLE, VOLATILE
from .context import build_history, build_system_prompt
from .tools import Approver, Asker, ToolContext, deny_all, nobody

Emit = Callable[[dict], Awaitable[None]]


async def _silent(_: dict) -> None:
    pass


def to_wire(ev: loop.Event) -> dict:
    """内核事件 → 前端协议。"""
    match ev:
        case loop.BlockStart(index, block):
            return {"type": "block.start", "index": index, "block": block}
        case loop.BlockUpdate(index, block):
            return {"type": "block.update", "index": index, "block": block}
        case loop.TextDelta(index, text):
            return {"type": "block.delta", "index": index, "text": text}
        case loop.ToolStatus(id, name, label, state, step):
            return {"type": "tool.status", "id": id, "name": name, "label": label, "state": state, "step": step}
        case loop.Thinking(text):
            return {"type": "thinking.delta", "text": text}
        case loop.Retry(attempt, max_, delay_ms, reason, code, fallback):
            out = {"type": "turn.retry", "attempt": attempt, "max": max_, "delay_ms": delay_ms, "reason": reason, "code": code}
            return {**out, "fallback": fallback, "fallback_label": settings.chat_models.get(fallback, fallback)} if fallback else out
    raise ValueError(ev)


def apply_model(conv: Conversation, model: object) -> None:
    """客户端随消息带来的模型选择：合法别名就记到对话上（下次、别的设备都沿用）；空串 = 回到默认；其它忽略。"""
    if model == "":
        conv.model = None
    elif model_router.choosable(model):
        conv.model = model


def apply_choice(conv: Conversation, event: dict) -> None:
    """消息 / 重新生成随带的“模型选择”（model + reasoning 一起，客户端改过才带）：各自合法就记到对话上，"" = 回默认。"""
    if "model" in event:
        apply_model(conv, event["model"])
    if "mode" in event:  # 计划模式开关（plan_mode.MODES；"" = default）
        mode = event["mode"] or plan_mode.DEFAULT
        if plan_mode.valid(mode):
            conv.mode = mode
    effort = event.get("reasoning")
    if effort == "":
        conv.reasoning = None
    elif reasoning.valid(effort):
        conv.reasoning = effort


class RewindError(ValueError):
    """不能重新生成；消息直接给用户看。"""


async def rewind(db: AsyncSession, conversation_id: str, message_id: str | None,
                 text: str | None = None) -> tuple[Conversation, Message, list[str]]:
    """重新生成的准备：删掉最后一条用户消息之后的回复，返回 (对话, 那条用户消息, 被删的回复 id)。

    message_id = 客户端以为的“最后一条回复”；给了就必须真是最后一条（另一台设备可能已经接着聊了）。
    不给 = 上一轮失败、没有回复时的“重试”。不保留旧版本：省存储、历史给模型的也只有一条线。
    text = 编辑：把那条用户消息的文字换掉再答（原地改，id 不变；附件保留；对话标题不动——可能是用户自己起的）。"""
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        raise RewindError("对话不存在")
    rows = (await db.scalars(select(Message).where(Message.conversation_id == conv.id)
                             .order_by(Message.created_at))).all()
    last_user = next((i for i in range(len(rows) - 1, -1, -1) if rows[i].role == "user"), None)
    if last_user is None:
        raise RewindError("这个对话里还没有可以重新回答的消息")
    trailing = rows[last_user + 1:]
    if message_id is not None and (not trailing or trailing[-1].id != message_id):
        raise RewindError("这条回复已经不是最新的了，刷新后再试")
    user_msg = rows[last_user]
    if text is not None:
        files = [b for b in user_msg.blocks if b.get("type") == "file"
                 or (b.get("type") == "agent" and b.get("target"))]  # 附件、卡片上点的“追问”跟着这条消息走（@子助手 按新文字重认）
        if not text.strip() and not any(b.get("type") == "file" for b in files):
            raise RewindError("消息不能为空")
        user_msg.blocks = (text_to_blocks(text.strip()) if text.strip() else []) + files  # 整体赋值，JSON 列才会被标脏
    if conv.summary_upto in {user_msg.id, *(m.id for m in trailing)}:  # 正常不会发生（当前一问总是原文），防御
        conv.summary, conv.summary_upto = "", None
    for m in trailing:
        await db.delete(m)
    await db.commit()
    return conv, user_msg, [m.id for m in trailing]


async def run_turn(db: AsyncSession, conv: Conversation, emit: Emit = _silent,
                   approve: Approver = deny_all, stop: asyncio.Event | None = None,
                   ask: Asker = nobody, task_id: str | None = None, notice: str | None = None,
                   inbox: steering.Inbox | None = None) -> Message | None:
    """inbox：用户回答途中补充的话（steering.py；调用方开、关，这里只交给 loop）。
    task_id：worker 跑定时任务时传入，工具从 ToolContext.task_id 知道“这是哪个任务在跑”。
    notice：没有用户发言、由系统事件触发的一轮（后台任务结束，见 jobs.follow_ups）——作为最后一条“用户”消息
    交给模型，但不落库、不显示；回复照常存为助手消息。"""
    with usage.scope(conv.id):  # 这一轮里所有模型调用（含摘要、记忆向量）都记在这个对话上
        return await _run_turn(db, conv, emit, approve, stop, ask, task_id, notice, inbox)


async def _run_turn(db: AsyncSession, conv: Conversation, emit: Emit,
                    approve: Approver, stop: asyncio.Event | None, ask: Asker = nobody,
                    task_id: str | None = None, notice: str | None = None,
                    inbox: steering.Inbox | None = None) -> Message | None:
    """跑一轮并落库。被取消时不丢已生成的内容：半截回复以 status=stopped 存下，照常发 message.done；
    一个块都还没有就发 message.stopped。
    stop = 调用方在 cancel 前 set() 的信号：是用户点了停止 → 吞掉取消、正常返回（连接上的下一轮照跑）；
    否则（断线、关机）落库后把取消继续抛出去。"""
    cid, project_id, choice, effort, previous = conv.id, conv.project_id, chat_model(conv.model), conv.reasoning, conv.routed_model
    mode, seen, plan_path = plan_mode.normalize(conv.mode), conv.mode_seen, conv.plan_path  # 都在 build_history 之前读：摘要折叠的回滚会让 conv 过期
    await turn_journal.recover(db, cid)  # 别的进程崩掉留下的半截回答先转成 interrupted 消息，排在历史里
    hist = await build_history(db, cid, model_router.view(choice))
    history = hist.messages
    if notice:
        history = [*history, {"role": "user", "content": notice}]
    last_user = next((m for m in reversed(history) if m["role"] == "user"), None)
    query = vision.text_of(last_user["content"]) if last_user else ""
    model, tier = await _route(db, cid, choice, query, history, previous, last_user, bool(notice), emit)
    if choice == model_router.AUTO:
        effort = None  # 自动：思考强度跟着路由到的模型走默认档（客户端在“自动”下也不显示强度选择）
    prompt = await build_system_prompt(db, project_id, query)  # 稳定段在前、易变段在后（app/prompt_cache.py）
    host = await host_mode.enabled(db)  # 服务器主机模式：每轮读一次，用户在“我的电脑”里关掉后下一轮就没有 host_command
    if host:
        prompt.add(STABLE, host_mode.PROMPT)
    if mode == plan_mode.PLAN:  # 计划模式规则放稳定段：同一模式里每轮不变，前缀缓存照样命中
        prompt.add(STABLE, plan_mode.PROMPT)
    if plan_path and (approved := plan_mode.approved_path(project_dir(workspace_of(project_id)), plan_path)):  # 批准过的方案文件还在：每轮提一句（稳定段）
        prompt.add(STABLE, plan_mode.approved_prompt(approved, mode == plan_mode.PLAN))
    if switched := plan_mode.notice(seen, mode):  # 两轮之间用户切了模式：先告诉模型一句
        prompt.add(VOLATILE, switched)
    if seen != mode:
        await db.execute(update(Conversation).where(Conversation.id == cid).values(mode_seen=mode, updated_at=Conversation.updated_at))
        await db.commit()
    if hist.summary:  # 滚动摘要隔几轮就重写一次：放易变段
        prompt.add(VOLATILE, f"这段对话更早的内容（摘要，原文已不在下面）：\n{hist.summary}")
    if not notice and (held := await jobs.take_held(db, cid)):  # 叫醒轮数到上限时压下的任务结论（jobs.follow_ups）
        prompt.add(VOLATILE, held)
    system = prompt.text()
    builder = loop.MessageBuilder()
    journal = turn_journal.Journal(cid, task_id)  # 进程被杀时这一轮的进度还在（turn_journal.py）
    await journal.open()
    try:
        with usage.routing(tier):  # 自动轮的调用打上档位（router_stats 算省了多少）
            return await _drive(db, cid, project_id, system, history, builder, journal, emit, approve, stop, ask, task_id, host, model,
                                effort, plan_mode.State(active=mode == plan_mode.PLAN), inbox)
    finally:
        await journal.close()  # 走到这里结果已由 _drive 落库（或出错/没内容）；只有进程死掉才会留下检查点


async def _route(db: AsyncSession, cid: str, choice: str, query: str, history: list[dict], previous: str | None,
                 last_user: dict | None, notice: bool, emit: Emit) -> tuple[str, str | None]:
    """这一轮用哪个别名（model_router.route；不是 auto 原样返回、零开销）。选了 auto：记到对话上（下一轮接话沿用、
    客户端显示“自动 · 快速”）并推 turn.model，再记一行路由账（router_stats）。返回 (别名, 档位 | None)。
    一轮只定一次（Gemini currentSequenceModel）；备用模型切换仍归 loop。"""
    if choice != model_router.AUTO:
        return choice, None
    content = last_user["content"] if last_user else ""
    images = isinstance(content, list) and any(isinstance(p, dict) and p.get("type") == "image_url" for p in content)
    d = await model_router.route(choice, query, history, previous, images, notice)
    await db.execute(update(Conversation).where(Conversation.id == cid)
                     .values(routed_model=d.model, updated_at=Conversation.updated_at))
    await router_stats.record(db, cid, d)
    await db.commit()  # 下一次模型调用前提交（SQLite：没提交的写会让 usage.record 撞锁）
    await _try_emit(emit, model_router.wire(d))
    return d.model, d.complexity or None


async def _drive(db: AsyncSession, cid: str, project_id: str | None, system: str, history: list[dict], builder: loop.MessageBuilder,
                 journal: turn_journal.Journal, emit: Emit, approve: Approver, stop: asyncio.Event | None,
                 ask: Asker, task_id: str | None, host: bool, model: str,
                 effort: str | None = None, plan: plan_mode.State | None = None,
                 inbox: steering.Inbox | None = None) -> Message | None:
    status = "done"
    interrupted = False
    ctx = ToolContext(db=db, project_id=project_id, approve=approve, conversation_id=cid, ask=ask, task_id=task_id, host=host, effort=effort,
                      plan=plan)
    if inbox is not None:
        inbox.start(model)  # 历史已拼好：从这一刻起补充的话只经收件箱进来，不会和历史重复
    try:
        async for ev in loop.run(system, history, ctx, builder, model, inbox=inbox):
            if isinstance(ev, loop.Done):
                status = ev.ended  # wrapped / looped：内容是完整的一段交代，但事没做完（客户端给“继续”）
            else:
                await journal.seen(ev, builder)
                await emit(to_wire(ev))
    except asyncio.CancelledError:
        if (task := asyncio.current_task()) is not None:
            task.uncancel()
        status, interrupted = "stopped", not (stop and stop.is_set())
        with contextlib.suppress(Exception):
            await db.rollback()  # 工具可能停在半个事务里
    except Exception as e:  # 模型/网关错误：上报，不吞掉
        await emit({"type": "error", "message": llm_retry.user_text(e)})  # 重试也救不回来：说人话（鉴权 / 额度 / 太长 / …）
        return None
    if plan is not None and plan.exited:  # 这一轮方案被批准、已退出计划模式：客户端把“计划”钮关掉（在 message.done 之前）
        await _try_emit(emit, {"type": "conversation.mode", "conversation_id": cid, "mode": plan_mode.DEFAULT})
    blocks = builder.partial() if status == "stopped" else builder.final()
    if card := turn_changes.finish(ctx.changes, ctx.workspace):  # 这一轮改过的文件：净改动卡 + 整轮撤销（被停下也出）
        blocks = [*blocks, card]
    reply = None
    if blocks:
        reply = Message(conversation_id=cid, role="assistant", blocks=blocks, status=status,
                        steps=builder.steps(stopped=status == "stopped"), trace=builder.trace())
        db.add(reply)
        await journal.drop(db)  # 同一个事务：回复落库 = 检查点消失
        await db.commit()
        journal.dropped()
        await _try_emit(emit, {"type": "message.done", "message": reply.to_wire()})
    elif status == "stopped":
        await _try_emit(emit, {"type": "message.stopped", "conversation_id": cid})
    if interrupted:
        raise asyncio.CancelledError
    return reply


async def _try_emit(emit: Emit, event: dict) -> None:
    """收尾事件：断线导致的取消时连接已经没了，发不出去也不影响落库。"""
    with contextlib.suppress(Exception):
        await emit(event)
