"""工作区工具：读写文件直接在后端做（快、零成本）；执行命令交给隔离沙盒。
每段对话都有工作区（项目 = 项目的，主聊天/定时任务 = 个人的），用 ctx.workspace，规则在 app/workspaces.py。"""
import asyncio

import httpx

from ... import command_guard, deliver, jobs, sandbox_client, spill, vision
from ...config import settings
from ...storage import hidden, looks_text, mime_of, project_dir, safe_join
from ..tools import ToolContext, ToolImage, ToolResult, tool

MAX_READ = 12000
MAX_READ_LIMIT = 20000


def _command_risk(args: dict) -> str | None:
    """需要用户点头的命令弹审批卡；会被直接拦下的（block）不弹卡，run_command 里拒绝。规则全在 command_guard.py。"""
    v = command_guard.verdict(args.get("command", ""))
    return v.why if v is not None and v.level == "ask" else None
_PATH = {"type": "string", "description": "相对工作区根目录的路径"}


@tool("list_files", "正在查看文件", "列出工作区里的文件。",
      {"type": "object", "properties": {"path": {**_PATH, "default": ""}}})
async def list_files(ctx: ToolContext, path: str = "") -> ToolResult:
    root = project_dir(ctx.workspace)
    base = safe_join(root, path)
    if not base.is_dir():
        return ToolResult("目录不存在。")
    items = [p for p in sorted(base.rglob("*")) if not hidden(p.relative_to(root).parts)][:300]
    lines = [f"{p.relative_to(root)}{'/' if p.is_dir() else f'  ({p.stat().st_size} B)'}" for p in items]
    return ToolResult("\n".join(lines) or "（空）")


@tool("read_file", "正在读文件",
      "读取工作区里的文本文件；图片文件（jpg/png/webp/gif）会直接给你看。长文件用 offset / limit 分段读"
      "（也能读被省略的长输出 .spill/… 和后台任务完整日志 .jobs/<id>/log）。",
      {"type": "object", "properties": {
          "path": _PATH,
          "offset": {"type": "integer", "default": 0, "description": "从第几个字符开始（负数 = 从结尾倒数）"},
          "limit": {"type": "integer", "default": MAX_READ, "maximum": MAX_READ_LIMIT, "description": "最多读多少字符"}},
       "required": ["path"]})
async def read_file(ctx: ToolContext, path: str, offset: int = 0, limit: int = MAX_READ) -> ToolResult:
    p = safe_join(project_dir(ctx.workspace), path)
    if not p.is_file():
        return ToolResult("文件不存在。")
    if mime_of(p.name) in vision.IMAGE_MIMES:
        size = p.stat().st_size
        if size > vision.TOOL_IMAGE_MAX_BYTES:
            return ToolResult(f"{path} 是图片，但太大（{size} B），先用 run_command 缩小再看。")
        return ToolResult(f"{path} 是图片（{size} B）。", images=[ToolImage(p.name, p.read_bytes())])
    if not looks_text(p):
        return ToolResult(f"{path} 不是文本文件（{p.stat().st_size} B），可以用 run_command 处理。")
    text = p.read_text(encoding="utf-8", errors="replace")
    return ToolResult(page(text, offset, limit))


def page(text: str, offset: int = 0, limit: int = MAX_READ) -> str:
    """按字符分页：全文放得下原样返回；否则给这一段并说明位置和下一段从哪开始。"""
    total = len(text)
    limit = max(200, min(int(limit or MAX_READ), MAX_READ_LIMIT))
    start = max(0, total + offset if offset < 0 else min(offset, total))
    if start == 0 and total <= limit:
        return text
    end = min(total, start + limit)
    more = f"下一段用 offset={end}" if end < total else "已到结尾"
    return f"{text[start:end]}\n…（第 {start}–{end} 字符，共 {total} 字符；{more}）"


@tool("write_file", "正在写文件", "在工作区里创建或覆盖一个文本文件（用户看不到卡片；要交给用户的用 display_file）。",
      {"type": "object", "properties": {"path": _PATH, "content": {"type": "string"}},
       "required": ["path", "content"]})
async def write_file(ctx: ToolContext, path: str, content: str) -> ToolResult:
    p = safe_join(project_dir(ctx.workspace), path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return ToolResult(f"已写入 {path}（{len(content)} 字符）。")


@tool("display_file", "正在把文件交给你",
      "把工作区里的文件交给用户：聊天里出现文件卡（图片直接显示），用户能打开/下载。用于交付成果——"
      "命令生成的图表、PDF、表格、压缩包、报告、写好的文档；传目录会自动打包成 zip。"
      "交付的是此刻的快照，之后改文件不影响已交付的卡片。中间产物、脚本、日志不要交付（除非用户要）。"
      "交付后在回复里一句话说清是什么，不要再贴文件内容。",
      {"type": "object", "properties": {
          "paths": {"type": "array", "items": _PATH, "minItems": 1, "maxItems": deliver.MAX_FILES,
                    "description": "要交付的文件或目录，按想让用户看到的顺序"}},
       "required": ["paths"]})
async def display_file(ctx: ToolContext, paths: list[str]) -> ToolResult:
    blocks, notes = [], []
    for path in list(dict.fromkeys(paths))[:deliver.MAX_FILES]:
        try:
            d = await asyncio.to_thread(deliver.deliver, ctx.workspace, path)
        except deliver.DeliverError as e:
            notes.append(f"没有交付 {path}：{e}")
            continue
        blocks.append(d.block)
        notes.append(d.note)
    return ToolResult("\n".join(notes), blocks)


@tool("run_command", "正在运行命令",
      "在工作区的隔离 Linux 沙盒里执行 shell 命令（工作目录就是工作区根目录，有 python3、node、git）。"
      "用于运行代码、测试、安装依赖、git 操作。前台单次最长 120 秒。"
      "预计超过一分钟的活（装大依赖、训练、批量下载/爬取、大构建、长时间脚本）用 background=true 放到后台："
      "立即返回任务 id，用户在聊天里看到实时日志、可以取消；结束时你会收到通知并在这段对话里接着说，"
      "期间不要反复用 job_status 轮询。后台任务连续 idle_timeout 秒没有任何输出会被判定卡住自动停掉。"
      "毁系统的命令（rm -rf /、格式化、关机等）会被直接拦下。",
      {"type": "object", "properties": {
          "command": {"type": "string"},
          "timeout": {"type": "integer", "default": 60,
                      "description": "秒。前台最多 120；后台最多 3600（默认 3600）"},
          "background": {"type": "boolean", "default": False, "description": "放到后台跑"},
          "title": {"type": "string", "description": "后台任务给用户看的一句话名字，如“安装依赖”“训练模型”"},
          "idle_timeout": {"type": "integer",
                           "description": f"秒，仅后台：连续这么久没有新输出就判定卡住并停掉；默认 {settings.job_idle_seconds}，"
                                          "确实会长时间不打印（不输出进度的训练、静默编译）就设 0"}},
       "required": ["command"]}, risk=_command_risk)
async def run_command(ctx: ToolContext, command: str, timeout: int | None = None, background: bool = False,
                      title: str | None = None, idle_timeout: int | None = None) -> ToolResult:
    if (v := command_guard.verdict(command)) is not None and v.level == "block":
        return ToolResult(command_guard.refusal(v))
    if background:
        try:
            job = await jobs.start(ctx.db, project_id=ctx.workspace, command=command, title=title, timeout=timeout,
                                   idle_timeout=idle_timeout, conversation_id=ctx.conversation_id, task_id=ctx.task_id)
        except jobs.JobError as e:
            return ToolResult(f"没有启动：{e}")
        idle = f"，{jobs.duration_text(job.idle_timeout)}无输出算卡住" if job.idle_timeout else ""
        return ToolResult(f"已在后台启动任务 {job.id}「{job.title}」（最长 {jobs.duration_text(job.timeout)}{idle}）。"
                          "用户能在聊天里看到实时日志并取消；结束时你会收到通知，现在先简短告诉用户在跑什么、大概要多久。",
                          [jobs.block(job)])
    try:
        r = await sandbox_client.run(ctx.workspace, command, min(timeout or 60, 120))
    except httpx.HTTPError as e:
        return ToolResult(f"沙盒没响应（{type(e).__name__}），命令没有执行。")
    timed_out = r.get("timed_out")
    status = "超时被终止" if timed_out else f"退出码 {r['exit_code']}"
    out = shown = r.get("output", "")
    if spill.MARK in out:  # 沙盒那边输出太长：中间段省略，完整输出（能存下时）写进了工作区 .spill/
        omitted = r.get("omitted", 0)
        out = out.replace(spill.MARK, spill.notice(omitted, r.get("spill"), r.get("total", 0)))
        shown = shown.replace(spill.MARK, f"\n…（中间省略 {omitted} 字符）…\n")
    hint = "\n（前台最多 120 秒；这种长活用 background=true 放到后台重跑）" if timed_out else ""
    return ToolResult(f"{status}\n{out}{hint}", [
        {"type": "code", "language": "bash", "title": f"$ {command[:80]}", "source": f"{shown.strip() or '（无输出）'}\n# {status}"}])
