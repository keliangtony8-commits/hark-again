"""exit_plan_mode：计划模式下把方案交给用户批准；批准即退出计划模式、这一轮接着按方案做。规则在 app/plan_mode.py。

描述移植自 deepseek-harness plan-mode EXIT_DESCRIPTION（MIT）与 Gemini CLI exit_plan_mode（Apache-2.0）的写法，modified。
工具常驻（deepseek：进出计划模式只换提示、不换工具目录，前缀缓存不断）；不在计划模式时 plan_mode.refusal 直接拒。
v1.72：批准后方案写进工作区 plans/（plan_mode.plan_file，Gemini approvedPlanPath），进时间线这一步的改动和整轮改动卡。
v1.73：批准时把方案里的步骤种成进度清单（plan_mode.plan_steps）；方案没存成时把卡上的“已存为”撤掉（ToolResult.card）。
"""
import asyncio
import logging

from sqlalchemy import select, update

from ... import file_edit, file_seen, plan as checklist, plan_mode, quota
from ...models import Conversation
from ...schedule import local_now
from ...storage import project_dir
from ..tools import Approval, ToolContext, ToolResult, tool

log = logging.getLogger(__name__)


async def _target(ctx: ToolContext, title: str) -> str:
    """批准后存到哪（卡上显示的和真正写的是同一个规则、同一份输入）。"""
    previous = await ctx.db.scalar(select(Conversation.plan_path).where(Conversation.id == ctx.conversation_id))
    return plan_mode.plan_file(project_dir(ctx.workspace), title, previous, local_now().date())


async def _risk(args: dict, ctx: ToolContext):
    try:
        text, title = plan_mode.check_plan(args.get("plan"))
    except plan_mode.PlanTextError:
        return None  # 方案不合格：不打扰用户，run 把原因还给模型
    card = plan_mode.review_card(text, title, ctx.workspace, await _target(ctx, title))
    return Approval(f"批准方案：{title}", card, rejected=plan_mode.REJECTED)


async def _save(ctx: ToolContext, rel: str, text: str) -> tuple[str, dict | None, bool]:
    """把批准的方案写进工作区（和 write_file 一样：整轮改动基线、已读记录、配额）。返回 (给模型的一句, 改动摘要, 存成没有)。"""
    root = project_dir(ctx.workspace)
    p = root / rel
    body = text.rstrip() + "\n"
    try:
        before = p.read_text(encoding="utf-8") if p.is_file() else None
        grow = len(body.encode()) - (p.stat().st_size if p.is_file() else 0)
        if grow > 0:
            await asyncio.to_thread(quota.check, ctx.workspace, grow)
        ctx.changes.before(root, p)  # 进这一轮的改动卡，能整轮撤销
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    except (OSError, UnicodeDecodeError, quota.QuotaError) as e:
        log.warning("approved plan not saved: %s", e)
        return f"（方案没能存成文件：{e}。照上面批准的方案原文做即可。）", None, False
    file_seen.observe(file_seen.owner_of(ctx.conversation_id, ctx.task_id), p)
    quota.forget(ctx.workspace)
    await ctx.db.execute(update(Conversation).where(Conversation.id == ctx.conversation_id)
                         .values(plan_path=rel, updated_at=Conversation.updated_at))
    verb = "已存到" if before is None else "已更新"
    return f"方案{verb}工作区 {rel}（之后要改做法，先和用户确认再更新它）。", file_edit.change(rel, before, body), True


@tool(plan_mode.TOOL, "正在提交方案",
      "只在计划模式下用：把完整方案交给用户审阅。用户批准 → 退出计划模式，这一轮接着按方案动手；"
      "用户没批准 → 仍在计划模式，问他想改哪里，改好再交完整的新一版。"
      "先在聊天里和用户大致对齐再交；不要在 run_command 里调用它。",
      {"type": "object", "properties": {
          "plan": {"type": "string", "description": "完整方案，Markdown，第一行是“# 标题”（概要、要改的地方、怎么验证、假设）"}},
       "required": ["plan"]},
      scope="conversation", risk=_risk, quiet=True)
async def exit_plan_mode(ctx: ToolContext, plan: object = "") -> ToolResult:
    try:
        text, title = plan_mode.check_plan(plan)
    except plan_mode.PlanTextError as e:
        return ToolResult(f"方案没有交出去：{e}", failed=str(e))
    # 走到这里 = 用户在方案卡上点了批准（kernel 的审批流程）
    if ctx.plan is not None:
        ctx.plan.lift()
    saved, change, ok = await _save(ctx, await _target(ctx, title), text)
    await ctx.db.execute(update(Conversation).where(Conversation.id == ctx.conversation_id)
                         .values(mode=plan_mode.DEFAULT, mode_seen=plan_mode.DEFAULT, updated_at=Conversation.updated_at))
    await ctx.db.commit()  # 下一次模型调用前提交（SQLite 锁）
    items = plan_mode.seed_items(steps) if (steps := plan_mode.plan_steps(text)) else []
    head = plan_mode.LIFTED + (plan_mode.LIFTED_SEEDED if items else plan_mode.LIFTED_FREE)
    body = f"{head}\n{saved}" + (f"\n{checklist.for_model(items)}" if items else "")
    return ToolResult(body, blocks=[checklist.block(items, "按批准的方案")] if items else [], change=change,
                      card=None if ok else {"path": ""})  # 没存成：卡上不显示“已存为”
