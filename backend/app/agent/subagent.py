# Portions Copyright 2026 Google LLC — Apache-2.0 (modified).
# Ported from google-gemini/gemini-cli packages/core/src/agents/local-executor.ts + generalist-agent.ts (Apache-2.0), modified:
#   子助手 = 同一个内核跑一轮独立上下文（自己的消息列表），工具从主助手的注册表里按名单挑（不含派活工具本身 → 不会递归），
#   有步数 / 时间上限（generalist：20 轮、10 分钟），到了先给“最后一次机会”交代结果（final warning turn → 这里是 loop.Limits
#   的 wrap_up：收掉工具、让它写结论），再兜一个宽限期的硬超时（GRACE_PERIOD_MS 60 s）；执行中把它的动作推给主界面（onActivity）。
# 嫁接：deepseek-harness tool-subagent（MIT）——“全新上下文的子助手要拿到自成一体的任务说明”的措辞、深度上限（默认 1）、
#       “互相独立的委派放在同一条消息里一起发”；Codex multi_agents（Apache-2.0）——何时委派 / 不委派的指引
#       （关键路径上马上要用的结果自己做、只派边界清楚的旁路活、不重复劳动），子助手沿用主助手的模型，并行上限的思路。
# v1.97 续问：tasks 项带 continue = 之前某个子助手的 id，就用它存下的上下文接着问（Codex resume_agent 的冷恢复，
#       上下文的存取规则在 agent/subagent_threads.py）。
# 不采纳：deepseek / Codex 的异步激活 + wait / send_input / close（一轮回复里等结果就够，手机上也看得懂；省掉一整套生命周期管理）、
#       Gemini 的 complete_task 强制工具（我们的内核本来就以“不再调工具的那句回复”收尾）。
# 我们加的：非交互（不能问用户、需要批准的操作直接拒绝并让它把要做的事写进结果）、不开浏览器（共用会话会抢页面）、
#       每个子助手独立数据库会话（并行时不共用一个 AsyncSession）、聊天里一张实时“子任务”卡片。
"""子助手（唯一规则）：delegate 工具把几件互相独立的事并行交给子助手，各自在独立上下文里做完，只把结论交回主助手。

块：{"type": "delegate", "tasks": [{"id"?, "round"?, "title", "state", "steps", "now"?, "seconds"?, "result"?, "note"?}], "live"?}
id = 子助手编号（sa_xxxxxx，续问用）；round = 这是它第几轮（≥2 才给，续问的那次）。
state：running 在做 | done 做完 | partial 预算 / 时间到了、交了半截 | failed 出错或超时 | stopped 这一轮被停掉。
"""
import asyncio
import time
from dataclasses import dataclass, field

from .. import plan_mode
from ..config import settings
from ..db import SessionLocal
from . import loop, subagent_threads as threads
from ..prompt_cache import STABLE
from .context import build_system_prompt
from .tools import ToolContext

TITLE_MAX = 24
PROMPT_MAX = 8000
RESULT_MAX = 6000       # 每个子助手交回给主助手的结论最多多少字
CARD_RESULT_MAX = 2000  # 卡片上展开能看到的结论
GRACE_SECONDS = 60      # 截止时间之后再等多久（最后一步在写结论）；Gemini GRACE_PERIOD_MS

# 子助手能用的工具：读写同一个工作区、跑命令和后台任务、查网页、调已授权的 API / MCP、读技能。
# 不给：问用户的表单与登录、浏览器（多个子助手共用会话会抢页面）、展示卡片（结果只交回主助手）、记忆 / 定时任务 / Home 等
# 改用户设置的、计划清单（属于主助手那张）、派活工具本身（深度 1）。
CHILD_TOOLS = frozenset({
    "web_search", "web_fetch", "image_search",
    "list_files", "glob", "grep", "read_file", "write_file", "edit_file", "apply_patch",
    "run_command", "job_status", "cancel_job", "restart_service",
    "api_request", "mcp_tools", "mcp_call", "use_skill",
    "get_current_time", "convert_time", "resolve_relative_date", "analyze_video", "search_transcript", "search_history", "search_memory",
    "extract_data", "save_attachment", "render_document",
})

STATES = ("running", "done", "partial", "failed", "stopped")
LABEL = {"running": "在做", "done": "完成", "partial": "交了半截", "failed": "没成", "stopped": "被停下"}

ROLE = """你现在是子助手：主助手把下面这件事交给你独立完成。你的最终回复会原样交回主助手（不是直接给用户看）。
规则：
1. 只做交代的这件事，不扩展范围；和别的子助手同时在跑，不要动任务说明之外的文件。
2. 没人能回答你的问题：信息不够就按最合理的假设去做，并在结果里写明假设。
3. 需要用户批准的操作（危险命令、付款、写外部服务）在这里会被直接拒绝——不要换方式重试，把要做的事写进结果交回。
4. 最终回复自成一体：结论先行，给出具体数据、来源链接、改过 / 新建的文件路径和没做完的部分；不寒暄、不复述任务。
5. 没做过的事不要说做了。"""

RESUMED = "这是续问：上面是你之前做这件事的过程和交回的结果，接着最后一条消息做，已经做过的不要重做。"

WRAP_UP = ("[系统提示] 你的步数 / 时间预算用完了，不能再调用工具。现在直接写交给主助手的最终结果：已经查到 / 做完了什么"
           "（具体结论、文件路径），还差什么没做、卡在哪里。")


class DelegateError(ValueError):
    """参数不对：原因回给模型让它改。"""


@dataclass
class Task:
    title: str
    prompt: str
    state: str = "running"
    steps: int = 0
    now: str = ""
    result: str = ""
    note: str = ""
    seconds: int | None = None
    id: str = field(default_factory=threads.new_id)
    resume: bool = False          # 续问：接着它存下的上下文（attach 填 base / round）
    base: list[dict] = field(default_factory=list)
    round: int = 1
    model: str | None = None      # 续问沿用派它时的模型（deepseek 描述符）
    _running: set[str] = field(default_factory=set)

    def card(self) -> dict:
        out = {"id": self.id, "title": self.title, "state": self.state, "steps": self.steps}
        if self.round > 1:
            out["round"] = self.round
        if self.state == "running" and self.now:
            out["now"] = self.now
        if self.seconds is not None:
            out["seconds"] = self.seconds
        if self.result and self.state != "running":
            out["result"] = _clip(self.result, CARD_RESULT_MAX)
        if self.note:
            out["note"] = self.note
        return out


def normalize(tasks: object) -> list[Task]:
    """模型给的子任务 → Task 列表。规则：数组、1..subagent_max_tasks 个、title / prompt 非空、标题不重复。
    续问项 {continue: 编号, prompt}：title 可省（attach 从存下的上下文补），同一个编号只能出现一次。"""
    if settings.subagent_max_tasks <= 0:
        raise DelegateError("子助手已关闭（SUBAGENT_MAX_TASKS=0），自己做")
    if not isinstance(tasks, list) or not tasks:
        raise DelegateError("tasks 要是一个非空数组：[{title, prompt}]")
    if len(tasks) > settings.subagent_max_tasks:
        raise DelegateError(f"一次最多 {settings.subagent_max_tasks} 个子任务（给了 {len(tasks)} 个）：合并或分批")
    out, seen = [], set()
    for t in tasks:
        if not isinstance(t, dict):
            raise DelegateError("每个子任务要是 {title, prompt} 对象")
        title = " ".join(str(t.get("title") or "").split())
        prompt = str(t.get("prompt") or "").strip()
        if (sid := t.get("continue")) not in (None, ""):
            if not threads.valid_id(sid):
                raise DelegateError(f"continue 要是之前子任务结果里给的编号（形如 sa_1a2b3c），给的是 {str(sid)[:20]!r}")
            if sid in {x.id for x in out}:
                raise DelegateError(f"同一个子助手 {sid} 一次只能续问一次：把问题合在一条 prompt 里")
            if not prompt:
                raise DelegateError(f"续问 {sid} 没有 prompt：写清楚要它接着做什么")
            if len(prompt) > PROMPT_MAX:
                raise DelegateError(f"续问 {sid} 的 prompt 太长（{len(prompt)} 字，上限 {PROMPT_MAX}）")
            out.append(Task(_clip(title, TITLE_MAX), prompt, id=sid, resume=True))
            continue
        if not title:
            raise DelegateError("每个子任务都要有 title（几个字，给用户看）")
        if not prompt:
            raise DelegateError(f"子任务「{title}」没有 prompt：写清楚目标、路径、约束和要交回什么")
        if len(prompt) > PROMPT_MAX:
            raise DelegateError(f"子任务「{title}」的 prompt 太长（{len(prompt)} 字，上限 {PROMPT_MAX}）：大段材料先写进工作区文件，再告诉它路径")
        title = _clip(title, TITLE_MAX)
        if title in seen:
            raise DelegateError(f"子任务标题重复：「{title}」")
        seen.add(title)
        out.append(Task(title, prompt))
    return out


async def attach(db, conversation_id: str | None, tasks: list[Task]) -> None:
    """续问项读回存下的上下文（只认这段对话派过的）；找不到 → DelegateError。新派的不动。"""
    for t in tasks:
        if not t.resume:
            continue
        row = await threads.load(db, conversation_id, t.id)
        if row is None or not (base := threads.history_of(row)):
            raise DelegateError(f"找不到子助手 {t.id} 的上下文（不是这段对话派的、或已经清掉了）：改成新派一个，prompt 写全")
        t.title, t.base, t.round, t.model = t.title or row.title, base, (row.rounds or 1) + 1, row.model


def block(tasks: list[Task], live: bool = False) -> dict:
    b = {"type": "delegate", "tasks": [t.card() for t in tasks]}
    if live:
        b["live"] = True
    return b


def history_text(b: dict) -> str:
    """历史里的一行：用户回“继续”时模型知道上一轮派过什么、结果如何（结论本身已经在那一轮的回复文字里）。"""
    items = [f"{t.get('title', '')}（{LABEL.get(t.get('state', ''), '')}）" for t in b.get("tasks") or []]
    return f"[子任务：{'；'.join(items)}]" if items else ""


def for_model(tasks: list[Task]) -> str:
    """交回主助手的文字：每个子助手的状态 + 结论。"""
    done = sum(t.state == "done" for t in tasks)
    parts = [f"{len(tasks)} 个子任务已结束（完成 {done} 个）。下面是它们交回的结果——用户看不到这些原文，需要的话由你整理后告诉用户。"
             "要接着问某个子助手（它记得自己查过 / 做过的），再调 delegate，tasks 里放 {continue: 编号, prompt}。"]
    for i, t in enumerate(tasks, 1):
        head = f"## {i}. {t.title}（编号 {t.id}" + (f"，第 {t.round} 轮" if t.round > 1 else "") + f"）— {LABEL[t.state]}（{t.steps} 步" \
            + (f"，{t.seconds} 秒" if t.seconds is not None else "") + "）"
        body = _clip(t.result, RESULT_MAX) if t.result else "（没有交回结果）"
        note = f"\n说明：{t.note}" if t.note else ""
        parts.append(f"{head}{note}\n{body}")
    return "\n\n".join(parts)


def summary(tasks: list[Task]) -> str:
    """时间线这一步的摘要。"""
    counts = {s: sum(t.state == s for t in tasks) for s in STATES}
    bits = [f"{LABEL[s]} {n}" for s, n in counts.items() if n]
    return f"{len(tasks)} 个子任务：" + "，".join(bits)


async def run_all(ctx: ToolContext, tasks: list[Task]) -> None:
    """并行跑所有子助手，过程中 ctx.live 推卡片。被取消（用户停止）时一起取消，状态记 stopped。"""
    await ctx.db.commit()  # 主助手这边别占着写锁（SQLite），子助手各自开会话写库
    push = lambda: ctx.live(block(tasks, live=True))
    push()
    runs = [asyncio.create_task(_guarded(ctx, t, push)) for t in tasks]
    try:
        await asyncio.gather(*runs)
    except asyncio.CancelledError:
        for r in runs:
            r.cancel()
        await asyncio.gather(*runs, return_exceptions=True)
        for t in tasks:
            if t.state == "running":
                t.state = "stopped"
        raise


async def _guarded(ctx: ToolContext, t: Task, push) -> None:
    t0 = time.monotonic()
    limit = (settings.subagent_minutes if settings.subagent_minutes > 0 else 10) * 60
    try:
        await asyncio.wait_for(_child(ctx, t, push, t0 + limit), limit + GRACE_SECONDS)
    except asyncio.TimeoutError:
        t.state, t.note = "failed", f"超过 {settings.subagent_minutes:g} 分钟还没交结果，已停下"
    except asyncio.CancelledError:
        t.state = "stopped"
        raise
    except Exception as e:  # 一个子助手出错不连累别的
        t.state, t.note = "failed", _clip(f"出错：{e}", 160)
    finally:
        t.seconds = int(time.monotonic() - t0)
        t.now = ""
        push()


async def _child(parent: ToolContext, t: Task, push, deadline: float) -> None:
    async with SessionLocal() as db:
        model = t.model if t.model and t.model in settings.chat_models else parent.model  # 那个模型下架了 → 用现在的
        ctx = ToolContext(db=db, project_id=parent.project_id, conversation_id=parent.conversation_id,
                          task_id=parent.task_id, model=model, effort=parent.effort, allow=CHILD_TOOLS, depth=parent.depth + 1,
                          changes=parent.changes,  # 子助手改的文件也算进这一轮的改动卡
                          plan=plan_mode.State(active=True, can_exit=False) if parent.plan and parent.plan.active else None)
        prompt = (await build_system_prompt(db, parent.project_id, t.prompt)).add(STABLE, ROLE)
        if t.resume:
            prompt.add(STABLE, RESUMED)
        if ctx.plan is not None:  # 主助手在计划模式：子助手同样只读（Gemini 计划模式只放调查类子助手）
            prompt.add(STABLE, plan_mode.CHILD_NOTE)
        system = prompt.text()
        limits = loop.Limits(max(1, settings.subagent_max_steps), settings.subagent_turn_tokens, deadline, WRAP_UP)
        builder = loop.MessageBuilder()
        history = [*t.base, threads.follow_up(t.prompt)] if t.resume else [threads.opening(t.title, t.prompt)]
        finished = False
        try:
            await _drive(system, history, ctx, builder, model, limits, t, push)
            finished = True
            texts = [b["text"].strip() for b in builder.blocks if b.get("type") == "text" and b["text"].strip()]
            t.result = texts[-1] if texts else ""
            t.state = "partial" if limits.wrapped else "done"
            if limits.wrapped:
                t.note = "步数 / 时间预算用完，交的是当时的进度"
            if not t.result:
                t.state, t.note = "failed", "没有交回任何结论"
        finally:  # 被停 / 超时 / 出错也留下已经做过的（tidy 剪掉没收尾的调用），之后还能接着问
            said = [{"role": "assistant", "content": t.result}] if finished and t.result else []
            if builder.transcript is not None and await threads.save(
                    db, parent.conversation_id, t.id, t.title, model, t.state if finished else "stopped",
                    [*builder.transcript, *said], t.resume):
                await db.commit()


async def _drive(system, history, ctx, builder, model, limits, t: Task, push) -> None:
    async for ev in loop.run(system, history, ctx, builder, model, limits):
        if isinstance(ev, loop.ToolStatus) and ev.name != "compact_context":
            if ev.state == "running":
                t._running.add(ev.id)
                t.steps += 1
                t.now = ev.label
            else:
                t._running.discard(ev.id)
                if not t._running:
                    t.now = ""
            push()
    await ctx.db.commit()


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
