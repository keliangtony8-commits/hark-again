"""WebSocket 传输层：收消息、收审批答复、推事件。一轮对话放进后台任务，
这样生成过程中仍能收到用户对审批卡的回复。业务流程在 agent/runner.py。"""
import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..agent import approvals
from ..agent.runner import RewindError, apply_model, rewind, run_turn
from ..auth import verify_token
from ..blocks import FileBlock, text_to_blocks
from ..db import SessionLocal
from ..models import Conversation, Message
from ..storage import mime_of, upload_path

router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    try:
        verify_token(ws.query_params.get("token", ""))
    except Exception:
        await ws.close(code=4401)
        return
    await ws.accept()
    turns = _Turns(ws)
    try:
        while True:
            event = await ws.receive_json()
            match event.get("type"):
                case "user.message":
                    turns.enqueue(_handle_user_message, event)
                case "message.regenerate":
                    turns.enqueue(_handle_regenerate, event)
                case "message.cancel":
                    turns.stop(event.get("conversation_id"))
                case "approval.reply":
                    approvals.resolve(str(event.get("id")), bool(event.get("approved")))
    except WebSocketDisconnect:
        turns.close()


class _Turns:
    """一条连接上的对话轮次。

    - 排队：一次只跑一轮，新请求排在上一轮后面而不是丢掉——上一轮发完 message.done/error 后还要收尾一小会儿，
      客户端这时立刻发来的下一条（比如马上点“重新生成”）若被丢掉，界面会一直转圈。
    - 停止：记住正在跑的那轮和它的对话；message.cancel 先 set 停止信号再 cancel，run_turn 据此把半截回复存为
      stopped 并正常结束，排在后面的轮次照跑。
    - 断线：取消所有还没结束的轮次（run_turn 会先把半截回复落库再抛出）。"""

    def __init__(self, ws: WebSocket):
        self._ws = ws
        self._last: asyncio.Task | None = None
        self._all: set[asyncio.Task] = set()
        self._running: asyncio.Task | None = None
        self._conv_id: str | None = None
        self._stop = asyncio.Event()

    def enqueue(self, handler, event: dict) -> None:
        self._last = asyncio.create_task(self._after(self._last, handler, event))
        self._all.add(self._last)
        self._last.add_done_callback(self._all.discard)

    def stop(self, conversation_id: str | None) -> None:
        """只停正在跑的那轮；带了 conversation_id 就必须对得上（旧界面上残留的停止按钮不能误伤别的对话）。
        没有在跑的轮次 = 刚好已经说完，什么也不做：客户端已经收到了 message.done。"""
        task = self._running
        if task is None or task.done() or self._stop.is_set():
            return
        if conversation_id and self._conv_id and conversation_id != self._conv_id:
            return
        self._stop.set()
        task.cancel()

    def close(self) -> None:
        for task in list(self._all):
            task.cancel()

    async def _after(self, prev: asyncio.Task | None, handler, event: dict) -> None:
        if prev is not None:
            await asyncio.wait({prev})  # 只等它结束；上一轮失败/被停止都与这一轮无关
        self._running, self._conv_id, self._stop = asyncio.current_task(), None, asyncio.Event()
        try:
            await handler(self._emit, event, self._stop)
        except asyncio.CancelledError:
            # 停止落在 run_turn 之外（还在存用户消息）：同样算正常结束，告诉客户端这一轮停了
            if not self._stop.is_set():
                raise
            asyncio.current_task().uncancel()
            with contextlib.suppress(Exception):
                await self._ws.send_json({"type": "message.stopped", "conversation_id": self._conv_id})
        finally:
            self._running = None

    async def _emit(self, event: dict) -> None:
        if event.get("type") == "message.start":
            self._conv_id = event.get("conversation_id")
        await self._ws.send_json(event)


async def _approve(aid: str, _title: str, _detail: str) -> bool:
    return await approvals.wait(aid)  # 审批卡已随事件流推给前端，这里只等用户答复


async def _handle_user_message(emit, event: dict, stop: asyncio.Event) -> None:
    text = (event.get("text") or "").strip()
    files = _attachments(event.get("attachments") or [])
    if not text and not files:
        return
    async with SessionLocal() as db:
        conv = await db.get(Conversation, event.get("conversation_id")) if event.get("conversation_id") else None
        if conv is None:
            conv = Conversation(title=(text or files[0]["name"])[:40], project_id=event.get("project_id"))
            db.add(conv)
            await db.flush()
        apply_model(conv, event.get("model"))
        user_msg = Message(conversation_id=conv.id, role="user",
                           blocks=(text_to_blocks(text) if text else []) + files)
        db.add(user_msg)
        await db.commit()
        await emit({"type": "message.start", "conversation_id": conv.id,
                    "user_message_id": user_msg.id, "title": conv.title})
        await run_turn(db, conv, emit=emit, approve=_approve, stop=stop)


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
        if "model" in event:  # “换个模型重答”：和 user.message 一样记到对话上
            apply_model(conv, event["model"])
            await db.commit()
        await emit({"type": "message.start", "conversation_id": conv.id,
                    "user_message_id": user_msg.id, "title": conv.title, "replaced": replaced,
                    **({"user_message": user_msg.to_wire()} if isinstance(text, str) else {})})
        await run_turn(db, conv, emit=emit, approve=_approve, stop=stop)


def _attachments(ids: list[str]) -> list[dict]:
    """只接受服务器上真实存在的上传，前端传来的名字/类型一律不信。"""
    out = []
    for uid in ids[:10]:
        if p := upload_path(str(uid)):
            out.append(FileBlock(source="upload", id=str(uid), name=p.name, mime=mime_of(p.name),
                                 size=p.stat().st_size).model_dump())
    return out
