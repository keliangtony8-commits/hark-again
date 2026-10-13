"""长期记忆工具：remember 记 / update_memory 改 / forget 删 / search_memory 查（v2.11）/ memory_note 主题笔记（v2.21）。
写入逻辑全在 memory_store（查重覆盖、按短引用定位）；这里只做参数整理和给模型的回话，
每次真改了记忆就附一张记忆卡（blocks.MemoryBlock），用户在聊天里看得见、能撤销。"""
from sqlalchemy import select

from ... import memory_notes, memory_store
from ...db import SessionLocal
from ...models import Memory
from ..tools import ToolContext, ToolResult, tool

CATEGORIES = ["profile", "food", "travel", "work", "shopping", "general"]


def _cat(c: str | None) -> str | None:
    return c if c in CATEGORIES else None


@tool("remember", "正在记住",
      "把用户明确说出的、以后还用得上的偏好或事实存进长期记忆（如饮食禁忌、专业、作息）。"
      "不要存一次性的事情、不要存密码和证件号。保持用户原意，不夸大。"
      "关于某个人、地方、项目的一串细节写进 memory_note 的主题笔记，这里只存一句话的偏好或事实。",
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
      "要用到用户的偏好或事实而上面没列出来、或要改/删一条看不到的记忆时先查（用户存的做法 / 流程在技能里，用 skill_search）。query 空 + category = 列出这一类。",
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
        notes = await memory_notes.search(db, query) if query.strip() and not cat else []
    if notes:  # 笔记正文也搜（v2.21）：一句话记忆没命中时它常常就是答案
        text += "\n\n" + memory_notes.search_text(notes)
    what = query.strip() or cat
    return ToolResult(text, detail=f"{what} · {len(hits)} 条" + (f" + {len(notes)} 篇笔记" if notes else ""))


_ACTIONS = ["list", "read", "write", "append", "edit", "move", "delete"]


@tool("memory_note", "正在整理笔记",
      "记忆笔记：一个主题一篇 Markdown（一个人、一个地方、一个项目、一个长期兴趣），放一句话记不下的一串细节。"
      "路径即名字，如 people/张三、locations/学校、考研计划；kind=contact 自动放 people/，place 放 locations/。"
      "action：list 列目录；read 看全文；write 整篇写（没有就建，有就覆盖）；append 结尾加一段（没有就建）；"
      "edit 用 old→new 精确替换（要唯一，先 read）；move 改路径（new_path）；delete 删。"
      "只写用户说过的，保留他的条件，推断的标“（推断）”；不写密码证件号、不写一次性的事。先看上下文里的笔记目录，同一主题别建两篇。",
      {"type": "object", "properties": {
          "action": {"type": "string", "enum": _ACTIONS},
          "path": {"type": "string", "description": "如 people/张三"},
          "body": {"type": "string", "description": "write：整篇 Markdown；append：要加的一段"},
          "title": {"type": "string", "description": "新建时的标题，默认是名字"},
          "kind": {"type": "string", "enum": list(memory_notes.KINDS)},
          "old": {"type": "string"}, "new": {"type": "string"},
          "replace_all": {"type": "boolean"},
          "new_path": {"type": "string"}},
       "required": ["action"]})
async def memory_note(ctx: ToolContext, action: str, path: str = "", body: str = "", title: str | None = None,
                      kind: str | None = None, old: str = "", new: str = "", replace_all: bool = False,
                      new_path: str = "") -> ToolResult:
    db = ctx.db
    if action not in _ACTIONS:
        return ToolResult(f"action 只能是 {' / '.join(_ACTIONS)}。", failed="参数不对")
    if action == "list":
        notes = await memory_notes.all_notes(db)
        return ToolResult(memory_notes.list_text(notes), detail=f"{len(notes)} 篇")
    if not path.strip():
        return ToolResult("要给 path（如 people/张三）。", failed="没给路径")
    try:
        if action == "read":
            n = await memory_notes.find(db, path, kind)
            if n is None:
                return ToolResult(f"没有笔记 {path}。用 list 看目录，或 write 新建。", failed="没有这篇")
            return ToolResult(memory_notes.read_text(n), detail=n.path)
        if action == "write":
            n, previous = await memory_notes.write(db, path, body, title, kind)
            said = "新建了" if previous is None else "重写了"
            return ToolResult(f"{said}笔记 {n.path}（{len(n.body)} 字）。", detail=f"{n.path} · {said}")
        if action == "append":
            n, created = await memory_notes.append(db, path, body, title, kind)
            said = "新建了" if created else "加进了"
            return ToolResult(f"{said}笔记 {n.path}（现在 {len(n.body)} 字）。", detail=f"{n.path} · {said}")
        if action == "edit":
            n, k = await memory_notes.edit(db, path, old, new, replace_all)
            return ToolResult(f"改好了 {n.path}（{k} 处）。", detail=f"{n.path} · 改了 {k} 处")
        if action == "move":
            if not new_path.strip():
                return ToolResult("move 要给 new_path。", failed="没给新路径")
            n, was = await memory_notes.move(db, path, new_path, kind)
            return ToolResult(f"{was} → {n.path}。", detail=f"{was} → {n.path}")
        n = await memory_notes.delete(db, path)
        return ToolResult(f"删掉了笔记 {n.path}。", detail=f"{n.path} · 删了")
    except memory_notes.NoteError as e:
        return ToolResult(str(e), failed=str(e)[:40])
