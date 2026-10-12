"""计划清单工具：多步任务开工前列出步骤，边做边勾，聊天里是一张随时更新的清单卡。规则在 app/plan.py。

描述移植自 deepseek-harness todo_write（MIT）的写法（单人干活：只能有一步 in_progress），
参数形状取 Codex update_plan（plan[{step,status}] + explanation）与 deepseek 的 content 命名的折中：todos[{content,status}]。
"""
from ... import plan
from ..tools import ToolContext, ToolResult, tool


@tool("update_plan", "正在更新计划",
      "记录并更新这次任务的步骤清单，用户在聊天里会看到一张实时打勾的清单。要做 3 步以上的活（装环境、写代码再跑、"
      "多处查资料再汇总）先列出来再动手；一两步就能完成的不要用。每次传完整清单（替换上一份）。"
      "还有活没做完时，保持恰好一步 in_progress；做完一步立刻标 completed，同时把下一步标 in_progress。"
      "计划变了就改清单，并在 explanation 里用一句话说为什么。",
      {"type": "object", "properties": {
          "todos": {"type": "array", "description": "完整清单，替换上一份；传空数组 = 清掉",
                    "items": {"type": "object", "additionalProperties": False, "required": ["content", "status"], "properties": {
                        "content": {"type": "string", "description": "这一步做什么：一句短的祈使句"},
                        "status": {"type": "string", "enum": list(plan.STATUSES),
                                   "description": "pending 没开始 | in_progress 正在做 | completed 做完了"}}}},
          "explanation": {"type": "string", "description": "可选：这次为什么改计划（一句话）"}},
       "required": ["todos"]},
      quiet=True)
async def update_plan(ctx: ToolContext, todos: object = None, explanation: object = "") -> ToolResult:
    try:
        items, note = plan.normalize(todos, explanation)
    except plan.PlanError as e:
        return ToolResult(f"计划没有更新：{e}。改好后重新传完整清单。", failed=str(e))
    return ToolResult(plan.for_model(items), blocks=[plan.block(items, note)])
