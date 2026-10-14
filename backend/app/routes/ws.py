"""WebSocket 传输层：收消息、收审批答复、推事件。轮次的排队、停止、断线续传都归 live_turns（一轮不绑在连接上），
这里只把帧交给它；业务流程在 agent/runner.py。"""
import asyncio
import contextlib
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import logging

from .. import agent_mentions, conversation_title, file_mentions, init_command, live_turns, project_relay, reply_quote, run_conversations, skill_mentions, steering, user_shell, workspaces
from ..agent import approvals, context
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
        await verify_token(ws.query_params.get("token", ""))
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
                    # 回答途中补充（steering）：插得进正在跑的那一轮就插，插不进（已收尾 / 插满 / !命令、@子助手）照常排队成下一轮
                    if not (event.get("steer") and await _steer(event)):
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
        run_conversations.promote(conv)  # 在定时任务的运行对话里接话 = 普通对话了，进列表
        follow = await agent_mentions.follow(db, conv.id, event.get("follow"), event.get("follow_title")) if text else []
        user_msg = Message(conversation_id=conv.id, role="user",
                           blocks=(text_to_blocks(text) if text else []) + files + _skills(text) + (follow or _agents(text)),
                           reply_to=await reply_quote.valid(db, conv.id, event.get("reply_to")))
        db.add(user_msg)
        await db.commit()
        await emit({"type": "message.start", "conversation_id": conv.id,
                    "user_message_id": user_msg.id, "title": conv.title, **_client_id(event)})
        await _answer(db, conv, user_msg, emit, stop)


def _client_id(event: dict) -> dict:
    """客户端给消息的本地 id 原样带回：想插进上一轮却排成了新一轮的那句，客户端据此把气泡挪到对的位置。"""
    c = event.get("client_id")
    return {"client_id": c} if isinstance(c, str) and c and len(c) <= 64 else {}


async def _steer(event: dict) -> bool:
    """回答途中补充：文字、附件、@文件、$技能都能插（steering.reason；!命令、/init、@子助手 排队），交给正在跑的那一轮
    （steering.offer，模型看到的内容按“当前这一问”渲染：context.render_now），存成 status=steer 的用户消息
    （块和普通提问一样；created_at = 收下那一刻，早于这一轮的回复），在这一轮的事件流里推 turn.steered。
    返回 False = 没插进去，调用方照常排队。"""
    cid, text = event.get("conversation_id"), (event.get("text") or "").strip()
    if not isinstance(cid, str) or not steering.active(cid) or event.get("reply_to"):
        return False  # 引用回复是新的一件事：排成下一轮（模型要在那一轮的开头看到被引原文）
    ids, picked = event.get("attachments") or [], event.get("project_files") or []
    ids, picked = (ids if isinstance(ids, list) else []), (picked if isinstance(picked, list) else [])
    if steering.reason(text, files=len(ids) + len(picked), agent=bool(_agents(text) or event.get("follow")),
                       command=user_shell.parse(text) is not None or init_command.parse(text) is not None):
        return False
    async with SessionLocal() as db:
        conv = await db.get(Conversation, cid)
        if conv is None:
            return False
        files = _attachments(ids)
        files += await _project_files(db, conv.project_id, picked, MAX_FILES - len(files), text)
        if not text and not files:  # 附件全是假的：交给排队那条路去拒
            return False
        blocks = (text_to_blocks(text) if text else []) + files + _skills(text)
        rich = any(b.get("type") != "text" for b in blocks)
        content = await context.render_now(blocks, steering.model_of(cid)) if rich else text
        msg = Message(id=uuid.uuid4().hex, conversation_id=cid, role="user", blocks=blocks, status=steering.STEER)
        if (item := steering.offer(cid, text, msg.id, content)) is None:  # 不 await 地收下：模型下一次调用前就能读到
            return False
        msg.created_at = item.at
        db.add(msg)
        try:
            await db.commit()
        except Exception:  # 模型已经读到了；只是历史里少这一句
            logging.getLogger(__name__).exception("saving steer message failed")
            return True
    await live_turns.note(cid, {"type": "turn.steered", "conversation_id": cid, "message": msg.to_wire(), **_client_id(event)})
    return True


async def _handle_pending(emit, event: dict, stop: asyncio.Event) -> None:
    """上一轮收尾时还没读到的补充：另起一轮回答它（消息已在库里，不再新建）。"""
    async with SessionLocal() as db:
        conv = await db.get(Conversation, event.get("conversation_id"))
        msg = await db.get(Message, event.get("message_id")) if conv is not None else None
        if conv is None or msg is None or msg.conversation_id != conv.id:
            return
        await emit({"type": "message.start", "conversation_id": conv.id, "user_message_id": msg.id, "title": conv.title})
        await _answer(db, conv, msg, emit, stop)


# 别的项目转交来的消息（project_relay.send 已落库）：和“补充的话另起一轮”同一条路——有人看着就实时推，审批卡照常弹
project_relay.set_answerer(lambda cid, mid: live_turns.follow(cid, _handle_pending, {"conversation_id": cid, "message_id": mid}))


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
        if run_conversations.promote(conv) or "model" in event or "reasoning" in event:  # 重答运行对话也算接话
            await db.commit()
        await emit({"type": "message.start", "conversation_id": conv.id,
                    "user_message_id": user_msg.id, "title": conv.title, "replaced": replaced,
                    **({"user_message": await reply_quote.wire_one(db, user_msg)} if isinstance(text, str) else {})})
        await _answer(db, conv, user_msg, emit, stop)


async def _answer(db, conv: Conversation, user_msg: Message, emit, stop: asyncio.Event) -> None:
    """回答一条用户消息：`!命令` 直接在工作区电脑上跑（user_shell，不调模型；重新生成 = 再跑一次），
    其余交给模型（run_turn）。停掉的半截不起名，下一轮再试；第一轮失败后点“重试”也起一次。"""
    if (command := user_shell.command_of(user_msg.blocks)) is not None:
        await user_shell.run(db, conv.id, conv.project_id, command, emit, stop)
        return
    if init_command.of(user_msg.blocks) is not None and init_command.existing(workspaces.of(conv.project_id)):
        await _say(db, conv.id, init_command.DECLINE, emit)  # Gemini：已有就不调模型，直接回一句
        return
    cid = conv.id
    inbox = steering.open_inbox(cid)  # 这一轮跑模型期间，用户补充的话插得进来（steering.py）
    try:
        reply = await run_turn(db, conv, emit=emit, approve=_approve, stop=stop, ask=_ask, inbox=inbox)
    finally:
        left = steering.close(inbox)
    if left and not stop.is_set():  # 模型已经收尾 / 预算到头才到的补充：紧接着另起一轮回答（用户点了停止就不自动接）
        live_turns.follow(cid, _handle_pending, {"conversation_id": cid, "message_id": left[-1].message_id})
    if reply is not None and reply.status != "stopped":
        conversation_title.schedule(cid, emit)  # 后台起标题，不挡排队的下一轮


async def _say(db, cid: str, text: str, emit) -> None:
    """不调模型的一句回复（/init 已有 AGENTS.md 时）：落库一条助手消息，推 message.done。"""
    reply = Message(conversation_id=cid, role="assistant", blocks=text_to_blocks(text), status="done")
    db.add(reply)
    await db.commit()
    await emit({"type": "message.done", "message": reply.to_wire()})


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


def _agents(text: str) -> list[dict]:
    """text 里的 `@子助手` → agent 引用块（规则只在 app/agent_mentions.py）；`!命令` 不认。"""
    if not text or user_shell.parse(text) is not None:
        return []
    return agent_mentions.blocks(text)


async def _add_mentions(db, conv: Conversation, user_msg: Message, text: str) -> None:
    have = [b for b in user_msg.blocks if b.get("type") == "file"]
    taken = {b.get("id") for b in have if b.get("source") == "project"}
    extra = await _project_files(db, conv.project_id, [], MAX_FILES, text)
    extra = [b for b in extra if b["id"] not in taken][:MAX_FILES - len(have)]
    skills = [b for b in _skills(text)
              if b["id"] not in {x.get("id") for x in user_msg.blocks if x.get("type") == "skill"}]
    agents = agent_mentions.blocks(text, user_msg.blocks) if _agents(text) else []
    if extra or skills or agents:
        user_msg.blocks = [*user_msg.blocks, *extra, *skills, *agents]  # 整体赋值，JSON 列才会被标脏
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
