"""工作区工具：读写文件直接在后端做（快、零成本）；执行命令交给隔离沙盒。
每段对话都有工作区（项目 = 项目的，主聊天/定时任务 = 个人的），用 ctx.workspace，规则在 app/workspaces.py。"""
import asyncio

import httpx

from ... import apply_patch as patching, command_guard, computer, deliver, file_edit, file_seen, jobs, quota, sandbox_client, spill, term_text, vision, workspace_search, workspaces
from ...config import settings
from ...storage import hidden, looks_text, mime_of, project_dir, safe_join
from ..tools import ToolContext, ToolImage, ToolResult, tool

MAX_READ = 12000
MAX_READ_LIMIT = 20000


def _command_risk(args: dict, ctx=None) -> str | None:
    """需要用户点头的命令弹审批卡；会被直接拦下的（block）不弹卡，run_command 里拒绝。规则全在 command_guard.py。"""
    v = command_guard.verdict(args.get("command", ""))
    return v.why if v is not None and v.level == "ask" else None
_PATH = {"type": "string", "description": "相对工作区根目录的路径"}


@tool("list_files", "正在查看文件", "列出工作区里的文件（最多 300 项）。按名字找文件用 glob，按内容找用 grep。",
      {"type": "object", "properties": {"path": {**_PATH, "default": ""}}}, parallel=True)
async def list_files(ctx: ToolContext, path: str = "") -> ToolResult:
    root = project_dir(ctx.workspace)
    base = safe_join(root, path)
    if not base.is_dir():
        return ToolResult("目录不存在。")
    items = [p for p in sorted(base.rglob("*")) if not hidden(p.relative_to(root).parts)][:300]
    lines = [f"{p.relative_to(root)}{'/' if p.is_dir() else f'  ({p.stat().st_size} B)'}" for p in items]
    return _with_rules(ctx, base, ToolResult("\n".join(lines) or "（空）"), is_dir=True)


@tool("glob", "正在找文件",
      "按文件名模式在工作区里找文件，新改的排前面，带大小和修改时间。"
      "*.py 匹配任意深度的文件名；带 / 的按路径匹配，如 src/**/*.ts、docs/*.md；{a,b} 二选一。"
      "隐藏目录（.git/.jobs/.spill/.home）和 node_modules 这类依赖目录默认不搜，path 明确指进去才搜。"
      "超过 100 个时按顶层目录轮流抽样列出，完整结果落盘可 read_file。"
      "找文件别用 run_command find/ls -R。",
      {"type": "object", "properties": {
          "pattern": {"type": "string", "description": "文件名模式，如 **/*.py、report*.pdf"},
          "path": {**_PATH, "default": "", "description": "从哪个目录开始找（默认工作区根）"}},
       "required": ["pattern"]}, parallel=True)
async def glob(ctx: ToolContext, pattern: str, path: str = "") -> ToolResult:
    try:
        return ToolResult(await asyncio.to_thread(workspace_search.glob, ctx.workspace, pattern, path))
    except workspace_search.SearchError as e:
        return ToolResult(str(e), failed=e.short)


@tool("grep", "正在搜索内容",
      "按正则在工作区文件内容里搜，结果按文件分组、带行号（路径:行号），之后用 read_file 看上下文或 edit_file 修改。"
      "找代码定义/调用、配置项、日志里的报错都用它，别用 run_command grep。"
      "include 限定文件（一个 glob，如 *.py 或 *.{ts,tsx}）；只按字面找设 fixed=true；context 给命中前后几行。"
      "二进制文件、超过 5 MB 的文件、隐藏目录和依赖目录默认跳过（path 明确指进去就搜，比如 .jobs/<id>/log）。",
      {"type": "object", "properties": {
          "pattern": {"type": "string", "description": "正则（Python 语法），如 def \\w+_user、TODO|FIXME"},
          "path": {**_PATH, "default": "", "description": "目录或单个文件（默认整个工作区）"},
          "include": {"type": "string", "default": "", "description": "只搜文件名匹配这个 glob 的文件"},
          "ignore_case": {"type": "boolean", "default": False},
          "fixed": {"type": "boolean", "default": False, "description": "pattern 当普通文字，不当正则"},
          "context": {"type": "integer", "default": 0, "maximum": workspace_search.CONTEXT_MAX,
                      "description": "每处命中前后各带几行"}},
       "required": ["pattern"]}, parallel=True)
async def grep(ctx: ToolContext, pattern: str, path: str = "", include: str = "", ignore_case: bool = False,
               fixed: bool = False, context: int = 0) -> ToolResult:
    try:
        text = await asyncio.to_thread(workspace_search.grep, ctx.workspace, pattern, path, include,
                                       ignore_case, fixed, context)
    except workspace_search.SearchError as e:
        return ToolResult(str(e), failed=e.short)
    return ToolResult(text)


@tool("read_file", "正在读文件",
      "读取工作区里的文本文件；图片文件（jpg/png/webp/gif）会直接给你看。长文件用 offset / limit 分段读"
      "（也能读被省略的长输出 .spill/… 和后台任务完整日志 .jobs/<id>/log）。",
      {"type": "object", "properties": {
          "path": _PATH,
          "offset": {"type": "integer", "default": 0, "description": "从第几个字符开始（负数 = 从结尾倒数）"},
          "limit": {"type": "integer", "default": MAX_READ, "maximum": MAX_READ_LIMIT, "description": "最多读多少字符"}},
       "required": ["path"]}, parallel=True)
async def read_file(ctx: ToolContext, path: str, offset: int = 0, limit: int = MAX_READ) -> ToolResult:
    p = safe_join(project_dir(ctx.workspace), path)
    return _with_rules(ctx, p, _read_file(ctx, p, path, offset, limit))


def _read_file(ctx: ToolContext, p, path: str, offset: int, limit: int) -> ToolResult:
    file_seen.observe(_owner(ctx), p)  # 看过（哪怕只读一段 / 不存在）：之后 write_file 才许覆盖，规则在 file_seen.py
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


@tool("write_file", "正在写文件",
      "在工作区里创建或整篇覆盖一个文本文件（用户看不到卡片；要交给用户的用 display_file）。"
      "覆盖已存在的文件前要先在这段对话里 read_file 过它（读开头一段也行），读过之后被改过也要重读。"
      "改已有文件的一小段用 edit_file，不要整篇重写。",
      {"type": "object", "properties": {"path": _PATH, "content": {"type": "string"}},
       "required": ["path", "content"]})
async def write_file(ctx: ToolContext, path: str, content: str) -> ToolResult:
    p = safe_join(project_dir(ctx.workspace), path)
    try:
        file_seen.check_write(_owner(ctx), p, path)
    except file_seen.Refused as e:
        return ToolResult(str(e), failed=e.short)
    before = _old_text(p)
    grow = len(content.encode()) - (p.stat().st_size if p.is_file() else 0)
    if (full := await _quota_refusal(ctx, path, grow)) is not None:
        return full
    ctx.changes.before(project_dir(ctx.workspace), p)  # 这一轮第一次碰：记基线（整轮撤销，turn_changes.py）
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    file_seen.observe(_owner(ctx), p)
    quota.forget(ctx.workspace)
    c = file_edit.change(path, before, content)
    verb = "新建" if before is None else "覆盖原文件"
    return _with_rules(ctx, p, ToolResult(f"已写入 {path}（{verb}，{len(content)} 字符，{file_edit.stat(c)}）。", change=c))


@tool("edit_file", "正在改文件",
      "精确修改工作区里已有的文本文件：把 old_string 换成 new_string，其余内容原样不动。"
      "old_string 要和文件里一字不差（含缩进），并且只出现一处——不唯一时多带几行上下文；"
      "要把所有出现都换掉设 replace_all=true。删一段就让 new_string 为空。新建文件或整篇重写用 write_file。"
      "改之前先 read_file 看准原文。",
      {"type": "object", "properties": {
          "path": _PATH,
          "old_string": {"type": "string", "description": "要替换的原文，一字不差"},
          "new_string": {"type": "string", "description": "替换成的内容"},
          "replace_all": {"type": "boolean", "default": False, "description": "替换所有出现（默认只允许唯一一处）"}},
       "required": ["path", "old_string", "new_string"]})
async def edit_file(ctx: ToolContext, path: str, old_string: str, new_string: str = "",
                    replace_all: bool = False) -> ToolResult:
    p = safe_join(project_dir(ctx.workspace), path)
    if not p.is_file():
        return ToolResult(f"{path} 不存在：新建文件用 write_file。", failed="文件不存在")
    try:
        file_seen.check_edit(_owner(ctx), p, path)
    except file_seen.Refused as e:
        return ToolResult(str(e), failed=e.short)
    if not looks_text(p):
        return ToolResult(f"{path} 不是文本文件，不能按文字替换；可以用 run_command 处理。", failed="不是文本文件")
    raw = p.read_bytes()
    try:
        before = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ToolResult(f"{path} 不是 UTF-8 编码，没有改（免得写坏）；可以用 run_command 处理。", failed="不是 UTF-8 文本")
    try:
        e = file_edit.apply(before, old_string, new_string, replace_all)
    except file_edit.EditError as err:
        return ToolResult(f"没有修改 {path}：{err}", failed=err.short)
    if (full := await _quota_refusal(ctx, path, len(e.text.encode()) - len(raw))) is not None:
        return full
    ctx.changes.before(project_dir(ctx.workspace), p)
    p.write_bytes(e.text.encode("utf-8"))  # 不经 write_text：保住文件原来的 \r\n
    file_seen.observe(_owner(ctx), p)
    quota.forget(ctx.workspace)
    c = file_edit.change(path, before, e.text)
    how = "（原文的空白/缩进或标点和文件里略有不同，已按文件里的缩进替换）" if e.loose else ""
    return _with_rules(ctx, p, ToolResult(f"已修改 {path}：替换了 {e.count} 处，{file_edit.stat(c)}{how}。", change=c))


PATCH_GRAMMAR = (
    "*** Begin Patch\n"
    "*** Add File: 路径          ← 新建（已有就整篇覆盖），之后每一行都以 + 开头\n"
    "*** Delete File: 路径       ← 删除，后面什么都不跟\n"
    "*** Update File: 路径       ← 修改；要改名就紧跟一行 *** Move to: 新路径\n"
    "@@ 定位行（可选：类名/函数名那一行，帮着找准位置；只有 @@ 也行）\n"
    " 上下文行（空格开头，照抄文件里的原文，改动前后各 3 行左右）\n"
    "-删掉的行\n"
    "+加上的行\n"
    "*** End of File             ← 可选：这一处必须在文件结尾\n"
    "*** End Patch")


@tool("apply_patch", "正在改文件",
      "用一份补丁一次改工作区里的多个文本文件：新建、修改（多处）、删除、改名都可以，整份要么全部生效、要么一个都不动。"
      "动多个文件或一个文件的多处时用它；只换一小段用 edit_file 也行。格式（Codex apply_patch）：\n" + PATCH_GRAMMAR + "\n"
      "要点：每一段都要有段头；新建文件的内容行也要以 + 开头；路径相对工作区根目录；"
      "同一文件的多处改动按文件里的先后顺序写，每处用 @@ 隔开；上下文和 - 行必须和文件一致，先 read_file 看准。"
      "覆盖或改名到已有文件前要先 read_file 过它。",
      {"type": "object", "properties": {
          "patch": {"type": "string", "description": "整份补丁，从 *** Begin Patch 到 *** End Patch"}},
       "required": ["patch"]})
async def apply_patch(ctx: ToolContext, patch: str) -> ToolResult:
    return await _apply_patch(ctx, patch)


async def _apply_patch(ctx: ToolContext, patch: str, sub: str = "") -> ToolResult:
    """apply_patch 工具和 run_command 里的 `apply_patch <<'EOF'` 共用。规则在 app/apply_patch.py；这里接工作区的护栏。"""
    root = project_dir(ctx.workspace)
    try:
        base = safe_join(root, sub) if sub else root
        if not base.is_dir():
            raise patching.PatchError(f"目录 {sub} 不存在。", "目录不存在")
        hunks = patching.parse(patch)
        if base != root.resolve():  # cd 子目录 && apply_patch：段里的路径相对那个子目录
            pre = base.relative_to(root.resolve()).as_posix()
            for h in hunks:
                h.path = f"{pre}/{h.path.lstrip('/')}"
                h.move_to = f"{pre}/{h.move_to.lstrip('/')}" if h.move_to else h.move_to
        plan = await asyncio.to_thread(patching.plan, root, hunks)
    except ValueError:
        return ToolResult(f"目录 {sub} 在工作区外面。", failed="路径越界")
    except patching.PatchError as e:
        return ToolResult(f"补丁没有应用，什么都没改：{e}", failed=e.short)
    changed = [e for e in plan.entries if e.changed]
    if not changed:
        return ToolResult("补丁应用后内容和原来完全一样，什么都没改。")
    owner = _owner(ctx)
    try:
        for e in changed:
            if e.disk is None:
                continue
            if e.whole:
                file_seen.check_write(owner, e.p, e.rel)
            else:
                file_seen.check_edit(owner, e.p, e.rel)
    except file_seen.Refused as err:
        return ToolResult(f"补丁没有应用，什么都没改：{err}", failed=err.short)
    if (full := await _quota_refusal(ctx, "这些文件", plan.growth)) is not None:
        return full
    for e in changed:
        ctx.changes.before(root, e.p)  # 整轮撤销的基线（turn_changes.py）
    try:
        await asyncio.to_thread(patching.commit, plan)
    except patching.PatchError as e:
        return ToolResult(str(e), failed=e.short)
    for e in changed:
        file_seen.observe(owner, e.p)
    quota.forget(ctx.workspace)
    cards = [_patch_change(e) for e in changed if not e.moved_away]
    stats = "；".join(f"{c['path']} {file_edit.stat(c)}" for c in cards)
    r = ToolResult(f"已应用补丁（{plan.hunks} 段）：{patching.summary(changed)}。{stats}。", change=cards)
    for e in changed:
        if e.after is not None:
            r = _with_rules(ctx, e.p, r)
    return r


def _patch_change(e) -> dict:
    """时间线上每个文件一份改动摘要：改名的按原文件算 diff 并注明从哪来；删掉的 = 整篇删除。"""
    c = file_edit.change(e.rel, e.before_text, e.after if e.after is not None else "")
    if e.after is None:
        c.pop("created", None)
        c["deleted"] = True
    if e.origin is not None:
        c.pop("created", None)
        c["moved_from"] = e.origin.rel
    return c


def _with_rules(ctx: ToolContext, p, r: ToolResult, is_dir: bool = False) -> ToolResult:
    """碰到子目录里的文件：把根到那里之间新出现 / 改过 / 删掉的 AGENTS.md 一类规则追加给模型（这一轮只说一次）。
    规则在 app/workspace_instructions.py（移植自 deepseek-harness agent-instructions，思路同 Gemini CLI 的 JIT context）。"""
    if note := ctx.instructions.note(ctx.workspace, p, is_dir):
        r.content = f"{r.content}\n\n{note}"
    return r


def _owner(ctx: ToolContext) -> str | None:
    return file_seen.owner_of(ctx.conversation_id, ctx.task_id)


def _old_text(p) -> str | None:
    """覆盖前的旧内容（拿来算 diff）；不存在 → None（新建）；二进制/读不了 → 空串（diff 只算新增）。"""
    if not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8") if looks_text(p) else ""
    except (UnicodeDecodeError, OSError):
        return ""


async def _quota_refusal(ctx: ToolContext, path: str, grow: int) -> ToolResult | None:
    if grow <= 0:
        return None  # 变小或不变：磁盘满了也允许（清理正是要这样做）
    try:
        await asyncio.to_thread(quota.check, ctx.workspace, grow)
    except quota.QuotaError as e:
        return ToolResult(f"没有写入 {path}：{e}", failed="工作区磁盘满了")
    return None


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
      "在工作区的隔离 Linux 沙盒里执行 shell 命令（工作目录就是工作区根目录，非 root，有 python3、node、git）。"
      "用于运行代码、测试、安装依赖、git 操作；pip install / npm i -g 装的东西留在工作区，下次不用重装。前台单次最长 120 秒。"
      "预计超过一分钟的活（装大依赖、训练、批量下载/爬取、大构建、长时间脚本）用 background=true 放到后台："
      "立即返回任务 id，用户在聊天里看到实时日志、可以取消；结束时你会收到通知并在这段对话里接着说，"
      "期间不要反复用 job_status 轮询。后台任务连续 idle_timeout 秒没有任何输出会被判定卡住自动停掉。"
      "前台命令运行中用户能实时看到输出。标准输入默认是空的（交互提示读到 EOF，不会卡住）；"
      "需要喂输入时（确认提示的回答、要处理的数据）用 stdin 传。"
      "毁系统的命令（rm -rf /、格式化、关机等）会被直接拦下。"
      "工作区磁盘有上限（含装的软件和日志），满了写不进新文件、后台任务会被停，结果里会提醒你。",
      {"type": "object", "properties": {
          "command": {"type": "string"},
          "timeout": {"type": "integer", "default": 60,
                      "description": "秒。前台最多 120；后台最多 3600（默认 3600）"},
          "background": {"type": "boolean", "default": False, "description": "放到后台跑"},
          "stdin": {"type": "string", "description": f"仅前台：传给命令标准输入的文本，最多 {sandbox_client.STDIN_MAX // 1024} KB"},
          "title": {"type": "string", "description": "后台任务给用户看的一句话名字，如“安装依赖”“训练模型”"},
          "idle_timeout": {"type": "integer",
                           "description": f"秒，仅后台：连续这么久没有新输出就判定卡住并停掉；默认 {settings.job_idle_seconds}，"
                                          "确实会长时间不打印（不输出进度的训练、静默编译）就设 0"}},
       "required": ["command"]}, risk=_command_risk)
async def run_command(ctx: ToolContext, command: str, timeout: int | None = None, background: bool = False,
                      title: str | None = None, idle_timeout: int | None = None, stdin: str | None = None) -> ToolResult:
    if (heredoc := patching.from_command(command)) is not None and not background:
        # Codex 的模型习惯在 shell 里写 apply_patch <<'EOF'：沙盒里没有这个命令，整条就是它时直接按补丁改（同 Codex invocation.rs）
        return await _apply_patch(ctx, *heredoc)
    if (v := command_guard.verdict(command)) is not None and v.level == "block":
        return ToolResult(command_guard.refusal(v), failed="危险命令，已拦下")
    if v is not None and v.level == "unsupported":
        return ToolResult(command_guard.unsupported(v, workspaces.ENVIRONMENT), failed="沙盒里没有这个权限")
    if background:
        if stdin is not None:
            return ToolResult("后台任务不接受 stdin：把输入写进工作区文件，命令里用 < 文件 读。")
        try:
            job = await jobs.start(ctx.db, project_id=ctx.workspace, command=command, title=title, timeout=timeout,
                                   idle_timeout=idle_timeout, conversation_id=ctx.conversation_id, task_id=ctx.task_id)
        except jobs.JobError as e:
            return ToolResult(f"没有启动：{e}", failed=f"没有启动：{e}")
        idle = f"，{jobs.duration_text(job.idle_timeout)}无输出算卡住" if job.idle_timeout else ""
        return ToolResult(f"已在后台启动任务 {job.id}「{job.title}」（最长 {jobs.duration_text(job.timeout)}{idle}）。"
                          "用户能在聊天里看到实时日志并取消；结束时你会收到通知，现在先简短告诉用户在跑什么、大概要多久。",
                          [jobs.block(job)])
    if stdin is not None and len(stdin.encode()) > sandbox_client.STDIN_MAX:
        return ToolResult(f"stdin 太长（上限 {sandbox_client.STDIN_MAX // 1024} KB）：先写进工作区文件，命令里用 < 文件 读。")
    title = f"$ {command[:80]}"
    tail, r = "", None
    try:
        async for ev in sandbox_client.stream(ctx.workspace, command, min(timeout or 60, 120), stdin):
            if ev["type"] == "out":
                tail = term_text.tail(tail + ev["data"])
                ctx.live({"type": "code", "language": "bash", "title": title, "source": tail, "live": True})
            elif ev["type"] == "exit":
                r = ev
            elif ev["type"] == "error":
                return ToolResult(f"沙盒出错（{ev.get('error', '')}），命令的结果不确定。", failed="沙盒出错")
    except httpx.HTTPError as e:
        return ToolResult(f"沙盒没响应（{type(e).__name__}），命令没有执行。", failed="沙盒没响应")
    if r is None:
        return ToolResult("沙盒连接中断，命令的结果不确定。", failed="沙盒连接中断")
    timed_out = r.get("timed_out")
    status = "超时被终止" if timed_out else f"退出码 {r['exit_code']}"
    if r.get("oom"):  # 沙盒比过 cgroup 的 OOM 计数：确实是内存超上限被内核杀的
        status = f"{jobs.OOM_REASON}（退出码 {r['exit_code']}）"
    # 终端文本统一洗一遍（颜色转义、\r 进度帧）；二进制输出沙盒已换成一句说明
    out = shown = term_text.clean(r.get("output", ""))
    if r.get("binary") is not None:
        out, shown = term_text.binary_note(r["binary"]), f"（二进制输出，{r['binary']} 字节，不显示）"
    if spill.MARK in out:  # 沙盒那边输出太长：中间段省略，完整输出（能存下时）写进了工作区 .spill/
        omitted = r.get("omitted", 0)
        note = spill.notice(omitted, r.get("spill"), r.get("total", 0))
        if r.get("spill_truncated"):  # 沙盒只存了前 64 MB
            note += "（完整输出太大，文件里只存了开头一部分）"
        out = out.replace(spill.MARK, note)
        shown = shown.replace(spill.MARK, f"\n…（中间省略 {omitted} 字符）…\n")
    hint = "\n（前台最多 120 秒；这种长活用 background=true 放到后台重跑）" if timed_out else ""
    if r.get("oom"):
        hint = f"\n（{jobs.oom_hint(r.get('memory_limit'))}）"
    hint += computer.wake_note(r.get("woke"))
    # 命令可能刚写了大东西：重数一遍（线程里跑，最多数 20 万项），满了 / 快满了才有一句
    hint += await asyncio.to_thread(quota.model_note, ctx.workspace, True)
    return ToolResult(f"{status}\n{out}{hint}", [
        {"type": "code", "language": "bash", "title": title, "source": f"{shown.strip() or '（无输出）'}\n# {status}"}],
        failed="" if r.get("exit_code") == 0 and not timed_out else status)

