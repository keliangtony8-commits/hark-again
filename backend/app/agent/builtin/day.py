"""“帮我准备今天”：day_overview 一次交出今天已知的事（日程、主页待办、收件箱、记忆里的日期），
由技能 prep-my-day 写成 show_summary 简报。原料的收集规则全在 app/day_brief.py。"""
from ... import day_brief
from ..tools import ToolContext, ToolResult, tool


@tool("day_overview", "正在看今天的安排",
      "一次拿到今天已知的事：今天按钟点排着的定时任务及状态、Home 上等着用户的建议和提醒、收件箱未读、记忆里写到今天或这几天的日期。"
      "用户说“帮我准备今天”“今天有什么”、早间简报任务，都先调它（只读、不花模型额度），再按技能 prep-my-day 写简报。",
      {"type": "object", "properties": {}})
async def day_overview(ctx: ToolContext) -> ToolResult:
    brief = await day_brief.gather(ctx.db)
    hint = ("\n\n（今天没有任何已知安排：简报就说今天很空，可以问用户要不要排点什么，别编造日程。）" if brief.empty else
            "\n\n（Home 上已有的卡不要再用 offer_on_home 重复放；自动暂停、失败的任务值得在提醒里点名。）")
    return ToolResult(brief.text() + hint)
