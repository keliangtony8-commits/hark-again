"""WebSocket 传输层：收消息、收审批答复、推事件。轮次的排队、停止、断线续传都归 live_turns（一轮不绑在连接上），
这里只把帧交给它；业务流程在 agent/runner.py。"""
import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import conversation_title, file_mentions, live_turns, skill_mentions, user_shell, workspaces
from ..agent import approvals
from ..agent.runner import RewindError, apply_choice, rewind, run_turn
from ..auth import verify_token
from ..blocks import FileBlock, text_to_blocks
from ..db import SessionLocal
from ..models import Conversation, Message
from ..storage import mime_of, project_file, project_file_root, upload_path

router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    try:
        verify_token(ws.query_params.get("token", ""))
    except Exception:
        await ws.close(code=4401)
        return
    await ws.accept()

    async def overflow() -> None:  # 客户端读不动：断开，它重连后按游标补（live_turns.Conn）
        with contextlib.suppress(Exception):
            await ws.close(code=1013)

    conn = live_turns.Conn(ws.send_json, overflow)
    try:
        while True:
            event = await ws.receive_json()
            match event.get("type"):
                case "user.message":
                    live_turns.enqueue(_handle_user_message, event, conn)
                case "message.regenerate":
                    live_turns.enqueue(_handle_regenerate, event, conn)
                case "message.cancel":
                    live_turns.stop(conn, event.get("conversation_id"))
                case "turn.resume":
                    live_turns.resume(conn, event)
                case "ping":
                    conn.put({"type": "pong"})
                case "approval.reply":
                    approvals.resolve(str(event.get("id")), bool(event.get("approved")), event.get("option"))
                case "form.reply":
                    approvals.resolve_form(str(event.get("id")), event.get("values"), event.get("remember"))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        conn.close()  # 退订；回答在服务器上接着跑（live_turns：没人看着最多再跑 turn_offline_minutes）


async def _approve(aid: str, _title: str, _detail: str) -> bool:
    return await approvals.wait(aid)  # 审批卡已随事件流推给前端，这里只等用户答复


async def _ask(fid: str, form: dict):
    return await approvals.wait_form(fid, [f["name"] for f in form.get("fields", [])])  # 表单卡已推给前端


async def _handle_user_message(emit, event: dict, stop: asyncio.Event) -> None:
    text = (event.get("text") or "").strip()
    async with SessionLocal() as db:
        conv = await db.get(Conversation, event.get("conversation_id")) if event.get("conversation_id") else None
        pid = conv.project_id if conv is not None else event.get("project_id")
        if workspaces.is_personal(pid) or not isinstance(pid, str):
            pid = None  # 主聊天：对话不属于任何项目（个人工作区不是项目）
        files = _attachments(event.get("attachments") or [])
        files += await _project_files(db, pid, event.get("project_files") or [], MAX_FILES - len(files), text)
        if not text and not files:
            return
        if conv is None:
            conv = Conversation(title=conversation_title.first_title(text or files[0]["name"]),
                                title_source=conversation_title.FIRST, project_id=pid)
            db.add(conv)
            await db.flush()
        apply_choice(conv, event)
        user_msg = Message(conversation_id=conv.id, role="user",
                           blocks=(text_to_blocks(text) if text else []) + files + _skills(text))
        db.add(user_msg)
        await db.commit()
        await emit({"type": "message.start", "conversation_id": conv.id,
                    "user_message_id": user_msg.id, "title": conv.title})
        await _answer(db, conv, user_msg, emit, stop)


async def _handle_regenerate(emit, event: dict, stop: asyncio.Event) -> None:
    """重新生成最后一条回复（或上一轮失败时重试；带 text = 编辑最后一条用户消息后重答）：
    删旧回复 →（改写用户消息）→ 再跑一轮。"""
    text = event.get("text")
    async with SessionLocal() as db:
        try:
            conv, user_msg, replaced = await rewind(db, str(event.get("conversation_id") or ""),
                                                    event.get("message_id") or None,
                                                    text if isinstance(text, str) else None)
        except RewindError as e:
            await emit({"type": "error", "message": str(e)})
            return
        if isinstance(text, str):  # 编辑后的文字里新写的 @路径 / $技能：补上引用（原有附件保留，不重复；技能按新文字重认）
            await _add_mentions(db, conv, user_msg, text)
        if "model" in event or "reasoning" in event:  # “换个模型 / 思考强度重答”：和 user.message 一样记到对话上
            apply_choice(conv, event)
            await db.commit()
        await emit({"type": "message.start", "conversation_id": conv.id,
                    "user_message_id": user_msg.id, "title": conv.title, "replaced": replaced,
                    **({"user_message": user_msg.to_wire()} if isinstance(text, str) else {})})
        await _answer(db, conv, user_msg, emit, stop)


async def _answer(db, conv: Conversation, user_msg: Message, emit, stop: asyncio.Event) -> None:
    """回答一条用户消息：`!命令` 直接在工作区电脑上跑（user_shell，不调模型；重新生成 = 再跑一次），
    其余交给模型（run_turn）。停掉的半截不起名，下一轮再试；第一轮失败后点“重试”也起一次。"""
    if (command := user_shell.command_of(user_msg.blocks)) is not None:
        await user_shell.run(db, conv.id, conv.project_id, command, emit, stop)
        return
    reply = await run_turn(db, conv, emit=emit, approve=_approve, stop=stop, ask=_ask)
    if reply is not None and reply.status != "stopped":
        conversation_title.schedule(conv.id, emit)  # 后台起标题，不挡排队的下一轮


MAX_FILES = 10  # 一条消息最多带几个文件（上传 + 项目文件合计）


def _attachments(ids: list[str]) -> list[dict]:
    """只接受服务器上真实存在的上传，前端传来的名字/类型一律不信。"""
    out = []
    for uid in ids[:MAX_FILES]:
        if p := upload_path(str(uid)):
            out.append(FileBlock(source="upload", id=str(uid), name=p.name, mime=mime_of(p.name),
                                 size=p.stat().st_size).model_dump())
    return out


def _skills(text: str) -> list[dict]:
    """text 里的 `$技能` → 技能引用块（规则只在 app/skill_mentions.py）；`!命令` 里的 $ 是 shell 变量，不认。"""
    if not text or user_shell.parse(text) is not None:
        return []
    return skill_mentions.blocks(text)


async def _add_mentions(db, conv: Conversation, user_msg: Message, text: str) -> None:
    have = [b for b in user_msg.blocks if b.get("type") == "file"]
    taken = {b.get("id") for b in have if b.get("source") == "project"}
    extra = await _project_files(db, conv.project_id, [], MAX_FILES, text)
    extra = [b for b in extra if b["id"] not in taken][:MAX_FILES - len(have)]
    skills = [b for b in _skills(text)
              if b["id"] not in {x.get("id") for x in user_msg.blocks if x.get("type") == "skill"}]
    if extra or skills:
        user_msg.blocks = [*user_msg.blocks, *extra, *skills]  # 整体赋值，JSON 列才会被标脏
        await db.commit()


async def _project_files(db, pid: str | None, paths: list, room: int, text: str = "") -> list[dict]:
    """“引用工作区文件”：只认这段对话所在工作区（项目 / 主聊天 = 个人工作区）里真实存在的文件（相对路径，去重）。
    paths = 选择器选的；text 里的 `@路径`（file_mentions，学 Gemini @ 命令）接在后面一起认；`!命令` 不解析（那是给电脑的）。
    消息里只存引用（source=project，id=相对路径，project_id=工作区 id）；内容每轮由 context 从磁盘读。"""
    pid = workspaces.of(pid)
    if room <= 0 or await workspaces.name(db, pid) is None:
        return []
    paths = paths if isinstance(paths, list) else []
    if text and user_shell.parse(text) is None:
        paths = [*paths, *await asyncio.to_thread(file_mentions.paths, text, project_file_root(pid))]
    out, seen = [], set()
    for rel in paths:
        if not isinstance(rel, str) or rel in seen or len(out) >= room:
            continue
        seen.add(rel)
        if p := project_file(pid, rel):
            rel = str(p.relative_to(project_file_root(pid)))
            out.append(FileBlock(source="project", id=rel, name=p.name, mime=mime_of(p.name),
                                 size=p.stat().st_size, project_id=pid).model_dump())
    return out
