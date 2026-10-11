"""项目档案工具：只在项目对话里提供。逻辑在 app/project_brief.py，这里只做模型接口。"""
from ... import project_brief
from ...models import Project
from ..tools import ToolContext, ToolResult, tool


@tool("project_brief", "正在更新项目档案",
      "读或改当前项目的「项目档案」（项目的长期记忆）。action=read 看全文；edit 把 find 原文（必须唯一）换成 replace；write 用 content 整份重写。",
      {"type": "object", "properties": {
          "action": {"type": "string", "enum": ["read", "edit", "write"]},
          "find": {"type": "string", "description": "edit：要替换的原文，精确复制"},
          "replace": {"type": "string", "description": "edit：替换成的新内容（可为空 = 删除）"},
          "content": {"type": "string", "description": "write：完整的新档案（Markdown，小标题组织）"}},
       "required": ["action"]},
      scope="project")
async def project_brief_tool(ctx: ToolContext, action: str, find: str = "", replace: str = "", content: str = "") -> ToolResult:
    p = await ctx.db.get(Project, ctx.project_id)
    if p is None:
        return ToolResult("找不到当前项目。")
    if action == "read":
        return ToolResult(p.brief or "（项目档案是空的）")
    if action == "edit":
        err = project_brief.edit(p, find, replace)
    elif action == "write":
        err = project_brief.write(p, content)
    else:
        return ToolResult("action 只能是 read / edit / write。")
    if err:
        return ToolResult(err)
    await ctx.db.commit()
    return ToolResult(f"已更新项目档案（{len(p.brief)} 字）。")
