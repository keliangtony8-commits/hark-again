"""技能：模型按需读取做法（use_skill），或把用户教的做法存下来（save_skill）。"""
from ... import skills_store
from ..tools import ToolContext, ToolResult, tool


@tool("use_skill", "正在读取技能", "读取某个技能的完整做法，按它执行任务。",
      {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]})
async def use_skill(ctx: ToolContext, id: str) -> ToolResult:
    s = skills_store.get_skill(id)
    if s is None:
        return ToolResult("没有这个技能。")
    if not s.enabled:
        return ToolResult(f"技能「{s.name}」已被用户停用，不要按它做；需要的话请用户在技能页重新启用。")
    return ToolResult(f"# {s.name}\n{s.description}\n\n{s.body}")


@tool("save_skill", "正在保存技能",
      "用户让你记住一套做事方法时，存成技能。正文写成可执行的步骤，保留用户的具体要求。"
      "改已有技能时传它的 id（内置技能会先复制成用户的自定义版再改）。",
      {"type": "object", "properties": {
          "name": {"type": "string"}, "description": {"type": "string", "description": "一句话：什么时候用"},
          "body": {"type": "string", "description": "分步骤的做法"},
          "id": {"type": "string", "description": "要修改的已有技能 id；新建时不传"}},
       "required": ["name", "description", "body"]}, deferred=True)
async def save_skill(ctx: ToolContext, name: str, description: str, body: str, id: str | None = None) -> ToolResult:
    if id:
        cur = skills_store.get_skill(id)
        if cur is None:
            return ToolResult(f"没有 id 为 {id} 的技能；新建请不传 id。")
        if cur.builtin:
            skills_store.customize(id)
        s = skills_store.save_skill(name, description, body, sid=id)
        return ToolResult(f"已更新技能「{s.name}」（id: {s.id}{'，内置技能的自定义版' if s.customized else ''}）。")
    s = skills_store.save_skill(name, description, body)
    return ToolResult(f"已保存技能「{s.name}」（id: {s.id}）。")
