# Portions ported from openai/codex (Apache-2.0):
#   codex-rs/core/src/tasks/user_shell.rs, codex-rs/core/src/context/user_shell_command.rs,
#   codex-rs/core/src/user_shell_command.rs — modified (sandbox stream instead of a local shell,
#   Chinese wording, ShellBlock card, record kept in the message instead of a history item).
# Output cap and escaping idea from google-gemini/gemini-cli (Apache-2.0):
#   packages/cli/src/ui/hooks/useExecutionLifecycle.ts addShellCommandToGeminiHistory — modified.
"""用户自己跑命令：输入框里以 ! 开头的消息不经过模型，直接在这段对话的工作区电脑上前台执行。
唯一入口：认不认（parse / command_of）、卡片（block）、模型以后怎么看到（record / reply_block）、执行（run）。

学 Codex 的 `!命令`（user_shell.rs）：
- 不调模型、不花 token；结果作为“用户那边发生的事”记进历史（<user_shell_command> 片段，Codex 原格式），
  下一次问助手时它能看到命令和输出（“刚才那个报错怎么修”）。
- 被停止 = 命令被整组杀掉，记成 stopped（Codex：command aborted by user，退出码 -1）。
嫁接 Gemini CLI：进历史的输出有上限（MAX_OUTPUT_LENGTH 10000）；我们按中间省略截（日志的尾巴更要紧）。
自己的规则：沙盒前台上限 120 秒（长活让助手放后台）；毁系统的命令照样拦（command_guard，用户自己发也不放行，
沙盒里 rm -rf / 没有任何好处）；计划模式不管它（那是约束模型的）；附件消息不算命令。"""
import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from . import command_env, command_guard, computer, foreground, quota, workspaces
from .config import settings
from .models import Message

Emit = Callable[[dict], Awaitable[None]]

PREFIXES = ("!", "！")  # 中文输入法打出来的全角叹号也算
COMMAND_MAX = 4000
OUTPUT_MAX = 10000  # 进历史给模型的输出上限（Gemini MAX_OUTPUT_LENGTH）
LIVE_S = 0.5  # 运行中卡片最多这么久推一次
STATES = ("running", "done", "failed", "timeout", "stopped", "refused", "error")
OPEN, CLOSE = "<user_shell_command>", "</user_shell_command>"  # Codex type_markers
LEAD = "用户自己在这段对话的电脑（工作区）上运行了一条命令——不是你执行的，结果给你参考，被问到时接着用："
STATE_TEXT = {"timeout": "超时被终止", "stopped": "用户中途停止，命令被终止", "refused": "被安全规则拦下，没有执行",
              "error": "没有拿到结果"}


def parse(text: object) -> str | None:
    """整条消息是不是一条用户命令：去掉首尾空白后以 ! / ！ 开头、后面还有东西 → 命令；否则 None（照常问助手）。"""
    if not settings.user_shell or not isinstance(text, str):
        return None
    t = text.strip()
    if not t or t[0] not in PREFIXES:
        return None
    return t[1:].strip() or None


def command_of(blocks: list[dict]) -> str | None:
    """一条用户消息（存库的块）是不是命令：只有一个文字块（带附件的不算）。"""
    if len(blocks) != 1 or blocks[0].get("type") != "text":
        return None
    return parse(blocks[0].get("text"))


def block(command: str, state: str = "running", output: str = "", exit_code: int | None = None,
          seconds: float | None = None, note: str | None = None) -> dict:
    out = {"type": "shell", "command": command, "state": state, "output": output}
    if exit_code is not None:
        out["exit_code"] = exit_code
    if seconds is not None:
        out["seconds"] = round(seconds, 2)
    if note:
        out["note"] = note
    return out


def reply_block(blocks: list[dict]) -> dict | None:
    """这条助手消息是不是用户命令的结果（只有一张 shell 卡）。"""
    if len(blocks) == 1 and blocks[0].get("type") == "shell":
        return blocks[0]
    return None


def _clip(text: str, limit: int = OUTPUT_MAX) -> str:
    if len(text) <= limit:
        return text
    head = limit * 2 // 5
    tail = limit - head
    return f"{text[:head]}\n…（中间省略 {len(text) - limit} 字符）…\n{text[-tail:]}"


def _safe(text: str) -> str:
    """输出里出现结束标记不能让片段提前“闭合”（Gemini 转义反引号的同一个考虑）。"""
    return text.replace(CLOSE, "</user_shell_command\u200b>").replace(OPEN, "<user_shell_command\u200b>")


def record(b: dict) -> str:
    """给模型的历史文本：Codex UserShellCommand.body 的格式（Exit code / Duration / Output），前面一句说明是谁跑的。"""
    state = b.get("state", "done")
    code = b.get("exit_code")
    result = f"Exit code: {code}" if code is not None else "Exit code: -1"
    if state in STATE_TEXT:
        result += f"（{STATE_TEXT[state]}）"
    body = _clip(b.get("output") or "")
    note = f"\n{b['note']}" if b.get("note") else ""
    return (f"{LEAD}\n{OPEN}\n<command>\n{_safe(b.get('command', ''))}\n</command>\n<result>\n{result}\n"
            f"Duration: {float(b.get('seconds') or 0):.4f} seconds\nOutput:\n{_safe(body)}{_safe(note)}\n</result>\n{CLOSE}")


def summary(b: dict) -> str:
    """一行（搜索 / 导出 / blocks_to_text）。"""
    state = b.get("state")
    what = STATE_TEXT.get(state) or (f"退出码 {b['exit_code']}" if b.get("exit_code") is not None else "运行中")
    out = (b.get("output") or "").strip()
    return f"[用户自己运行：$ {b.get('command', '')}——{what}]" + (f"\n{out[-600:]}" if out else "")


def _note(r: foreground.Outcome) -> str | None:
    """卡片底下给人看的一句（不是给模型的提示）。"""
    parts = []
    if r.timed_out:
        parts.append(f"前台最多 {foreground.MAX_SECONDS} 秒；长活让助手用后台任务跑")
    if r.oom:
        parts.append("内存超过这台电脑的上限，被系统结束了")
    if r.woke in computer.WAKE_TEXT:
        parts.append(f"电脑刚才{computer.WAKE_TEXT[r.woke]}，这条命令把它重新开机了；之前在前台跑的程序已经停了")
    return "；".join(parts) or None


async def run(db: AsyncSession, conversation_id: str, project_id: str | None, command: str,
              emit: Emit, stop: asyncio.Event | None = None) -> Message:
    """执行并落库一条助手消息（一张 shell 卡），推 block.start / block.update / message.done。
    被取消：用户点了停止（stop 已 set）→ 存成 stopped 正常返回；断线 / 关机 → 存下后把取消继续抛出（同 runner）。"""
    ws = workspaces.of(project_id)
    started = time.monotonic()
    if len(command) > COMMAND_MAX:
        b = block(command[:200] + "…", "refused", note=f"命令太长（上限 {COMMAND_MAX} 字），写成脚本文件再运行")
        return await _save(db, conversation_id, b, emit)
    if (v := command_guard.verdict(command)) is not None and v.level in ("block", "unsupported"):
        why = f"被安全规则拦下了（{v.why}），没有执行" if v.level == "block" else f"没有执行：{v.why}"
        return await _save(db, conversation_id, block(command, "refused", note=why), emit)
    await _try(emit, {"type": "block.start", "index": 0, "block": block(command)})
    latest: list[str] = []  # 最近一次的终端尾巴（foreground 的 live 回调是同步的，推送放到 ticker 里）

    async def ticker() -> None:
        sent = None
        while True:
            await asyncio.sleep(LIVE_S)
            if latest and latest[-1] != sent:
                sent = latest[-1]
                await _try(emit, {"type": "block.update", "index": 0, "block": block(command, output=sent)})

    def live(tail: str) -> None:
        latest[:] = [tail]

    tick = asyncio.create_task(ticker())
    interrupted = False
    try:
        r = await foreground.run(ws, command, settings.user_shell_seconds, None, live, await command_env.load(db))
    except asyncio.CancelledError:
        if (task := asyncio.current_task()) is not None:
            task.uncancel()
        interrupted = not (stop and stop.is_set())
        b = block(command, "stopped", latest[-1] if latest else "", -1, time.monotonic() - started, "已停止")
        r = None
    finally:
        tick.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tick
    if r is not None:
        if r.failed:
            b = block(command, "error", "", None, r.seconds, r.message)
        else:
            state = "timeout" if r.timed_out else ("done" if r.exit_code == 0 else "failed")
            b = block(command, state, r.out.strip(), r.exit_code, r.seconds, _note(r))
    quota.forget(ws)  # 命令可能写了大东西：下次用量重数
    reply = await _save(db, conversation_id, b, emit)
    if interrupted:
        raise asyncio.CancelledError
    return reply


async def _save(db: AsyncSession, conversation_id: str, b: dict, emit: Emit) -> Message:
    with contextlib.suppress(Exception):
        await db.rollback()
    reply = Message(conversation_id=conversation_id, role="assistant", blocks=[b],
                    status="stopped" if b["state"] == "stopped" else "done")
    db.add(reply)
    await db.commit()
    await _try(emit, {"type": "message.done", "message": reply.to_wire()})
    return reply


async def _try(emit: Emit, event: dict) -> None:
    with contextlib.suppress(Exception):
        await emit(event)
