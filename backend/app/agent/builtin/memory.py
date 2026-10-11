"""长期记忆：模型在用户说出稳定的偏好/事实时调用 remember，用户要求忘掉时调用 forget。"""
from sqlalchemy import select

from ... import memory_store
from ...models import Memory
from ..tools import ToolContext, ToolResult, tool

CATEGORIES = ["profile", "food", "travel", "work", "shopping", "general"]


@tool("remember", "正在记住",
      "把用户明确说出的、以后还用得上的偏好或事实存进长期记忆（如饮食禁忌、专业、作息）。"
      "不要存一次性的事情、不要存密码和证件号。保持用户原意，不夸大。",
      {"type": "object", "properties": {
          "content": {"type": "string", "description": "一句话，如：不吃香菜"},
          "category": {"type": "string", "enum": CATEGORIES}},
       "required": ["content", "category"]})
async def remember(ctx: ToolContext, content: str, category: str = "general") -> ToolResult:
    category = category if category in CATEGORIES else "general"
    old, vec = await memory_store.find_similar(ctx.db, content)
    if old:  # 意思相同的旧记忆：用新说法覆盖（偏好会变，以最新为准）
        replaced, old.content, old.category, old.embedding = old.content, content, category, vec
        await ctx.db.commit()
        return ToolResult("已经记过了。" if replaced == content else f"已更新（原来是：{replaced}）。")
    ctx.db.add(Memory(content=content, category=category, embedding=vec))
    await ctx.db.commit()
    return ToolResult("已记住。")


@tool("forget", "正在删除记忆",
      "用户要求忘掉某件事，或某条记忆已经不对时调用。传入关键词，删除包含它的记忆。",
      {"type": "object", "properties": {"keyword": {"type": "string"}}, "required": ["keyword"]})
async def forget(ctx: ToolContext, keyword: str) -> ToolResult:
    rows = (await ctx.db.scalars(select(Memory).where(Memory.content.contains(keyword)))).all()
    for m in rows:
        await ctx.db.delete(m)
    await ctx.db.commit()
    return ToolResult(f"删除了 {len(rows)} 条：" + "；".join(m.content for m in rows) if rows else "没有找到相关记忆。")
