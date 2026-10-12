"""host_command：服务器主机模式下在 VPS 本机（不是沙盒）跑一条命令。审批规则全在 app/host_policy.py，开关/规则/批准在 app/host_mode.py。

流程（Codex：exec_policy 定要不要问 → 审批卡（Approved / ApprovedForSession / ApprovedExecpolicyAmendment）→ 执行）：
1. risk（异步）：开关、已存规则、这段对话里的批准 → 不用问返回 None；要问返回带 options 的主机审批卡；禁止的也返回 None，留给 run 拒绝。
2. run 再判一次（权威）：forbid → 不执行；ask 但没有 grant（无人值守）→ 不执行；批准了 → 先记下用户选的范围再执行。
"""
import httpx

from ... import host_client, host_mode, host_policy, term_text
from ...config import settings
from ..tools import Approval, ToolContext, ToolResult, deny_all, tool


def _unattended(ctx: ToolContext) -> bool:
    return ctx.approve is deny_all  # 定时任务、后台任务结束后的接着说：没人能点卡


async def _requirement(ctx: ToolContext, args: dict) -> host_policy.Requirement:
    proposed = args.get("prefix_rule")
    proposed = [str(w) for w in proposed] if isinstance(proposed, list) else None
    return await host_mode.requirement(ctx.db, str(args.get("command") or ""), ctx.conversation_id,
                                       _unattended(ctx), proposed)


async def _hostname() -> str | None:
    try:
        return (await host_client.health()).get("hostname")
    except (httpx.HTTPError, OSError, ValueError):
        return None


async def _risk(args: dict, ctx: ToolContext):
    req = await _requirement(ctx, args)
    await ctx.db.commit()  # 读过库：SQLite 读事务也要在等用户（可能几分钟）之前放掉
    if req.kind != "ask":
        return None
    note = req.reason or str(args.get("reason") or "").strip()[:120] or None
    card = {"type": "approval", "title": "在服务器上运行命令", "detail": str(args.get("command") or "")[:2000],
            "target": "host", "host": await _hostname(), "note": note, "warn": bool(req.reason),
            "options": host_mode.options(req)}
    return Approval(f"在服务器上运行：{req.reason or '主机命令'}", card)


@tool("host_command", "正在服务器上运行",
      "在这台 VPS 本机以 root 运行一条 shell 命令（不是沙盒）：装系统软件、管 systemd 服务、看 journalctl、改 /etc 配置、看整机资源。"
      "每条都要用户在审批卡上批准；他可以选“这段对话里都允许”或“以后都允许以某前缀开头的命令”。"
      "prefix_rule 可选：建议一个前缀（如 [\"systemctl\", \"status\"]），用户若选“以后都允许”就按它存；太宽的（bash、python、rm、sudo…）不会采用。"
      f"最长 {settings.host_command_max_seconds} 秒；标准输入是空的。毁系统的命令（rm -rf /、格式化、关机）一律拦下。",
      {"type": "object", "properties": {
          "command": {"type": "string"},
          "reason": {"type": "string", "description": "一句话：为什么要在服务器上跑这条（显示在审批卡上）"},
          "timeout": {"type": "integer", "default": 60, "description": f"秒，最多 {settings.host_command_max_seconds}"},
          "prefix_rule": {"type": "array", "items": {"type": "string"},
                          "description": "可选：建议“以后都允许”的命令前缀（字面词）"}},
       "required": ["command", "reason"]},
      scope="host", risk=_risk, grants=True)
async def host_command(ctx: ToolContext, command: str, reason: str = "", timeout: int = 60,
                       prefix_rule: list[str] | None = None, grant: str | None = None) -> ToolResult:
    if not await host_mode.enabled(ctx.db):  # 这一轮中途被关掉了
        await ctx.db.commit()
        return ToolResult("服务器主机模式已经关了，没有执行。", failed="主机模式已关")
    req = await _requirement(ctx, {"command": command, "prefix_rule": prefix_rule})
    if req.kind == "forbid":
        await ctx.db.commit()
        return ToolResult(req.reason, failed="没有执行")
    note = ""
    if req.kind == "ask":
        if grant is None:  # 要问却没人批（无人值守）：evaluate 已按 unattended 判 forbid，这里兜底
            await ctx.db.commit()
            return ToolResult("这条主机命令需要用户批准，现在没人能批，没有执行。", failed="没人批准")
        note = await host_mode.remember(ctx.db, grant, req, ctx.conversation_id)
    else:
        await host_mode.used(ctx.db, req.commands)
    await ctx.db.commit()  # 跑命令（可能几分钟）之前放掉写锁
    timeout = max(1, min(int(timeout or 60), settings.host_command_max_seconds))
    title = f"服务器 $ {command[:80]}"
    tail, r = "", None
    try:
        async for ev in host_client.stream(command, timeout):
            if ev.get("type") == "out":
                tail = term_text.tail(tail + str(ev.get("data", "")))
                ctx.live({"type": "code", "language": "bash", "title": title, "source": tail, "live": True})
            elif ev.get("type") == "exit":
                r = ev
    except (httpx.HTTPError, OSError) as e:
        return ToolResult(f"连不上服务器上的主机代理（{type(e).__name__}），命令没有执行。"
                          "请用户在服务器上看 systemctl status assistant-host。", failed="主机代理没响应")
    if r is None:
        return ToolResult("和主机代理的连接中断了，命令的结果不确定。", failed="连接中断")
    timed_out = bool(r.get("timed_out"))
    status = f"超时（{timeout} 秒）被终止" if timed_out else f"退出码 {r.get('exit_code')}"
    out = term_text.clean(str(r.get("output", "")))
    granted = f"（{note}）\n" if note else ""
    return ToolResult(f"{granted}{status}\n{out}", [
        {"type": "code", "language": "bash", "title": title, "source": f"{out.strip() or '（无输出）'}\n# {status}"}],
        failed="" if r.get("exit_code") == 0 and not timed_out else status)
