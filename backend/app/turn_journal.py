# Copyright (c) 2026 DeepSeek — MIT License (see assistant/NOTICE)
# Ported from deepseek-ai/deepseek-harness packages/core/session/src/repair.ts (MIT), adapted:
#   TOOL_NOT_STARTED / TOOL_OUTCOME_UNKNOWN 两种结论、“开始了但结果没落盘 = 结果未知，只读/幂等才重试，有副作用先核实或问用户，
#   别盲目重试”的措辞、闭合顺序（先补未答的调用，再闭合这一轮）按原意翻译。
# 改动：①deepseek 的会话本身就是事件日志，我们的回复只在一轮结束时整条落库，所以另记一张检查点表（turn_journals），
#        崩溃后把它转成 status=interrupted 的助手消息，而不是往日志尾巴补事件；
#      ②我们的步骤在工具真正开跑时才记（activity.Recorder.start），检查点里只会有“开始了”的步骤 → 只用得到 OUTCOME_UNKNOWN；
#        还没开跑的调用随这一轮一起消失（模型下一轮看到的是文字历史，没有悬空的 tool_call 需要配对）；
#      ③嫁接 Codex core/src/context/turn_aborted.rs：给模型的历史里在被打断的回复后面附一段 <turn_aborted> 说明，
#        用户中途停止（status=stopped）也附（Codex INTERRUPTED_GUIDANCE：被停下的命令可能执行了一部分）；
#      ④嫁接心跳（deepseek 靠单进程写日志，我们有 backend + worker 两个进程）：owner = 进程:启动 id，同类进程换了启动 id
#        或心跳超过 STALE_S 没动 = 那个进程已经没了。
"""一轮回答的崩溃恢复（唯一入口）。

一轮开始 open() 记一行检查点；跑的过程中 seen(event) 在工具开始/结束、新块出现时（文字最多每 SAVE_S 一次）
把当前的块和步骤存进去，另有心跳每 BEAT_S 刷一次 beat_at；正常结束、用户停止、出错都由 runner 自己落库，close() 删掉这行。
进程被杀（OOM、断电、docker 重启）时这行留下：recover() 把它转成一条 status=interrupted 的助手消息——
半截文字保留、实时块定格（loop.settle_blocks）、还在跑的步骤标 stopped + 结果未知；模型下一轮从 history_note 知道发生了什么。

recover 的时机：backend / worker 启动时（各收各的：同类进程上一次启动留下的），每轮开始前和打开对话时（按心跳判断，
收另一个进程留下的）。假设每类进程只跑一个（deploy 里 uvicorn 单 worker、worker 单实例）。
检查点写入用自己的短会话、失败只记日志：它是保险，不能拖垮这一轮。"""
import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import SessionLocal
from .models import Message, TurnJournal

log = logging.getLogger(__name__)

TOOL_NOT_STARTED = "TOOL_NOT_STARTED"  # deepseek 原有；我们的步骤开跑才记，用不到，保留名字对照
TOOL_OUTCOME_UNKNOWN = "TOOL_OUTCOME_UNKNOWN"

BEAT_S = 20.0  # 心跳间隔（长命令跑着时也证明进程还活着）
STALE_S = 90.0  # 心跳多久没动算进程没了（> 4 次心跳）
SAVE_S = 3.0  # 只有文字在涨时，检查点最多这么久存一次

UNKNOWN_NOTE = "服务器重启时它还在跑，结果没记下来，可能已经执行了一部分"

BOOT = uuid.uuid4().hex[:12]
_process = "backend"


def claim(process: str) -> None:
    """进程启动时声明自己是谁（"backend" | "worker"）；只影响 owner 的前缀。"""
    global _process
    _process = process


def owner() -> str:
    return f"{_process}:{BOOT}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(t: datetime | None) -> datetime | None:
    return t.replace(tzinfo=timezone.utc) if t is not None and t.tzinfo is None else t  # SQLite 读回无时区 = UTC


def dead(row_owner: str, beat_at: datetime | None, now: datetime | None = None) -> bool:
    """这行检查点的主人是不是已经没了：同类进程换了启动 id，或者心跳太久没动。"""
    proc, _, boot = (row_owner or "").partition(":")
    if proc == _process and boot != BOOT:
        return True
    beat = _aware(beat_at)
    return beat is None or ((now or _now()) - beat).total_seconds() > STALE_S


def interrupted_steps(steps: list[dict]) -> list[dict]:
    """还在跑的步骤 → stopped + 结果未知（deepseek TOOL_OUTCOME_UNKNOWN）；其余原样。"""
    return [{**s, "state": "stopped", "note": UNKNOWN_NOTE, "code": TOOL_OUTCOME_UNKNOWN}
            if s.get("state") == "running" else dict(s) for s in steps or []]


def _step_line(s: dict) -> str:
    return f"- {s.get('title') or s.get('tool') or '操作'}" + (f"：{s['detail']}" if s.get("detail") else "")


def history_note(status: str, steps: list[dict]) -> str:
    """给模型的历史里附在被打断的回复后面（Codex turn_aborted 的形状，deepseek 的措辞）。done → 空串。"""
    if status == "interrupted":
        unknown = [s for s in steps or [] if s.get("code") == TOOL_OUTCOME_UNKNOWN]
        head = "这一轮回答被服务器重启打断了，没有说完（不是用户停的）。"
        if not unknown:
            body = "用户要是让你继续，从断开的地方接着做，先说一句刚才被打断了。"
        else:
            body = ("这些操作开始了，但结果没记下来，可能已经执行了一部分：\n" + "\n".join(_step_line(s) for s in unknown)
                    + "\n要不要重做看操作本身：只读或可以重复执行的才重做；可能有副作用的（改文件、装东西、发消息、下单、改服务器）"
                      "先核实现状或问用户，别盲目重试。")
        return f"\n\n<turn_aborted>\n{head}\n{body}\n</turn_aborted>"
    if status == "stopped":
        cut = [s for s in steps or [] if s.get("state") == "stopped"]
        body = "用户中途停止了这一轮。"
        if cut:
            body += "被停下的操作可能执行了一部分：\n" + "\n".join(_step_line(s) for s in cut)
        return f"\n\n<turn_aborted>\n{body}\n</turn_aborted>"
    return ""


async def recover(db: AsyncSession, conversation_id: str | None = None, now: datetime | None = None) -> int:
    """把主人已经没了的检查点转成 interrupted 消息；返回条数。conversation_id 给了只看那个对话。"""
    from .agent.loop import settle_blocks  # 避免循环导入（loop → tools → … → models）
    q = select(TurnJournal)
    if conversation_id is not None:
        q = q.where(TurnJournal.conversation_id == conversation_id)
    rows = [r for r in (await db.scalars(q)).all() if dead(r.owner, r.beat_at, now)]
    for r in rows:
        db.add(Message(conversation_id=r.conversation_id, role="assistant", status="interrupted",
                       blocks=settle_blocks(r.blocks or []), steps=interrupted_steps(r.steps or []),
                       created_at=_aware(r.started_at) or _now()))
        await db.delete(r)
    if rows:
        await db.commit()
        log.warning("recovered %d interrupted turn(s)", len(rows))
    return len(rows)


async def busy(db: AsyncSession, conversation_id: str, now: datetime | None = None) -> bool:
    """这个对话有一轮正在进行（检查点在、主人还活着）。手动整理上文等“别在回复中途动历史”的操作看它。"""
    rows = (await db.scalars(select(TurnJournal).where(TurnJournal.conversation_id == conversation_id))).all()
    return any(not dead(r.owner, r.beat_at, now) for r in rows)


async def recover_all(process: str) -> int:
    """进程启动：声明身份 + 收掉上一次启动留下的。失败（表还没建等）只记日志。"""
    claim(process)
    try:
        async with SessionLocal() as db:
            return await recover(db)
    except Exception:  # noqa: BLE001
        log.exception("turn journal recovery failed")
        return 0


class Journal:
    """一轮的检查点。runner 用法：open() → 每个事件 seen(ev, builder) → finally close()。"""

    def __init__(self, conversation_id: str, task_id: str | None = None) -> None:
        self.conversation_id, self.task_id = conversation_id, task_id
        self.id: str | None = None
        self._beat: asyncio.Task | None = None
        self._saved = 0.0

    async def _write(self, **values) -> None:
        if self.id is None:
            return
        try:
            async with SessionLocal() as db:
                row = await db.get(TurnJournal, self.id)
                if row is None:
                    return
                for k, v in values.items():
                    setattr(row, k, v)
                await db.commit()
        except Exception as e:  # noqa: BLE001 — 保险而已
            log.warning("turn journal write failed: %s", e)

    async def open(self) -> None:
        try:
            async with SessionLocal() as db:
                row = TurnJournal(conversation_id=self.conversation_id, task_id=self.task_id, owner=owner(),
                                  blocks=[], steps=[])
                db.add(row)
                await db.commit()
                self.id = row.id
        except Exception as e:  # noqa: BLE001
            log.warning("turn journal open failed: %s", e)
            return
        self._beat = asyncio.create_task(self._beating())

    async def _beating(self) -> None:
        while True:
            await asyncio.sleep(BEAT_S)
            await self._write(beat_at=_now())

    async def save(self, builder) -> None:
        """存当前的块和步骤（原样：实时块、running 步骤都留着，恢复时才定格）。"""
        self._saved = time.monotonic()
        await self._write(blocks=[dict(b) for b in builder.blocks], steps=builder.steps(), beat_at=_now())

    async def seen(self, ev, builder) -> None:
        """每个内核事件过一下：工具开始/结束、新块、块替换立刻存；文字增量攒着，最多每 SAVE_S 存一次。"""
        from .agent import loop
        if isinstance(ev, (loop.ToolStatus, loop.BlockStart, loop.BlockUpdate)):
            await self.save(builder)
        elif isinstance(ev, loop.TextDelta):
            if time.monotonic() - self._saved >= SAVE_S:
                await self.save(builder)

    async def drop(self, db: AsyncSession) -> None:
        """把删检查点并进调用方的事务：runner 存回复时同一次 commit，回复落库和检查点消失要么都发生、要么都没发生
        （先发 message.done 再删的话，客户端一断线、这一轮在删的时候被取消，就会留下检查点被误恢复成第二条回复）。"""
        if self.id is not None:
            await db.execute(delete(TurnJournal).where(TurnJournal.id == self.id))

    def dropped(self) -> None:
        """drop 所在的事务已提交。"""
        self.id = None

    async def close(self) -> None:
        """停心跳；还没删的（没回复、出错、停止时没内容）删掉。删除放在 shield 里：这一轮被取消也要删完。"""
        if self._beat is not None:
            self._beat.cancel()
            self._beat = None
        if self.id is None:
            return
        jid, self.id = self.id, None
        await asyncio.shield(_delete(jid))


async def _delete(jid: str) -> None:
    try:
        async with SessionLocal() as db:
            await db.execute(delete(TurnJournal).where(TurnJournal.id == jid))
            await db.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("turn journal close failed: %s", e)
