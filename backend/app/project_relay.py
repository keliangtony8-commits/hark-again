"""跨项目协作（对标 Hark 的 projects 工具：看有哪些项目、新建项目、把一件事交给另一个项目）。这是唯一规则。

- list_text：项目清单（名字、id、对话数、最近活动、档案第一行），当前项目标“（就是这里）”。
- create：新建项目（名字去重；可带第一版项目档案）。
- send：把一段话（可带本工作区的文件）交给另一个项目——
  · 落在对方最近的一段普通对话里（没有就新开一段；定时任务的报告对话不算）；
  · 存成一条用户消息：[origin 块（谁转来的、第几手），文字，文件块]，对方助手立刻在那段对话里接着做（answer 钩子：
    routes/ws 注册成和“补充的话另起一轮”同一条路，worker 进程里没有 ws 就用这里的默认做法）；
  · 文件复制进对方工作区 received/（同名加 (2)，隐藏目录拒绝，过对方磁盘配额）——“把文件放进别的项目，同时一定发消息告诉它”合成一步；
  · 防转圈：转来的消息再转出去算第 2 手，超过 DEPTH_MAX 拒绝；每轮最多 PER_TURN_MAX 条；不能发给自己所在的项目。
- render：origin 块给模型的一句话（这不是用户本人直接说的，是哪边的助手代用户转来的）。
发送方回复里放一张 relay 卡（发给了谁、哪段对话、带了哪些文件，点开就到那段对话）；接收方气泡上方一枚“来自 X”标签。
"""
import asyncio
import re
import shutil
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from . import project_brief, quota, workspaces
from .blocks import FileBlock, OriginBlock, RelayBlock
from .models import Conversation, Message, Project, TaskRun
from .storage import hidden, mime_of, project_dir, project_file

TEXT_MAX = 4000          # 一条转交的话最多多少字（再长就写成文件一起带过去）
FILES_MAX = 5
FILE_MAX = 50 * 1024 * 1024
DEPTH_MAX = 2            # 转来的消息最多再转一手
PER_TURN_MAX = 3         # 一轮里最多发几条
NAME_MAX = 60
LIST_MAX = 30
RECEIVED_DIR = "received"
MAIN_NAME, MAIN_EMOJI = "主聊天", "💬"
PREVIEW_MAX = 200        # relay 卡上显示的预览字数


class RelayError(ValueError):
    """给模型看的中文原因。"""


@dataclass
class Sent:
    project: Project
    conversation_id: str
    message_id: str
    new_conversation: bool
    files: list[dict] = field(default_factory=list)
    depth: int = 1


# ---------------------------------------------------------------- 项目

def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


async def find(db: AsyncSession, ref: str) -> Project:
    """按 id、名字（忽略大小写和空白）找；名字不全时唯一包含也算。找不到 / 有歧义 → RelayError。"""
    ref = (ref or "").strip()
    if not ref:
        raise RelayError("没说是哪个项目：project 填项目名字或 id（先 action=list 看有哪些）。")
    if p := await db.get(Project, ref):
        return p
    rows = (await db.scalars(select(Project))).all()
    key = _norm(ref)
    exact = [p for p in rows if _norm(p.name) == key]
    if len(exact) == 1:
        return exact[0]
    part = exact or [p for p in rows if key and key in _norm(p.name)]
    if len(part) == 1:
        return part[0]
    if part:
        raise RelayError("有几个项目都叫这个：" + "、".join(f"{p.name}（{p.id}）" for p in part[:5]) + "。用 id 指定。")
    raise RelayError(f"没有叫「{ref}」的项目。先 action=list 看有哪些；要新建用 action=create。")


def _aware(t):
    return t if t is None or t.tzinfo else t.replace(tzinfo=timezone.utc)


async def list_text(db: AsyncSession, here: str | None) -> str:
    rows = (await db.scalars(select(Project).order_by(Project.updated_at.desc()))).all()
    if not rows:
        return "还没有任何项目。用户有一件独立、会长期积累文件的事时，可以建议新建一个（action=create），由他决定。"
    stats = {pid: (n, last) for pid, n, last in (await db.execute(
        select(Conversation.project_id, func.count(Conversation.id), func.max(Conversation.updated_at))
        .where(Conversation.project_id.in_([p.id for p in rows])).group_by(Conversation.project_id))).all()}
    lines = []
    for p in rows[:LIST_MAX]:
        n, last = stats.get(p.id, (0, None))
        when = max(t for t in (_aware(p.updated_at), _aware(last)) if t is not None)
        brief = next((ln.strip(" #-") for ln in (p.brief or p.rules or "").splitlines() if ln.strip(" #-")), "")
        mark = "（就是这里）" if p.id == here else ""
        lines.append(f"- {p.emoji} {p.name}{mark}  id={p.id}  {n} 个对话  最近 {when:%Y-%m-%d %H:%M} UTC"
                     + (f"\n  {brief[:80]}" if brief else ""))
    more = f"\n（还有 {len(rows) - LIST_MAX} 个没列出）" if len(rows) > LIST_MAX else ""
    return f"共 {len(rows)} 个项目：\n" + "\n".join(lines) + more


async def create(db: AsyncSession, name: str, emoji: str = "", brief: str = "") -> Project:
    name = re.sub(r"\s+", " ", name or "").strip()
    if not name:
        raise RelayError("项目要有名字。")
    if len(name) > NAME_MAX:
        raise RelayError(f"名字太长（最多 {NAME_MAX} 字）。")
    if any(_norm(p.name) == _norm(name) for p in (await db.scalars(select(Project))).all()):
        raise RelayError(f"已经有叫「{name}」的项目了：要往里交代事情用 action=message。")
    p = Project(name=name, emoji=(emoji or "📁").strip()[:8] or "📁")
    if brief.strip():
        if err := project_brief.write(p, brief):
            raise RelayError(err)
    db.add(p)
    await db.commit()
    return p


# ---------------------------------------------------------------- 转交

def origin_of(blocks: list[dict] | None) -> dict | None:
    return next((b for b in blocks or [] if b.get("type") == "origin"), None)


def render(b: dict) -> str:
    """origin 块给模型的话（当前这一问和历史里都一样）。"""
    src = b.get("name") or MAIN_NAME
    return (f"[这条消息不是用户本人在这里说的：是「{src}」那边的助手替用户转交过来的（第 {b.get('depth', 1)} 手）。"
            "按这个项目的档案和用户的长期偏好去做；做完的结果留在这段对话里，用户会在这里看到。"
            "需要用户本人拍板的事（花钱、对外发送、删东西）照常先问他，不要当作他已经同意。]")


_sent: "OrderedDict[tuple[str, str], int]" = OrderedDict()  # (发送方对话, 那一轮的锚点) → 这一轮已发几条；进程内足够


async def _anchor(db: AsyncSession, cid: str | None) -> tuple[str, int]:
    """发送方这一轮的锚点（最后一条用户消息 id）和这一轮自己是第几手转来的（那条消息的 origin.depth，没有 = 0）。"""
    if not cid:
        return "", 0
    last = await db.scalar(select(Message).where(Message.conversation_id == cid, Message.role == "user")
                           .order_by(Message.created_at.desc()).limit(1))
    if last is None:
        return "", 0
    o = origin_of(last.blocks)
    return last.id, int(o.get("depth", 1)) if o else 0


async def target_conversation(db: AsyncSession, project_id: str) -> Conversation | None:
    """对方项目里最近更新的普通对话（定时任务跑出来的报告对话不算）；没有 → None（调用方新开）。"""
    task_convs = select(TaskRun.conversation_id).where(TaskRun.conversation_id.is_not(None))
    return await db.scalar(select(Conversation).where(Conversation.project_id == project_id,
                                                      Conversation.id.not_in(task_convs))
                           .order_by(Conversation.updated_at.desc()).limit(1))


def _free_name(root, name: str) -> str:
    stem, suffix = PurePosixPath(name).stem, PurePosixPath(name).suffix
    cand, i = name, 2
    while (root / RECEIVED_DIR / cand).exists():
        cand, i = f"{stem} ({i}){suffix}", i + 1
    return cand


def _check_files(src_ws: str, paths: list[str]):
    if len(paths) > FILES_MAX:
        raise RelayError(f"一次最多带 {FILES_MAX} 个文件；多了先打包成 zip 再带。")
    out = []
    for rel in paths:
        rel = str(rel or "").strip().lstrip("/")
        if rel.startswith("workspace/"):
            rel = rel[len("workspace/"):]
        if not rel:
            continue
        parts = PurePosixPath(rel).parts
        if hidden(parts):
            raise RelayError(f"{rel} 在隐藏目录里（日志、密钥、家目录），不能带去别的项目。")
        p = project_file(src_ws, rel)
        if p is None:
            raise RelayError(f"工作区里没有文件 {rel}（目录要先打包成 zip）。")
        if p.stat().st_size > FILE_MAX:
            raise RelayError(f"{rel} 太大（上限 {quota.size_text(FILE_MAX)}）。")
        out.append((rel, p))
    return out


def _copy(dst_ws: str, files) -> list[dict]:
    total = sum(p.stat().st_size for _, p in files)
    if not files:
        return []
    quota.check(dst_ws, total)  # QuotaError 由调用方转成原因
    root = project_dir(dst_ws)
    (root / RECEIVED_DIR).mkdir(parents=True, exist_ok=True)
    blocks = []
    for _rel, p in files:
        name = _free_name(root, p.name)
        dest = root / RECEIVED_DIR / name
        shutil.copy2(p, dest)
        blocks.append(FileBlock(source="project", id=f"{RECEIVED_DIR}/{name}", name=name, mime=mime_of(name),
                                size=dest.stat().st_size, project_id=dst_ws).model_dump())
    quota.forget(dst_ws)
    return blocks


async def send(db: AsyncSession, source_conversation_id: str | None, source_project_id: str | None,
               ref: str, text: str, paths: list[str] | None = None) -> Sent:
    text = (text or "").strip()
    if not text:
        raise RelayError("要交代的话是空的：text 写清楚要对方做什么（对方看不到这段对话，背景要写全）。")
    if len(text) > TEXT_MAX:
        raise RelayError(f"太长了（{len(text)} 字，上限 {TEXT_MAX}）：长材料写成文件，用 files 一起带过去。")
    if text[0] in "!！/":  # 对方会把开头的 !命令 / /init 当成用户的本地命令
        raise RelayError("不要以 ! 或 / 开头：写成一句话交代要做什么。")
    target = await find(db, ref)
    if target.id == source_project_id:
        raise RelayError("这就是当前项目，不用转交，直接在这里做。")
    anchor, depth = await _anchor(db, source_conversation_id)
    if depth + 1 > DEPTH_MAX:
        raise RelayError(f"这件事本身就是别的项目转来的（已经第 {depth} 手），不能再往外转：在这里做完，或者告诉用户需要他去对方项目里说。")
    key = (source_conversation_id or "", anchor)
    if _sent.get(key, 0) >= PER_TURN_MAX:
        raise RelayError(f"这一轮已经转交了 {PER_TURN_MAX} 条，先别再发了。")
    files = _check_files(workspaces.of(source_project_id), [str(x) for x in paths or []])
    try:
        file_blocks = _copy(target.id, files)
    except quota.QuotaError as e:
        raise RelayError(f"对方项目的磁盘放不下这些文件：{e}") from e
    if source_project_id and (src := await db.get(Project, source_project_id)):
        name, emoji = src.name, src.emoji
    else:
        name, emoji = MAIN_NAME, MAIN_EMOJI
    conv = await target_conversation(db, target.id)
    new = conv is None
    if new:
        conv = Conversation(project_id=target.id, title=f"来自{name}：{text.splitlines()[0][:24]}", title_source="first")
        db.add(conv)
        await db.flush()
    origin = OriginBlock(name=name, emoji=emoji, project_id=source_project_id,
                         conversation_id=source_conversation_id, depth=depth + 1).model_dump()
    msg = Message(conversation_id=conv.id, role="user",
                  blocks=[origin, {"type": "text", "text": text}, *file_blocks])
    db.add(msg)
    conv.updated_at = datetime.now(timezone.utc)  # 对方历史里这段对话排到最上面
    await db.commit()
    _sent[key] = _sent.get(key, 0) + 1
    _sent.move_to_end(key)
    while len(_sent) > 256:
        _sent.popitem(last=False)
    answer(conv.id, msg.id)
    return Sent(target, conv.id, msg.id, new, file_blocks, depth + 1)


def card(s: Sent, text: str) -> dict:
    """发送方回复里的 relay 卡。"""
    return RelayBlock(project_id=s.project.id, name=s.project.name, emoji=s.project.emoji, conversation_id=s.conversation_id,
                      text=text[:PREVIEW_MAX] + ("…" if len(text) > PREVIEW_MAX else ""),
                      files=[b["name"] for b in s.files], new_conversation=s.new_conversation).model_dump()


def for_model(s: Sent) -> str:
    where = "新开的一段对话" if s.new_conversation else "最近的那段对话"
    files = f"；文件已放进对方工作区 {', '.join(b['id'] for b in s.files)}" if s.files else ""
    return (f"已交给「{s.project.emoji} {s.project.name}」项目（{where}），那边的助手已经开始处理{files}。"
            "结果会留在那个项目里，不会自动传回来；用一句话告诉用户交出去了、去哪看，用户已经能看到转交卡。")


# ---------------------------------------------------------------- 让对方接着做

Answer = Callable[[str, str], None]
_answer: Answer | None = None
_tasks: set[asyncio.Task] = set()


def set_answerer(fn: Answer | None) -> None:
    """routes/ws 注册：live_turns.follow(…, _handle_pending)（有人看着那段对话就实时推，审批卡照常弹）。"""
    global _answer
    _answer = fn


def answer(conversation_id: str, message_id: str) -> None:
    if _answer is not None:
        _answer(conversation_id, message_id)
        return
    from . import live_turns  # worker 进程：同样排进那段对话的轮次队列，没人看着按断线计时
    live_turns.follow(conversation_id, _default_handler, {"conversation_id": conversation_id, "message_id": message_id})


async def _default_handler(emit, event: dict, stop: asyncio.Event) -> None:
    from .agent.runner import run_turn  # 避免 import 环：runner → 工具 → 这里
    from .db import SessionLocal
    async with SessionLocal() as db:
        conv = await db.get(Conversation, event.get("conversation_id"))
        if conv is None:
            return
        await emit({"type": "message.start", "conversation_id": conv.id, "user_message_id": event.get("message_id"),
                    "title": conv.title})
        await run_turn(db, conv, emit=emit, stop=stop)
