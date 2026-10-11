"""项目工作区：读写文件直接在后端做（快、零成本）；执行命令交给隔离沙盒。只在项目对话中可用。"""
from ... import sandbox_client
from ...storage import is_text, project_dir, safe_join
from ..tools import ToolContext, ToolResult, tool

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
    items = sorted(base.rglob("*"))[:300]
    lines = [f"{p.relative_to(root)}{'/' if p.is_dir() else f'  ({p.stat().st_size} B)'}"
             for p in items if ".git" not in p.parts]
    return ToolResult("\n".join(lines) or "（空）")


@tool("read_file", "正在读文件", "读取项目里的文本文件。",
      {"type": "object", "properties": {"path": _PATH}, "required": ["path"]}, scope="project")
async def read_file(ctx: ToolContext, path: str) -> ToolResult:
    p = safe_join(project_dir(ctx.project_id), path)
    if not p.is_file():
        return ToolResult("文件不存在。")
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
      "用于运行代码、测试、安装依赖、git 操作。单次最长 120 秒。",
      {"type": "object", "properties": {"command": {"type": "string"},
                                        "timeout": {"type": "integer", "default": 60, "maximum": 120}},
       "required": ["command"]}, scope="project", risk=_command_risk)
async def run_command(ctx: ToolContext, command: str, timeout: int = 60) -> ToolResult:
    r = await sandbox_client.run(ctx.project_id, command, min(timeout, 120))
    status = "超时被终止" if r.get("timed_out") else f"退出码 {r['exit_code']}"
    out = r.get("output", "")
    return ToolResult(f"{status}\n{out}", [
        {"type": "code", "language": "bash", "title": f"$ {command[:80]}", "source": f"{out.strip() or '（无输出）'}\n# {status}"}])
