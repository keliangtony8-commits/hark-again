"""后台任务的查看与取消（启动走 run_command background=true）。规则都在 app/jobs.py。"""
import asyncio
import time

from sqlalchemy import select

from ... import jobs
from ...models import Job
from ..tools import ToolContext, ToolResult, tool


WAIT_MAX = 60
WAIT_STEP = 2


async def _own(ctx: ToolContext, job_id: str) -> Job | None:
    job = await ctx.db.get(Job, job_id.strip())
    return job if job is not None and job.project_id == ctx.workspace else None


@tool("job_status", "正在查看后台任务",
      "查看本工作区后台任务的状态和输出；不给 job_id 就列出最近的任务。给 job_id 时只返回你上次查看之后的新输出"
      "（看过的不再重复；要重看最近一段设 tail=true）。任务结束时你会自动收到通知，不需要轮询；"
      "只有接下来的步骤确实要等它的结果时才用 wait（最多等 60 秒，到点还没完就照常返回）。",
      {"type": "object", "properties": {
          "job_id": {"type": "string"},
          "chars": {"type": "integer", "default": 3000, "maximum": 12000, "description": "最多给多少字符的输出"},
          "wait": {"type": "integer", "default": 0, "maximum": WAIT_MAX, "description": "秒：最多等它结束这么久"},
          "tail": {"type": "boolean", "default": False, "description": "true = 不管看没看过，给最近的一段"}}},)
async def job_status(ctx: ToolContext, job_id: str = "", chars: int = 3000, wait: int = 0, tail: bool = False) -> ToolResult:
    if not job_id:
        rows = (await ctx.db.scalars(select(Job).where(Job.project_id == ctx.workspace)
                                     .order_by(Job.created_at.desc()).limit(10))).all()
        for job in rows:
            await jobs.refresh(ctx.db, job)
        return ToolResult("\n".join(jobs.describe(j) for j in rows) or "这个工作区还没有后台任务。")
    job = await _own(ctx, job_id)
    if job is None:
        return ToolResult("没有这个后台任务（只能看本工作区的）。")
    await jobs.refresh(ctx.db, job)
    deadline = time.monotonic() + max(0, min(int(wait or 0), WAIT_MAX))
    while job.state == "running" and time.monotonic() < deadline:  # 有界等待（参考 deepseek-harness job_output wait）
        await asyncio.sleep(WAIT_STEP)
        await jobs.refresh(ctx.db, job, check_alive=True)
    if job.state != "running" and job.followup in ("pending", "held"):
        job.followup = "seen"  # 你已经看到结论了，结束通知就不再来
    chars = max(200, min(int(chars or 3000), 12000))
    first = not job.read_offset
    if tail:
        out, dropped, label = jobs.log_tail(job, chars), 0, "最近的输出"
        job.read_offset = jobs.log_size(job)
    else:
        out, job.read_offset, dropped = jobs.read_new(job, chars)
        label = "输出" if first else "上次查看之后的新输出"
    if not out and job.state != "running" and first:
        out = job.tail  # 日志文件没了（工作区被清理）：用结算时存下的尾巴
    await ctx.db.commit()  # 游标和 seen 一起提交（SQLite 写锁要在下一次调模型前放掉）
    body = out.rstrip("\n") if out.strip() else ("（还没有输出）" if first else "（没有新输出）")
    more = ""
    if dropped:  # render.ts：被丢掉的部分要说清完整输出在哪
        more = (f"\n（前面还有约 {dropped} 字节没显示。完整日志：{jobs.log_path(job)}，"
                "用 read_file 按 offset 分段读）")
    return ToolResult(f"{jobs.describe(job)}\n命令：{job.command[:300]}\n{label}：\n{body}{more}")


@tool("cancel_job", "正在取消后台任务", "取消本工作区里一个还在运行的后台任务（整组进程杀掉）。",
      {"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]})
async def cancel_job(ctx: ToolContext, job_id: str) -> ToolResult:
    job = await _own(ctx, job_id)
    if job is None:
        return ToolResult("没有这个后台任务（只能取消本工作区的）。")
    try:
        ok = await jobs.cancel(ctx.db, job, by="agent")
    except jobs.JobError as e:
        return ToolResult(str(e))
    if not ok:
        return ToolResult(f"它已经结束了：{jobs.describe(job)}")
    return ToolResult(f"已取消：{jobs.describe(job)}")
