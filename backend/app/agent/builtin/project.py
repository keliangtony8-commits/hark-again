"""项目工具：项目档案（只在项目对话里）+ 跨项目协作 projects。逻辑在 app/project_brief.py、app/project_relay.py，这里只做模型接口。"""
from ... import project_brief, project_relay
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


@tool("projects", "正在协调项目",
      "看用户有哪些项目、新建项目、把一件事交给另一个项目去做（规则在 app/project_relay.py）。"
      "action=list 列出项目；create 新建（name、emoji、brief = 第一版项目档案）——一件独立、会长期积累文件的事才建议新开项目，"
      "先问用户，别擅自建；message 把 text（对方看不到这段对话，背景、要什么结果都写全）交给 project（名字或 id），"
      "可用 files 带上本工作区的文件（复制进对方 received/），对方助手立刻在它那边接着做，结果留在那个项目里。",
      {"type": "object", "properties": {
          "action": {"type": "string", "enum": ["list", "create", "message"]},
          "project": {"type": "string", "description": "message：目标项目的名字或 id"},
          "text": {"type": "string", "description": "message：交给对方的话"},
          "files": {"type": "array", "items": {"type": "string"}, "description": "message：本工作区里要一起带过去的文件路径（≤5 个）"},
          "name": {"type": "string", "description": "create：项目名字"},
          "emoji": {"type": "string", "description": "create：一个表情做图标"},
          "brief": {"type": "string", "description": "create：第一版项目档案（目标、范围；Markdown）"}},
       "required": ["action"]},
      scope="conversation", deferred=True)
async def projects_tool(ctx: ToolContext, action: str, project: str = "", text: str = "", files: list[str] | None = None,
                        name: str = "", emoji: str = "", brief: str = "") -> ToolResult:
    try:
        if action == "list":
            return ToolResult(await project_relay.list_text(ctx.db, ctx.project_id))
        if action == "create":
            p = await project_relay.create(ctx.db, name, emoji, brief)
            return ToolResult(f"已新建项目「{p.emoji} {p.name}」（id={p.id}）。要把这件事交过去用 action=message。",
                              detail=f"新建 {p.name}")
        if action == "message":
            sent = await project_relay.send(ctx.db, ctx.conversation_id, ctx.project_id, project, text, files)
            return ToolResult(project_relay.for_model(sent), [project_relay.card(sent, text.strip())],
                              detail=f"交给 {sent.project.name}")
    except project_relay.RelayError as e:
        return ToolResult(str(e), failed=str(e))
    return ToolResult("action 只能是 list / create / message。", failed="action 不对")
