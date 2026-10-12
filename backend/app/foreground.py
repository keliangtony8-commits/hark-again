"""前台跑一条命令（沙盒 /exec/stream）并把结果整理好：唯一入口。

run_command 工具（模型发起）和 user_shell（用户在输入框里打 `!命令` 自己跑）共用它，所以两边对
退出码、超时、OOM、二进制输出、超长输出（中间省略 + 工作区 .spill/ 全文）、休眠唤醒的说法完全一致。
给模型的话（提示怎么改）留在各自的调用方。"""
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from . import command_env, jobs, sandbox_client, spill, term_text

MAX_SECONDS = 120  # 沙盒前台单次上限（sandbox/runner.py 同一个数）


@dataclass
class Outcome:
    failed: str = ""         # 没拿到结果时的短原因（沙盒出错 / 沙盒没响应 / 沙盒连接中断）；空 = 有结果
    message: str = ""        # 同上，完整一句（给模型 / 给用户）
    exit_code: int | None = None
    timed_out: bool = False
    oom: bool = False
    memory_limit: object = None
    status: str = ""         # 退出码 N / 超时被终止 / 内存超上限…（退出码 N）
    out: str = ""            # 给模型：中间省略处换成 spill 提示（完整输出在哪个文件）
    shown: str = ""          # 给人看：中间省略处一句“省略 N 字符”
    woke: object = None      # 这条命令把休眠的电脑开起来了：原因（computer.wake_note 用）
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.failed and self.exit_code == 0 and not self.timed_out


async def run(workspace: str, command: str, timeout: int, stdin: str | None = None,
              live: Callable[[str], None] | None = None, env: dict[str, str] | None = None) -> Outcome:
    """timeout 秒（夹到 1..MAX_SECONDS）。live(tail)：每来一段输出给一次最近的终端尾巴（运行中的卡片）。
    env：用户的命令环境变量（command_env.load）；输出里的值一律打码（live 尾巴、out、shown 都过 command_env.scrub）。
    调用方被取消（用户停止）→ 连接关闭 → 沙盒整组杀掉命令；CancelledError 原样抛出。"""
    started = time.monotonic()
    tail, r = "", None
    try:
        async for ev in sandbox_client.stream(workspace, command, max(1, min(timeout, MAX_SECONDS)), stdin,
                                              **({"env": env} if env else {})):
            if ev["type"] == "out":
                tail = term_text.tail(tail + ev["data"])
                if live is not None:
                    live(command_env.scrub(tail, env))
            elif ev["type"] == "exit":
                r = ev
            elif ev["type"] == "error":
                return Outcome("沙盒出错", f"沙盒出错（{ev.get('error', '')}），命令的结果不确定。",
                               seconds=time.monotonic() - started)
    except httpx.HTTPError as e:
        return Outcome("沙盒没响应", f"沙盒没响应（{type(e).__name__}），命令没有执行。", seconds=time.monotonic() - started)
    seconds = time.monotonic() - started
    if r is None:
        return Outcome("沙盒连接中断", "沙盒连接中断，命令的结果不确定。", seconds=seconds)
    timed_out = bool(r.get("timed_out"))
    status = "超时被终止" if timed_out else f"退出码 {r['exit_code']}"
    if r.get("oom"):  # 沙盒比过 cgroup 的 OOM 计数：确实是内存超上限被内核杀的
        status = f"{jobs.OOM_REASON}（退出码 {r['exit_code']}）"
    # 终端文本统一洗一遍（颜色转义、\r 进度帧）；二进制输出沙盒已换成一句说明
    out = shown = command_env.scrub(term_text.clean(r.get("output", "")), env)
    if r.get("binary") is not None:
        out, shown = term_text.binary_note(r["binary"]), f"（二进制输出，{r['binary']} 字节，不显示）"
    if spill.MARK in out:  # 沙盒那边输出太长：中间段省略，完整输出（能存下时）写进了工作区 .spill/
        omitted = r.get("omitted", 0)
        note = spill.notice(omitted, r.get("spill"), r.get("total", 0))
        if r.get("spill_truncated"):  # 沙盒只存了前 64 MB
            note += "（完整输出太大，文件里只存了开头一部分）"
        out = out.replace(spill.MARK, note)
        shown = shown.replace(spill.MARK, f"\n…（中间省略 {omitted} 字符）…\n")
    return Outcome(exit_code=r.get("exit_code"), timed_out=timed_out, oom=bool(r.get("oom")),
                   memory_limit=r.get("memory_limit"), status=status, out=out, shown=shown,
                   woke=r.get("woke"), seconds=seconds)
