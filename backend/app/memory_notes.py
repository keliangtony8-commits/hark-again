"""记忆笔记（v2.21 大脑 az）：一个主题一篇 Markdown —— 唯一规则入口。

为什么有它：一句话记忆（memory_store）适合“不吃香菜”这类单条偏好；关于一个人、一个地方、一个项目的
一串细节（谁、什么关系、生日、上次聊到哪）拆成几十条一句话就散了。Hark 公开行为是“用户档案 + 每个主题一个文件”，
Codex 记忆目录也是“总览常驻上下文、主题文件按需打开”（core-research BRAIN az）。

分层（从总到细）：
- 一句话记忆（profile 等）照旧每轮带进上下文；
- 笔记目录（路径 + 标题 + 第一行）放上下文 STABLE 段末尾（index_text），正文不进上下文，要用时 memory_note read；
- search_memory 同时搜笔记正文（search）。

路径即名字：people/张三、locations/学校、考研计划。kind 决定默认文件夹（contact → people/，place → locations/），
最多两层，大小写不敏感唯一。正文 ≤ BODY_MAX，超了报错不截断（和 task_brief 同一原则：不悄悄丢内容）。
修改用精确查找替换（和 edit_file 一样要求唯一），追加一行用 append，省得模型整篇重写（省 token）。"""
from dataclasses import dataclass
from datetime import timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import chat_search
from .config import settings
from .memory_store import grams
from .models import MemoryNote
from .wire_time import iso

PATH_MAX = 80
SEGMENT_MAX = 40
DEPTH_MAX = 2
TITLE_MAX = 120
BODY_MAX = 20000
NOTES_MAX = 300
INDEX_MAX = 40        # 上下文里最多列几篇（最近更新的）
LINE_CHARS = 60       # 目录里每篇第一行的长度
READ_CHARS = BODY_MAX
SEARCH_LIMIT = 5
SNIPPET = 80

# kind → (中文名, 默认文件夹)
KINDS: dict[str, tuple[str, str]] = {
    "contact": ("人", "people"),
    "place": ("地方", "locations"),
    "project": ("项目", ""),
    "organization": ("组织", ""),
    "interest": ("兴趣", ""),
    "event": ("事件", ""),
    "misc": ("其他", ""),
}
_BAD = set('\\:*?"<>|\0')


class NoteError(ValueError):
    pass


def kind_of(kind: str | None) -> str:
    return kind if kind in KINDS else "misc"


def normalize(path: str, kind: str | None = None) -> str:
    """模型 / 用户给的路径 → 规范路径。去掉开头的 / 和 memory/、结尾的 .md；kind 有默认文件夹而路径没给文件夹时补上。"""
    p = (path or "").strip().replace("\\", "/")
    while p.startswith("/"):
        p = p[1:]
    if p.lower().startswith("memory/"):
        p = p[7:]
    if p.lower().endswith(".md"):
        p = p[:-3]
    segs = [s.strip() for s in p.split("/")]
    if not p or any(not s for s in segs):
        raise NoteError("笔记路径不能为空，也不能有空的一段（如 people/张三）")
    for s in segs:
        if s in (".", "..") or s.startswith("."):
            raise NoteError(f"路径里不能有「{s}」")
        if any(c in _BAD or ord(c) < 32 for c in s):
            raise NoteError("路径里不能有 \\ : * ? \" < > | 这些字符")
        if len(s) > SEGMENT_MAX:
            raise NoteError(f"路径每段最多 {SEGMENT_MAX} 个字")
    folder = KINDS[kind_of(kind)][1]
    if len(segs) == 1 and folder:
        segs = [folder, *segs]
    if len(segs) > DEPTH_MAX:
        raise NoteError(f"路径最多 {DEPTH_MAX} 层（文件夹/名字）")
    out = "/".join(segs)
    if len(out) > PATH_MAX:
        raise NoteError(f"路径最多 {PATH_MAX} 个字")
    return out


def kind_for(path: str, kind: str | None) -> str:
    """没给 kind 时按文件夹猜：people/ → contact，locations/ → place。"""
    if kind in KINDS:
        return kind
    head = path.split("/")[0].lower() if "/" in path else ""
    for k, (_, folder) in KINDS.items():
        if folder and folder == head:
            return k
    return "misc"


def _title(path: str, title: str | None) -> str:
    t = " ".join((title or "").split())[:TITLE_MAX]
    return t or path.split("/")[-1]


def _body(body: str | None) -> str:
    b = (body or "").replace("\r\n", "\n").strip("\n")
    if len(b) > BODY_MAX:
        raise NoteError(f"笔记正文最多 {BODY_MAX} 字（这次 {len(b)} 字）：拆成几篇，或删掉过时的内容")
    return b


def first_line(body: str) -> str:
    """目录 / 列表里的一句话：第一行非空、去掉 Markdown 标题和列表符号。"""
    for line in (body or "").splitlines():
        t = line.strip().lstrip("#").strip().lstrip("-*").strip()
        if t:
            return t[:LINE_CHARS] + ("…" if len(t) > LINE_CHARS else "")
    return ""


async def all_notes(db: AsyncSession) -> list[MemoryNote]:
    return list((await db.scalars(select(MemoryNote).order_by(MemoryNote.updated_at.desc()))).all())


async def find(db: AsyncSession, path: str, kind: str | None = None) -> MemoryNote | None:
    """按路径找（大小写不敏感）；没带文件夹时也认 kind 默认文件夹下的、或唯一同名的那篇。"""
    try:
        want = normalize(path, kind).lower()
        bare = normalize(path).lower()
    except NoteError:
        return None
    notes = await all_notes(db)
    for n in notes:
        if n.path.lower() in (want, bare):
            return n
    if "/" not in bare:  # 只给了名字：唯一同名才认
        same = [n for n in notes if n.path.lower().split("/")[-1] == bare]
        if len(same) == 1:
            return same[0]
    return None


async def _taken(db: AsyncSession, path: str, but: str | None = None) -> bool:
    return any(n.path.lower() == path.lower() and n.id != but for n in await all_notes(db))


async def create(db: AsyncSession, path: str, body: str = "", title: str | None = None,
                 kind: str | None = None) -> MemoryNote:
    p = normalize(path, kind)
    if await _taken(db, p):
        raise NoteError(f"已经有笔记 {p} 了")
    if len(await all_notes(db)) >= NOTES_MAX:
        raise NoteError(f"笔记最多 {NOTES_MAX} 篇：先合并或删掉不用的")
    n = MemoryNote(path=p, title=_title(p, title), kind=kind_for(p, kind), body=_body(body))
    db.add(n)
    await db.commit()
    return n


async def write(db: AsyncSession, path: str, body: str, title: str | None = None,
                kind: str | None = None) -> tuple[MemoryNote, str | None]:
    """整篇写：没有就建，有就覆盖。返回 (笔记, 覆盖前正文或 None)。"""
    n = await find(db, path, kind)
    if n is None:
        return await create(db, path, body, title, kind), None
    previous = n.body
    n.body = _body(body)
    if title and title.strip():
        n.title = _title(n.path, title)
    if kind in KINDS:
        n.kind = kind
    await db.commit()
    return n, previous


async def append(db: AsyncSession, path: str, text: str, title: str | None = None,
                 kind: str | None = None) -> tuple[MemoryNote, bool]:
    """在结尾加一段（另起一行）。没有这篇就新建。返回 (笔记, 是否新建)。"""
    add = (text or "").replace("\r\n", "\n").strip("\n")
    if not add.strip():
        raise NoteError("要追加的内容是空的")
    n = await find(db, path, kind)
    if n is None:
        return await create(db, path, add, title, kind), True
    n.body = _body(f"{n.body}\n{add}" if n.body else add)
    await db.commit()
    return n, False


async def edit(db: AsyncSession, path: str, old: str, new: str, replace_all: bool = False) -> tuple[MemoryNote, int]:
    """精确查找替换（规则同 edit_file）：找不到 / 不唯一 → NoteError。返回 (笔记, 替换了几处)。"""
    n = await find(db, path)
    if n is None:
        raise NoteError(f"没有笔记 {path}")
    if not old:
        raise NoteError("old 不能为空；整篇重写用 action=write")
    count = n.body.count(old)
    if count == 0:
        raise NoteError("正文里没找到 old 这段（要一字不差，含空格换行）：先 read 看原文")
    if count > 1 and not replace_all:
        raise NoteError(f"old 在正文里出现了 {count} 次：多带点上下文让它唯一，或 replace_all=true")
    n.body = _body(n.body.replace(old, new or "") if replace_all else n.body.replace(old, new or "", 1))
    await db.commit()
    return n, count if replace_all else 1


async def move(db: AsyncSession, path: str, new_path: str, kind: str | None = None) -> tuple[MemoryNote, str]:
    n = await find(db, path)
    if n is None:
        raise NoteError(f"没有笔记 {path}")
    p = normalize(new_path, kind)
    if await _taken(db, p, but=n.id):
        raise NoteError(f"已经有笔记 {p} 了")
    old, renamed_title = n.path, n.title == n.path.split("/")[-1]
    n.path = p
    if renamed_title:  # 标题本来就是名字 → 跟着改
        n.title = p.split("/")[-1]
    n.kind = kind_for(p, kind if kind in KINDS else (n.kind if n.kind not in ("contact", "place") else None))
    await db.commit()
    return n, old


async def delete(db: AsyncSession, path: str) -> MemoryNote:
    n = await find(db, path)
    if n is None:
        raise NoteError(f"没有笔记 {path}")
    await db.delete(n)
    await db.commit()
    return n


async def patch(db: AsyncSession, n: MemoryNote, changes: dict) -> MemoryNote:
    """REST PATCH：path / title / kind / body 任意组合，同样的校验。"""
    if "path" in changes and changes["path"] is not None:
        p = normalize(changes["path"], changes.get("kind"))
        if await _taken(db, p, but=n.id):
            raise NoteError(f"已经有笔记 {p} 了")
        n.path = p
    if changes.get("kind") in KINDS:
        n.kind = changes["kind"]
    if changes.get("title") is not None:
        n.title = _title(n.path, changes["title"])
    if changes.get("body") is not None:
        n.body = _body(changes["body"])
    await db.commit()
    return n


# ---- 给模型看 ----
def _day(n: MemoryNote) -> str:
    t = n.updated_at
    if t is None:
        return ""
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    try:
        t = t.astimezone(ZoneInfo(settings.timezone))
    except Exception:  # noqa: BLE001
        pass
    return f"{t:%Y-%m-%d}"


def index_line(n: MemoryNote) -> str:
    head = n.path if n.title == n.path.split("/")[-1] else f"{n.path}「{n.title}」"
    line = first_line(n.body)
    return f"- {head}" + (f"：{line}" if line else "（空）")


def index_text(notes: list[MemoryNote]) -> str:
    """上下文里的笔记目录（最近更新的 INDEX_MAX 篇）；没有笔记 → ""（只在系统提示里说怎么建）。"""
    if not notes:
        return ""
    shown = notes[:INDEX_MAX]
    more = f"\n（还有 {len(notes) - len(shown)} 篇没列出，search_memory 能搜到正文）" if len(notes) > len(shown) else ""
    return ("用户的记忆笔记（一个主题一篇，这里只有目录；要用到某篇的细节先 memory_note read 打开，别凭目录猜）：\n"
            + "\n".join(index_line(n) for n in shown) + more)


def read_text(n: MemoryNote) -> str:
    label = KINDS.get(n.kind, KINDS["misc"])[0]
    head = f"笔记 {n.path}「{n.title}」（{label}，更新于 {_day(n)}，{len(n.body)} 字）"
    return head + "\n" + (n.body if n.body else "（正文是空的）")


@dataclass
class Hit:
    note: MemoryNote
    score: float
    snippet: str


async def search(db: AsyncSession, query: str, limit: int = SEARCH_LIMIT) -> list[Hit]:
    """字面搜：空格 / 引号分开的词（chat_search.terms）在 路径+标题+正文 里全中优先，再按两字词重合。
    笔记正文长、条数少，不做向量（省一次向量接口调用；向量只用在一句话记忆上）。"""
    query = (query or "").strip()
    if not query:
        return []
    terms = chat_search.terms(query)
    q = grams(query)
    hits: list[Hit] = []
    for n in await all_notes(db):
        hay = f"{n.path}\n{n.title}\n{n.body}"
        whole = chat_search.count_in(hay, terms) / len(terms) if terms else 0.0
        part = len(q & grams(hay)) / len(q) if q else 0.0
        if whole > 0 or part >= 0.5:
            hits.append(Hit(n, whole * 2 + part, chat_search.snippet_of(n.body or n.title, terms or [query], SNIPPET)))
    hits.sort(key=lambda h: -h.score)  # 稳定：同分按最近更新
    return hits[:max(1, limit)]


def search_text(hits: list[Hit]) -> str:
    if not hits:
        return ""
    return ("笔记里相关的（memory_note read 打开全文）：\n"
            + "\n".join(f"- {h.note.path}「{h.note.title}」：{h.snippet}" for h in hits))


def list_text(notes: list[MemoryNote]) -> str:
    if not notes:
        return "还没有记忆笔记。"
    return f"共 {len(notes)} 篇笔记（最近更新在前）：\n" + "\n".join(
        index_line(n) + f" · 更新于 {_day(n)}" for n in notes)


# ---- 接口 ----
def wire(n: MemoryNote) -> dict:
    return {"id": n.id, "path": n.path, "title": n.title, "kind": n.kind, "body": n.body,
            "created_at": iso(n.created_at), "updated_at": iso(n.updated_at)}
