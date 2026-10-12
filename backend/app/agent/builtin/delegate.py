"""派子助手：把几件互相独立的事并行交出去，各自独立上下文做完、只交回结论。规则在 agent/subagent.py。

描述嫁接 Codex multi_agents spawn_agent 的“何时委派”指引与 deepseek-harness tool-subagent 的“全新上下文要写全”措辞。
"""
from ...config import settings
from .. import subagent
from ..tools import ToolContext, ToolResult, tool


@tool("delegate", "正在派子助手",
      "把边界清楚、互相独立的子任务交给子助手并行去做：每个子助手在自己的上下文里干活（不占你的上文），只把结论交回给你，"
      "你整理后再告诉用户。适合：几个方向的资料调研、分别排查几处问题、批量处理互不相干的文件、输出量很大的探索。"
      "不适合：你下一步马上就要依赖的结果（关键路径自己做）、紧密耦合的改动、一两步就能做完的事。"
      "子助手看不到这段对话：prompt 要自成一体，写清目标、相关路径和材料、约束、要交回什么。"
      f"互相独立的子任务一次全部放进 tasks（并行跑，最多 {settings.subagent_max_tasks} 个）；不要让两个子任务改同一个文件，"
      "也不要和子任务重复做同一件事。子助手能读写同一个工作区、跑命令、搜网页、调已授权的 API，"
      "但不能问用户、不能开浏览器、需要批准的操作会被拒绝（它会把要做的事写进结果，你再去请用户批准）。",
      {"type": "object", "properties": {
          "tasks": {"type": "array", "description": "要并行做的子任务",
                    "items": {"type": "object", "additionalProperties": False, "required": ["title", "prompt"], "properties": {
                        "title": {"type": "string", "description": "几个字的标题，给用户看，如“查竞品定价”"},
                        "prompt": {"type": "string", "description": "完整、自成一体的任务说明：目标、路径 / 材料、约束、要交回的结果形式"}}}}},
       "required": ["tasks"]})
async def delegate(ctx: ToolContext, tasks: object = None) -> ToolResult:
    try:
        items = subagent.normalize(tasks)
    except subagent.DelegateError as e:
        return ToolResult(f"没有派出去：{e}。改好后重试。", failed=str(e))
    await subagent.run_all(ctx, items)
    failed = "" if any(t.state in ("done", "partial") for t in items) else "子任务都没交回结论"
    return ToolResult(subagent.for_model(items), blocks=[subagent.block(items)], failed=failed)
