"""技能：模型按需读取做法（use_skill），或把用户教的做法存下来（save_skill）。"""
from ... import skill_catalog, skills_store
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


@tool("skill_search", "正在找技能",
      "按关键词在技能库里找做法（名称、描述、正文都搜）。用户说“按我的做法 / 流程 / 习惯 / 模板”、系统提示的技能目录没列全、"
      "或不确定有没有现成做法时先用它（存下来的做法在技能里，不在记忆和聊天记录里）；"
      "query 留空列出全部启用的技能。",
      {"type": "object", "properties": {
          "query": {"type": "string", "description": "关键词，空格分开；留空 = 列出全部"},
          "limit": {"type": "integer", "description": "最多几条（默认 8，最多 30）"}}},
      parallel=True)  # 不按需：真机 v2.46 s1 目录省略后模型只想到 search_memory/search_history（约 90 token）
async def skill_search(ctx: ToolContext, query: str = "", limit: int | None = None) -> ToolResult:
    skills = skills_store.enabled_skills()
    hits = skill_catalog.search(skills, query, limit)
    return ToolResult(skill_catalog.render(hits, query, len(skills)))


@tool("edit_skill", "正在修改技能",
      "小改已有技能：把技能全文里唯一一处 find 原文换成 replace（比 save_skill 整篇重写省）。"
      "find 要逐字一致、只出现一次；不确定原文先 use_skill。内置技能会自动复制成自定义版再改，用户可在技能页恢复默认。",
      {"type": "object", "properties": {
          "id": {"type": "string"}, "find": {"type": "string", "description": "要替换的原文（逐字）"},
          "replace": {"type": "string", "description": "换成什么；空串 = 删掉这段"}},
       "required": ["id", "find", "replace"]}, deferred=True)
async def edit_skill(ctx: ToolContext, id: str, find: str, replace: str) -> ToolResult:
    try:
        before = skills_store.get_skill(id)
        s = skills_store.edit_skill(id, find, replace)
    except KeyError:
        return ToolResult(f"没有 id 为 {id} 的技能；用 skill_search 找找。")
    except ValueError as e:
        return ToolResult(f"没有改：{e}")
    note = "（内置技能已复制成自定义版，可在技能页恢复默认）" if before and before.builtin and not before.customized else ""
    return ToolResult(f"已修改技能「{s.name}」（id: {s.id}）{note}。")


@tool("delete_skill", "正在删除技能",
      "用户明确要删掉某个技能时用。自己建的技能直接删除；内置技能的自定义版恢复成内置原样；内置技能不能删（可以请用户在技能页停用）。",
      {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}, deferred=True)
async def delete_skill(ctx: ToolContext, id: str) -> ToolResult:
    s = skills_store.get_skill(id)
    if s is None:
        return ToolResult(f"没有 id 为 {id} 的技能。")
    if s.customized:
        skills_store.reset(id)
        return ToolResult(f"「{s.name}」是内置技能的自定义版：已删掉你的改动，恢复成内置原样。")
    if s.builtin:
        return ToolResult(f"「{s.name}」是内置技能，不能删除；不想让我用它，可以在技能页把它停用。")
    skills_store.delete_skill(id)
    return ToolResult(f"已删除技能「{s.name}」。")
