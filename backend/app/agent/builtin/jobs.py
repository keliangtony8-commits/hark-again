"""后台任务的查看与取消（启动走 run_command background=true）。规则都在 app/jobs.py。"""
from sqlalchemy import select

from ... import jobs
from ...models import Job
from ..tools import ToolContext, ToolResult, tool


async def _own(ctx: ToolContext, job_id: str) -> Job | None:
    job = await ctx.db.get(Job, job_id.strip())
    return job if job is not None and job.project_id == ctx.project_id else None


@tool("job_status", "正在查看后台任务",
      "查看本项目后台任务的状态和最近的输出；不给 job_id 就列出最近的任务。任务结束时你会自动收到通知，不需要轮询。",
      {"type": "object", "properties": {
          "job_id": {"type": "string"},
          "chars": {"type": "integer", "default": 3000, "maximum": 12000, "description": "要看的日志尾巴长度（字符）"}}},
      scope="project")
async def job_status(ctx: ToolContext, job_id: str = "", chars: int = 3000) -> ToolResult:
    if not job_id:
        rows = (await ctx.db.scalars(select(Job).where(Job.project_id == ctx.project_id)
                                     .order_by(Job.created_at.desc()).limit(10))).all()
        for job in rows:
            await jobs.refresh(ctx.db, job)
        return ToolResult("\n".join(jobs.describe(j) for j in rows) or "这个项目还没有后台任务。")
    job = await _own(ctx, job_id)
    if job is None:
        return ToolResult("没有这个后台任务（只能看本项目的）。")
    await jobs.refresh(ctx.db, job)
    if job.state != "running" and job.followup == "pending":
        job.followup = "seen"  # 你已经看到结论了，结束通知就不再来
        await ctx.db.commit()
    tail = jobs.log_tail(job, max(200, min(chars, 12000))) or job.tail or "（还没有输出）"
    return ToolResult(f"{jobs.describe(job)}\n命令：{job.command[:300]}\n最近的输出：\n{tail}")


@tool("cancel_job", "正在取消后台任务", "取消本项目里一个还在运行的后台任务（整组进程杀掉）。",
      {"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]}, scope="project")
async def cancel_job(ctx: ToolContext, job_id: str) -> ToolResult:
    job = await _own(ctx, job_id)
    if job is None:
        return ToolResult("没有这个后台任务（只能取消本项目的）。")
    try:
        ok = await jobs.cancel(ctx.db, job, by="agent")
    except jobs.JobError as e:
        return ToolResult(str(e))
    if not ok:
        return ToolResult(f"它已经结束了：{jobs.describe(job)}")
    return ToolResult(f"已取消：{jobs.describe(job)}")
