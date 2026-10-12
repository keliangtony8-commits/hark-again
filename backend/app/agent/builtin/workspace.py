"""项目工作区：读写文件直接在后端做（快、零成本）；执行命令交给隔离沙盒。只在项目对话中可用。"""
import httpx

from ... import jobs, sandbox_client, vision
from ...storage import hidden, is_text, mime_of, project_dir, safe_join
from ..tools import ToolContext, ToolImage, ToolResult, tool

import re

MAX_READ = 12000

# 需要你点头才执行的命令：会改动远端、发布或大面积删除
RISKY = [
    (r"\bgit\s+push\b", "推送代码到远端仓库"),
    (r"\bgit\s+commit\b", "提交代码"),
    (r"\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r", "递归强制删除文件"),
    (r"\b(npm|pnpm|yarn)\s+publish\b|\btwine\s+upload\b", "发布软件包"),
    (r"(curl|wget)[^|]*\|\s*(ba)?sh", "下载并直接执行脚本"),
]


def _command_risk(args: dict) -> str | None:
    cmd = args.get("command", "")
    return next((why for pat, why in RISKY if re.search(pat, cmd)), None)
_PATH = {"type": "string", "description": "相对项目根目录的路径"}


@tool("list_files", "正在查看文件", "列出项目工作区里的文件。",
      {"type": "object", "properties": {"path": {**_PATH, "default": ""}}}, scope="project")
async def list_files(ctx: ToolContext, path: str = "") -> ToolResult:
    root = project_dir(ctx.project_id)
    base = safe_join(root, path)
    if not base.is_dir():
        return ToolResult("目录不存在。")
    items = [p for p in sorted(base.rglob("*")) if not hidden(p.relative_to(root).parts)][:300]
    lines = [f"{p.relative_to(root)}{'/' if p.is_dir() else f'  ({p.stat().st_size} B)'}" for p in items]
    return ToolResult("\n".join(lines) or "（空）")


@tool("read_file", "正在读文件", "读取项目里的文本文件；图片文件（jpg/png/webp/gif）会直接给你看。",
      {"type": "object", "properties": {"path": _PATH}, "required": ["path"]}, scope="project")
async def read_file(ctx: ToolContext, path: str) -> ToolResult:
    p = safe_join(project_dir(ctx.project_id), path)
    if not p.is_file():
        return ToolResult("文件不存在。")
    if mime_of(p.name) in vision.IMAGE_MIMES:
        size = p.stat().st_size
        if size > vision.TOOL_IMAGE_MAX_BYTES:
            return ToolResult(f"{path} 是图片，但太大（{size} B），先用 run_command 缩小再看。")
        return ToolResult(f"{path} 是图片（{size} B）。", images=[ToolImage(p.name, p.read_bytes())])
    if not is_text(p.name):
        return ToolResult(f"{path} 不是文本文件（{p.stat().st_size} B），可以用 run_command 处理。")
    text = p.read_text(encoding="utf-8", errors="replace")
    return ToolResult(text[:MAX_READ] + ("\n…（已截断）" if len(text) > MAX_READ else ""))


@tool("write_file", "正在写文件", "在项目里创建或覆盖一个文本文件。",
      {"type": "object", "properties": {"path": _PATH, "content": {"type": "string"}},
       "required": ["path", "content"]}, scope="project")
async def write_file(ctx: ToolContext, path: str, content: str) -> ToolResult:
    p = safe_join(project_dir(ctx.project_id), path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return ToolResult(f"已写入 {path}（{len(content)} 字符）。", [
        {"type": "file", "source": "project", "id": path, "name": p.name, "mime": "text/plain",
         "size": p.stat().st_size, "project_id": ctx.project_id}])


@tool("run_command", "正在运行命令",
      "在项目的隔离 Linux 沙盒里执行 shell 命令（工作目录就是项目根目录，有 python3、node、git）。"
      "用于运行代码、测试、安装依赖、git 操作。前台单次最长 120 秒。"
      "预计超过一分钟的活（装大依赖、训练、批量下载/爬取、大构建、长时间脚本）用 background=true 放到后台："
      "立即返回任务 id，用户在聊天里看到实时日志、可以取消；结束时你会收到通知并在这段对话里接着说，"
      "期间不要反复用 job_status 轮询。",
      {"type": "object", "properties": {
          "command": {"type": "string"},
          "timeout": {"type": "integer", "default": 60,
                      "description": "秒。前台最多 120；后台最多 3600（默认 3600）"},
          "background": {"type": "boolean", "default": False, "description": "放到后台跑"},
          "title": {"type": "string", "description": "后台任务给用户看的一句话名字，如“安装依赖”“训练模型”"}},
       "required": ["command"]}, scope="project", risk=_command_risk)
async def run_command(ctx: ToolContext, command: str, timeout: int | None = None, background: bool = False,
                      title: str | None = None) -> ToolResult:
    if background:
        try:
            job = await jobs.start(ctx.db, project_id=ctx.project_id, command=command, title=title, timeout=timeout,
                                   conversation_id=ctx.conversation_id, task_id=ctx.task_id)
        except jobs.JobError as e:
            return ToolResult(f"没有启动：{e}")
        return ToolResult(f"已在后台启动任务 {job.id}「{job.title}」（最长 {jobs.duration_text(job.timeout)}）。"
                          "用户能在聊天里看到实时日志并取消；结束时你会收到通知，现在先简短告诉用户在跑什么、大概要多久。",
                          [jobs.block(job)])
    try:
        r = await sandbox_client.run(ctx.project_id, command, min(timeout or 60, 120))
    except httpx.HTTPError as e:
        return ToolResult(f"沙盒没响应（{type(e).__name__}），命令没有执行。")
    timed_out = r.get("timed_out")
    status = "超时被终止" if timed_out else f"退出码 {r['exit_code']}"
    out = r.get("output", "")
    hint = "\n（前台最多 120 秒；这种长活用 background=true 放到后台重跑）" if timed_out else ""
    return ToolResult(f"{status}\n{out}{hint}", [
        {"type": "code", "language": "bash", "title": f"$ {command[:80]}", "source": f"{out.strip() or '（无输出）'}\n# {status}"}])
