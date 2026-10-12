"""把一条回复存成项目文件（v1.15）——唯一入口。
- markdown(blocks)：回复 → 一份能单独读的 Markdown（表格是真表格、链接带标题、草稿/摘要带标题）；
  只属于那一刻的卡（审批、表单、记忆、浏览器画面）不进文件。
- file_name(blocks, at)：文件名 = 摘要/草稿/表格标题 > 正文第一个标题 > 第一行字，去掉非法字符、最长 NAME_MAX；
  都没有 → “回复 MM-DD HHMM”。
- save(db, message_id, project_id)：工作区 = 传入的 project_id（主聊天里可选任意项目或 "me" 我的文件）
  或对话所在工作区（项目 / 个人）；写到根目录，同名不覆盖（“名字 2.md”）。
  错误：LookupError（消息/项目不存在）、ValueError（不是回复、没内容）。"""
import re
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from . import quota, storage, workspaces
from .blocks import blocks_to_text
from .config import settings
from .models import Conversation, Message

NAME_MAX = 24
SKIP = {"approval", "form", "memory", "browser", "job", "plan", "delegate"}
_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def _cell(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def _block_md(b: dict) -> str:
    t = b.get("type")
    if t in SKIP:
        return ""
    if t == "text":
        return b.get("text", "").strip()
    if t == "code":
        head = f"**{b['title']}**\n\n" if b.get("title") else ""
        return f"{head}```{b.get('language', '')}\n{b['source'].rstrip()}\n```"
    if t == "table":
        cols = b["columns"]
        lines = ["| " + " | ".join(_cell(c) for c in cols) + " |", "|" + "---|" * len(cols)]
        lines += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in b["rows"]]
        head = f"**{b['title']}**\n\n" if b.get("title") else ""
        note = f"\n\n{b['note']}" if b.get("note") else ""
        return head + "\n".join(lines) + note
    if t == "stats":
        return "\n".join(f"- {i['label']}：**{i['value']}**" + (f"（{i['note']}）" if i.get("note") else "") for i in b["items"])
    if t == "links":
        return "\n".join(f"- [{i.get('title') or i.get('label') or i['url']}]({i['url']})" for i in b["items"])
    if t == "page":
        return f"[{b['title']}]({b['url']})"
    if t == "file":
        return f"- 附件：{b['name']}"
    if t == "draft":
        return f"## {b['title']}\n\n{b['body'].strip()}"
    if t == "summary":
        sub = f"\n\n*{b['subtitle']}*" if b.get("subtitle") else ""
        return f"# {b['title']}{sub}\n\n{b['markdown'].strip()}"
    if t == "images":
        return "\n\n".join(f"![{i.get('caption') or ''}]({i['url']})" for i in b["items"])
    if t == "products":
        head = f"**{b['title']}**\n\n" if b.get("title") else ""
        rows = []
        for i in b["items"]:
            name = f"[{i['name']}]({i['url']})" if i.get("url") else i["name"]
            rows.append("- " + " · ".join(x for x in (name, i.get("price"), i.get("meta")) if x))
        pick = f"\n\n推荐：{b['pick']}" if b.get("pick") else ""
        return head + "\n".join(rows) + pick
    return blocks_to_text([b]).strip()


def markdown(blocks: list[dict]) -> str:
    parts = [m for m in (_block_md(b) for b in blocks) if m]
    return ("\n\n".join(parts) + "\n") if parts else ""


def _clean(s: str) -> str:
    s = re.sub(r"[#*_`>\[\]]", "", s)
    s = re.sub(r"\(https?://[^)]*\)", "", s)
    s = _BAD.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip().strip(".").strip()
    return s[:NAME_MAX].rstrip(" ，,。.;；:：")


def file_name(blocks: list[dict], at: datetime | None = None) -> str:
    """不带扩展名的文件名。"""
    for b in blocks:
        if b.get("type") in ("summary", "draft") or (b.get("type") in ("table", "products") and b.get("title")):
            if n := _clean(b["title"]):
                return n
    texts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
    for t in texts:  # 第一个 Markdown 标题
        for line in t.splitlines():
            if re.match(r"^#{1,6}\s", line.strip()) and (n := _clean(line)):
                return n
    for t in texts:  # 第一行字（列表符号去掉）
        for line in t.splitlines():
            if n := _clean(re.sub(r"^\s*([-*+]|\d+\.)\s+", "", line)):
                return n
    at = at or datetime.now(timezone.utc)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        at = at.astimezone(ZoneInfo(settings.timezone))
    except Exception:
        pass
    return f"回复 {at:%m-%d %H%M}"


def _free_path(root, base: str):
    p = root / f"{base}.md"
    n = 2
    while p.exists():
        p = root / f"{base} {n}.md"
        n += 1
    return p


async def save(db: AsyncSession, message_id: str, project_id: str | None = None) -> dict:
    msg = await db.get(Message, message_id)
    if not msg:
        raise LookupError("消息不存在")
    if msg.role != "assistant":
        raise ValueError("只能存助手的回复")
    text = markdown(msg.blocks or [])
    if not text.strip():
        raise ValueError("这条回复没有可存的内容")
    conv = await db.get(Conversation, msg.conversation_id)
    pid = project_id or workspaces.of(conv.project_id if conv else None)  # 主聊天不指定 = 我的文件
    where = await workspaces.name(db, pid)
    if where is None:
        raise LookupError("项目不存在")
    try:
        quota.check(pid, len(text.encode()))
    except quota.QuotaError as e:
        raise ValueError(str(e)) from e
    root = storage.project_dir(pid)
    p = _free_path(root, file_name(msg.blocks or [], msg.created_at))
    p.write_text(text, encoding="utf-8")
    quota.forget(pid)
    rel = str(p.relative_to(root))
    return {"project_id": pid, "project_name": where, "path": rel, "name": p.name,
            "size": p.stat().st_size, "mime": storage.mime_of(p.name)}
