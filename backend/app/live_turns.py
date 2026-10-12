# Design ported from two references (see docs/devlog.md v1.61 and assistant/NOTICE):
# - openai/codex codex-rs/app-server-transport/src/transport/remote_control/websocket.rs
#   (Apache-2.0, Copyright OpenAI) — modified: per-stream contiguous seq ids, bounded outbound
#   buffer, replay-after-cursor on reconnect, duplicate drop by seq on the receiving side.
# - deepseek-harness packages/api/session-controller/src/assistant-stream.ts (MIT) — modified:
#   process-local folded "reconnect baseline" for followers that missed part of the stream.
"""进行中的对话轮次（v1.61）：一轮在服务器上跑，不再绑在某条 WebSocket 上——手机切后台、进电梯、换网络，
回答照常往下写，客户端重连后从断开的地方接着看；另一台设备打开同一个对话也能看到它正在写。

唯一入口：只有本模块持有轮次任务、同对话排队、事件日志和订阅关系；routes/ws.py 只做传输
（收帧 → 调这里；每条连接一个 Conn 出站队列）。

- 游标（Codex remote_control）：一轮里的每个事件都带 turn_id 和从 1 起连续的 seq；客户端重连发
  turn.resume {turn_id?, conversation_id?, after}，服务器补发 seq > after 的事件，客户端按 seq 丢重复。
  出站队列有上限，客户端读不动就断开它（重连后按游标补，不丢），不让慢客户端拖住正在跑的一轮。
- 基线快照（deepseek-harness assistant-stream）：日志只留最近 LOG_MAX 条，同时把这一轮已产出的块和步骤
  折叠成一份；游标落在已丢弃的部分时发 turn.snapshot（整份替换生成中的那条），再接实时事件。
- 生命周期：enqueue → 同一对话前一轮结束后跑 → 结束后再留 KEEP_AFTER_END 秒给迟到的重连拿 message.done → 移除。
  没人看着（订阅的连接全断了）时最多再跑 settings.turn_offline_minutes 分钟，到点按“停止”收尾（半截存为 stopped）；
  设 0 = 旧行为，断线即停。进程重启时轮次随进程消失，由 turn_journal 变成 interrupted 回复（resume 得到 live=false）。"""
import asyncio
import contextlib
import copy
import uuid
from collections import deque
from collections.abc import Awaitable, Callable

from .config import settings

KEEP_AFTER_END = 120.0  # 秒：一轮结束后还留多久（重连的客户端要拿到 message.done）
LOG_MAX = 2000          # 每轮保留的事件条数；更早的靠快照
OUTBOX_MAX = 5000       # 每条连接排队未写出的事件上限（Codex 的 BoundedOutboundBuffer 思路）
TERMINAL = {"message.done", "message.stopped", "error"}


class Conn:
    """一条客户端连接的出站队列：put 立即返回（轮次产事件时不等网络），writer 任务按序写出。
    写失败或积压超过 OUTBOX_MAX → 标记关闭并调用 on_overflow（ws.py 关掉这条 WebSocket，客户端会重连再 resume）。"""

    def __init__(self, send: Callable[[dict], Awaitable[None]],
                 on_overflow: Callable[[], Awaitable[None]] | None = None):
        self._send, self._on_overflow = send, on_overflow
        self._q: asyncio.Queue = asyncio.Queue()
        self.closed = False
        self._writer = asyncio.create_task(self._drain())

    def put(self, event: dict) -> None:
        if self.closed:
            return
        if self._q.qsize() >= OUTBOX_MAX:
            self._fail()
            return
        self._q.put_nowait(event)

    async def _drain(self) -> None:
        try:
            while True:
                await self._send(await self._q.get())
        except asyncio.CancelledError:
            raise
        except Exception:
            self._fail()

    def _fail(self) -> None:
        if self.closed:
            return
        self.closed = True
        detach(self)
        if self._on_overflow is not None:
            asyncio.get_running_loop().create_task(self._on_overflow())
        if asyncio.current_task() is not self._writer:
            self._writer.cancel()

    async def flush(self, timeout: float = 2.0) -> None:
        """测试 / 关闭前用：等队列写空。"""
        with contextlib.suppress(asyncio.TimeoutError):
            async with asyncio.timeout(timeout):
                while not self._q.empty() and not self.closed:
                    await asyncio.sleep(0.01)

    def close(self) -> None:
        self.closed = True
        self._writer.cancel()
        detach(self)


class Turn:
    """一轮：handler 产出的事件编号、记日志、折叠成快照、推给所有订阅的连接。"""

    def __init__(self, key: str):
        self.id = uuid.uuid4().hex
        self.key = key
        self.conv_id: str | None = None
        self.seq = 0
        self.log: deque[dict] = deque(maxlen=LOG_MAX)
        self.blocks: list[dict] = []
        self.steps: list[dict] = []
        self.subs: set[Conn] = set()
        self.stop = asyncio.Event()
        self.task: asyncio.Task | None = None
        self.running = False
        self.ended = False
        self._orphan: asyncio.TimerHandle | None = None

    async def emit(self, event: dict) -> None:
        self.seq += 1
        e = {**event, "turn_id": self.id, "seq": self.seq}
        self._fold(e)
        self.log.append(e)
        for conn in list(self.subs):
            conn.put(e)

    def _fold(self, e: dict) -> None:
        match e.get("type"):
            case "message.start":
                self.conv_id = e.get("conversation_id")
                if self.conv_id:
                    _by_conv[self.conv_id] = self
                    # 新对话的第一轮：之后同一对话的请求要排在它后面
                    t = _tails.get(self.conv_id)
                    if self.task is not None and t is not self.task and (t is None or t.done()):
                        _tails[self.conv_id] = self.task
                        self.task.add_done_callback(
                            lambda x, k=self.conv_id: _tails.pop(k, None) if _tails.get(k) is x else None)
            case "block.start" | "block.update":
                i, block = e.get("index"), copy.deepcopy(e.get("block"))
                if isinstance(i, int) and 0 <= i <= len(self.blocks) and isinstance(block, dict):
                    if i == len(self.blocks):
                        self.blocks.append(block)
                    else:
                        self.blocks[i] = block
            case "block.delta":
                i = e.get("index")
                if isinstance(i, int) and 0 <= i < len(self.blocks) and self.blocks[i].get("type") == "text":
                    self.blocks[i]["text"] = (self.blocks[i].get("text") or "") + (e.get("text") or "")
            case "tool.status":
                step = e.get("step")
                if isinstance(step, dict) and step.get("id"):
                    for k, s in enumerate(self.steps):
                        if s.get("id") == step["id"]:
                            self.steps[k] = {**s, **step}
                            break
                    else:
                        self.steps.append(dict(step))

    def snapshot(self) -> dict:
        """折叠好的“到目前为止”：客户端整份替换生成中的那条。已结束的轮次快照停在终止事件之前，终止事件另补。"""
        terminal = self.ended and self.log and self.log[-1].get("type") in TERMINAL
        return {"type": "turn.snapshot", "turn_id": self.id, "seq": self.seq - (1 if terminal else 0),
                "conversation_id": self.conv_id,
                "message": {"blocks": copy.deepcopy(self.blocks), "steps": copy.deepcopy(self.steps)}}


_turns: dict[str, Turn] = {}
_by_conv: dict[str, Turn] = {}
_tails: dict[str, asyncio.Task] = {}

Handler = Callable[[Callable[[dict], Awaitable[None]], dict, asyncio.Event], Awaitable[None]]


def enqueue(handler: Handler, event: dict, conn: Conn) -> Turn:
    """排一轮：同一对话一次只跑一轮、按到达顺序（上一轮发完 message.done 后还要收尾一小会儿，紧接着来的请求不能丢）；
    新对话各自独立。发起的连接自动订阅。"""
    cid = event.get("conversation_id")
    key = cid if isinstance(cid, str) and cid else f"new:{uuid.uuid4().hex}"
    turn = Turn(key)
    turn.subs.add(conn)
    _turns[turn.id] = turn
    prev = _tails.get(key)
    turn.task = asyncio.create_task(_run(turn, prev, handler, event))
    _tails[key] = turn.task
    turn.task.add_done_callback(lambda t, k=key: _tails.pop(k, None) if _tails.get(k) is t else None)
    return turn


async def _run(turn: Turn, prev: asyncio.Task | None, handler: Handler, event: dict) -> None:
    try:
        if prev is not None:
            await asyncio.wait({prev})  # 只等它结束；上一轮失败 / 被停止都与这一轮无关
        turn.running = True
        await handler(turn.emit, event, turn.stop)
    except asyncio.CancelledError:
        # 停止落在 run_turn 之外（还在排队 / 存用户消息）：同样算正常结束
        if not turn.stop.is_set():
            raise
        asyncio.current_task().uncancel()
        await turn.emit({"type": "message.stopped", "conversation_id": turn.conv_id})
    finally:
        turn.running = False
        turn.ended = True
        if turn._orphan is not None:
            turn._orphan.cancel()
        with contextlib.suppress(RuntimeError):
            asyncio.get_running_loop().call_later(KEEP_AFTER_END, _forget, turn)


def _forget(turn: Turn) -> None:
    _turns.pop(turn.id, None)
    if turn.conv_id and _by_conv.get(turn.conv_id) is turn:
        _by_conv.pop(turn.conv_id, None)


def stop(conn: Conn, conversation_id: str | None) -> None:
    """message.cancel：只停正在跑的那轮。带 conversation_id 就必须对得上（旧界面残留的停止键不能误伤别的对话），
    任何连接都能停（断线重连后、另一台设备上）；不带 = 停这条连接订阅着的、正在跑的轮次。没有在跑的 = 刚好说完，忽略。"""
    for turn in list(_turns.values()):
        if not turn.running or turn.stop.is_set() or turn.task is None:
            continue
        if conversation_id:
            hit = turn.conv_id == conversation_id or (turn.conv_id is None and turn.key == conversation_id)
        else:
            hit = conn in turn.subs
        if hit:
            turn.stop.set()
            turn.task.cancel()


def resume(conn: Conn, event: dict) -> None:
    """turn.resume {turn_id?, conversation_id?, after?}：
    - 带 turn_id（断线前就在看这一轮）：哪怕已结束（还在保留期）也补发，客户端拿到 message.done 收尾。
    - 只带 conversation_id（刚打开对话 / 不知道 turn_id）：只接正在跑或排队的轮次；已结束的回复已在 GET 里，不重放。
    找不到 → turn.resumed {live: false}，客户端以 GET 为准。"""
    tid, cid = event.get("turn_id"), event.get("conversation_id")
    tid = tid if isinstance(tid, str) else None
    cid = cid if isinstance(cid, str) and cid else None
    turn = _turns.get(tid) if tid else None
    if turn is None and cid:
        turn = _by_conv.get(cid)
        if turn is None:  # 排队中、还没发 message.start 的轮次
            turn = next((t for t in _turns.values() if t.key == cid and not t.ended), None)
        if turn is not None and turn.ended:
            turn = None
    if turn is not None and cid and turn.conv_id not in (None, cid):
        turn = None
    if turn is None:
        conn.put({"type": "turn.resumed", "turn_id": tid, "conversation_id": cid, "live": False})
        return
    after = event.get("after")
    after = after if isinstance(after, int) and not isinstance(after, bool) and after >= 0 else 0
    after = min(after, turn.seq)
    oldest = turn.log[0]["seq"] if turn.log else turn.seq + 1
    gap = after + 1 < oldest
    _attach(turn, conn)
    conn.put({"type": "turn.resumed", "turn_id": turn.id, "conversation_id": turn.conv_id or cid, "live": True,
              "ended": turn.ended, "seq": turn.seq, "gap": gap})
    if gap:
        snap = turn.snapshot()
        conn.put(snap)
        for e in turn.log:
            if e["seq"] > snap["seq"]:
                conn.put(e)
    else:
        for e in turn.log:
            if e["seq"] > after:
                conn.put(e)


def _attach(turn: Turn, conn: Conn) -> None:
    turn.subs.add(conn)
    if turn._orphan is not None:
        turn._orphan.cancel()
        turn._orphan = None


def detach(conn: Conn) -> None:
    """连接断了：从所有轮次退订；没人看着的轮次开始计时（turn_offline_minutes；0 = 立刻按停止收尾）。"""
    for turn in list(_turns.values()):
        if conn not in turn.subs:
            continue
        turn.subs.discard(conn)
        if turn.subs or turn.ended or turn._orphan is not None:
            continue
        minutes = settings.turn_offline_minutes
        if minutes <= 0:
            _halt(turn)
        else:
            turn._orphan = asyncio.get_running_loop().call_later(minutes * 60, _halt, turn)


def _halt(turn: Turn) -> None:
    turn._orphan = None
    if turn.subs or turn.ended or turn.task is None or turn.task.done():
        return
    turn.stop.set()
    turn.task.cancel()


async def drain(timeout: float = 5.0) -> None:
    """测试用：等所有轮次结束。"""
    tasks = [t.task for t in _turns.values() if t.task is not None and not t.task.done()]
    if tasks:
        await asyncio.wait(tasks, timeout=timeout)
