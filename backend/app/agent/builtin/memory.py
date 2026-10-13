"""长期记忆工具：remember 记 / update_memory 改 / forget 删 / search_memory 查（v2.11）。
写入逻辑全在 memory_store（查重覆盖、按短引用定位）；这里只做参数整理和给模型的回话，
每次真改了记忆就附一张记忆卡（blocks.MemoryBlock），用户在聊天里看得见、能撤销。"""
from sqlalchemy import select

from ... import memory_store
from ...db import SessionLocal
from ...models import Memory
from ..tools import ToolContext, ToolResult, tool

CATEGORIES = ["profile", "food", "travel", "work", "shopping", "general"]


def _cat(c: str | None) -> str | None:
    return c if c in CATEGORIES else None


@tool("remember", "正在记住",
      "把用户明确说出的、以后还用得上的偏好或事实存进长期记忆（如饮食禁忌、专业、作息）。"
      "不要存一次性的事情、不要存密码和证件号。保持用户原意，不夸大。",
      {"type": "object", "properties": {
          "content": {"type": "string", "description": "一句话，如：不吃香菜"},
          "category": {"type": "string", "enum": CATEGORIES}},
       "required": ["content", "category"]})
async def remember(ctx: ToolContext, content: str, category: str = "general") -> ToolResult:
    m, previous = await memory_store.save(ctx.db, content.strip(), _cat(category) or "general")
    if previous == m.content:
        return ToolResult("已经记过了。")
    if previous is not None:
        return ToolResult(f"已更新（原来是：{previous}）。", [memory_store.card("updated", [(m, previous)])])
    return ToolResult("已记住。", [memory_store.card("saved", [(m, None)])])


@tool("update_memory", "正在修改记忆",
      "某条已知记忆变了或说得不准时调用：传它的 # 引用和新的一句话（分类可选）。",
      {"type": "object", "properties": {
          "ref": {"type": "string", "description": "记忆后面的引用，如 #a1b2c3d4"},
          "content": {"type": "string"},
          "category": {"type": "string", "enum": CATEGORIES}},
       "required": ["ref", "content"]})
async def update_memory(ctx: ToolContext, ref: str, content: str, category: str | None = None) -> ToolResult:
    found, _ = await memory_store.resolve(ctx.db, [ref])
    if not found:
        return ToolResult(f"找不到引用 {ref} 的记忆，换用 remember 新记一条。")
    m = found[0]
    previous = await memory_store.update(ctx.db, m, content.strip(), _cat(category))
    if previous == m.content and not category:
        return ToolResult("内容没变。")
    return ToolResult(f"已修改（原来是：{previous}）。", [memory_store.card("updated", [(m, previous)])])


@tool("forget", "正在删除记忆",
      "用户要求忘掉某件事，或某条记忆已经不对时调用。优先传记忆的 # 引用（可多条）；"
      "上下文里看不到那条记忆时才传关键词，删除内容包含它的记忆。",
      {"type": "object", "properties": {
          "refs": {"type": "array", "items": {"type": "string"}, "description": "如 [\"#a1b2c3d4\"]"},
          "keyword": {"type": "string"}}})
async def forget(ctx: ToolContext, refs: list[str] | None = None, keyword: str | None = None) -> ToolResult:
    rows, bad = await memory_store.resolve(ctx.db, refs or [])
    if keyword and keyword.strip():
        rows += [m for m in (await ctx.db.scalars(select(Memory).where(Memory.content.contains(keyword.strip())))).all()
                 if m not in rows]
    if not rows:
        return ToolResult("没有找到相关记忆。")
    block = memory_store.card("forgotten", [(m, None) for m in rows])  # 删之前拍下内容，撤销时照着重建
    for m in rows:
        await ctx.db.delete(m)
    await ctx.db.commit()
    tail = f"（这些引用没找到：{'、'.join(bad)}）" if bad else ""
    return ToolResult(f"删除了 {len(rows)} 条：" + "；".join(i["content"] for i in block["items"]) + tail, [block])


@tool("search_memory", "正在翻记忆",
      "在用户的全部长期记忆里查（上下文只放了最相关的一部分时用）：按字面和意思找，返回每条的 # 引用。"
      "要用到用户的偏好或事实而上面没列出来、或要改/删一条看不到的记忆时先查。query 空 + category = 列出这一类。",
      {"type": "object", "properties": {
          "query": {"type": "string", "description": "要找什么，如：过敏 / 喜欢的咖啡；整句用引号"},
          "category": {"type": "string", "enum": CATEGORIES},
          "limit": {"type": "integer", "description": f"最多返回几条，默认 {memory_store.SEARCH_LIMIT}，上限 {memory_store.LIMIT_MAX}"}}},
      parallel=True)
async def search_memory(ctx: ToolContext, query: str = "", category: str | None = None,
                        limit: int = memory_store.SEARCH_LIMIT) -> ToolResult:
    cat = _cat(category)
    if not query.strip() and not cat:
        return ToolResult("要给 query（找什么），或给 category 列出一类。", failed="没给要找什么")
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = memory_store.SEARCH_LIMIT
    # 可并行 → 不碰 ctx.db（共用会话不能并发）；补向量会写库，在自己的短会话里提交
    async with SessionLocal() as db:
        hits, total, vectors = await memory_store.search(db, query, cat, limit)
        text = memory_store.search_text(query, cat, hits, total, vectors)
    what = query.strip() or cat
    return ToolResult(text, detail=f"{what} · {len(hits)} 条")
