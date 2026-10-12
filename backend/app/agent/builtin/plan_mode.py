"""exit_plan_mode：计划模式下把方案交给用户批准；批准即退出计划模式、这一轮接着按方案做。规则在 app/plan_mode.py。

描述移植自 deepseek-harness plan-mode EXIT_DESCRIPTION（MIT）与 Gemini CLI exit_plan_mode（Apache-2.0）的写法，modified。
工具常驻（deepseek：进出计划模式只换提示、不换工具目录，前缀缓存不断）；不在计划模式时 plan_mode.refusal 直接拒。
"""
from sqlalchemy import update

from ... import plan_mode
from ...models import Conversation
from ..tools import Approval, ToolContext, ToolResult, tool


def _risk(args: dict, ctx: ToolContext):
    try:
        text, title = plan_mode.check_plan(args.get("plan"))
    except plan_mode.PlanTextError:
        return None  # 方案不合格：不打扰用户，run 把原因还给模型
    return Approval(f"批准方案：{title}", plan_mode.review_card(text, title), rejected=plan_mode.REJECTED)


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
        plan_mode.check_plan(plan)
    except plan_mode.PlanTextError as e:
        return ToolResult(f"方案没有交出去：{e}", failed=str(e))
    # 走到这里 = 用户在方案卡上点了批准（kernel 的审批流程）
    if ctx.plan is not None:
        ctx.plan.lift()
    await ctx.db.execute(update(Conversation).where(Conversation.id == ctx.conversation_id)
                         .values(mode=plan_mode.DEFAULT, mode_seen=plan_mode.DEFAULT, updated_at=Conversation.updated_at))
    await ctx.db.commit()  # 下一次模型调用前提交（SQLite 锁）
    return ToolResult(plan_mode.LIFTED)
