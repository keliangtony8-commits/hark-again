"""v2.18 CORE 32：后台任务改了哪些工作区文件 → 任务卡上的改动区 + 一键撤销。唯一规则在这里。

对标：Hark 的改动卡 / 撤销覆盖助手的所有改动；v2.14 只盯一轮里的前台命令，后台任务（跑几小时的构建、爬虫、
数据处理）改的文件没人记，用户只能在磁盘账（job_disk）里看到“写了 N 个文件”，看不到改了什么、退不回去。
三家参考都在用户本机跑、没有服务端后台任务（Codex unified_exec 的后台进程不进 TurnDiffTracker；Gemini 检查点只在
编辑工具前打；deepseek-harness 没有）→ 复用 v2.14 的影子库（command_changes），把“一轮”换成“任务开始 → 结算”：
- begin(ws, job_id)：任务启动之前（jobs.start 在叫沙盒之前；转后台的 jobs.adopt 在登记那一刻）扫一遍、把基线钉住
  （command_changes.pin：几小时后才结算，钉住期间影子库不清它要用的旧版本）。常驻服务不盯（tracks）。
- record(db, job)：jobs.settle 结算时（提交之前）：读回钉住的基线 → command_changes.after 找变了的 →
  去掉这期间对话回合自己记过撤销的路径（turn_changes.recorded_since：那些归那一轮的改动卡，免得两张卡撤同一个文件）
  → turn_changes.finish 出净 diff、落撤销记录（同一套 .turns/<token>/，30 天）→ 存进 jobs.changes（JSON 文本）；拔钉。
  同一工作区同时段还有别的后台任务 → overlap（卡上提醒“可能也算进来了”）。
- undo(db, job)：结束了才能撤；核对 / 冲突 / 过期规则全在 turn_changes.undo（之后又被改过的一个都不动）。
- wire / text：任务卡上的改动区（ChangesBlock 形状 + overlap / shared）和给模型的一句话（describe / 结束通知）。
- 出错从不抛：记不了只是卡上没有改动区。
"""
import asyncio
import json
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from . import command_changes, file_edit, job_disk, turn_changes
from .models import Job

SLACK_S = 2          # 回合撤销记录的 mtime 余量（同 job_disk）
NAMES_SHOWN = 3      # 给模型的一句话里点名几个文件


def tracks(keep_alive: bool) -> bool:
    """常驻服务（keep_alive）不盯：一直在跑、会自动重启，“它改了什么”没有结算的那一刻。"""
    return not keep_alive


def _pin(job_id: str) -> str:
    return f"job-{job_id}"


def _begin(ws: str, job_id: str) -> bool:
    t = turn_changes.Tracker()
    command_changes.before(ws, t)
    return command_changes.pin(ws, _pin(job_id), t)


async def begin(ws: str, job_id: str, keep_alive: bool = False) -> bool:
    if not tracks(keep_alive):
        return False
    try:
        return await asyncio.to_thread(_begin, ws, job_id)
    except Exception:
        return False


def drop(ws: str, job_id: str) -> None:
    """任务没能启动：拔钉。"""
    command_changes.unpin(ws, _pin(job_id))


def _finish(ws: str, job_id: str, since: float) -> dict | None:
    t = command_changes.restore(ws, _pin(job_id))
    if t is None:
        return None
    try:
        command_changes.after(ws, t)
        owned = turn_changes.recorded_since(ws, since - SLACK_S)
        shared = 0
        for key in list(t.base):
            if t.rel.get(key) in owned:
                shared += 1
                for m in (t.base, t.rel, t.modes):
                    m.pop(key, None)
                t.command.discard(key)
        block = turn_changes.finish(t, ws)
        if block is None:
            return None
        for f in block["files"]:
            f.pop("command", None)  # 全是任务改的，卡上不用再标“命令”
        if shared:
            block["shared"] = shared
        return block
    finally:
        command_changes.unpin(ws, _pin(job_id))


async def record(db: AsyncSession, job: Job) -> None:
    """结算时调（jobs.settle，提交之前）。没钉（常驻、老任务、开始时没钉上）→ 不存。"""
    if job.keep_alive:
        return
    try:
        since = _ts(job.created_at)
        block = await asyncio.to_thread(_finish, job.project_id, job.id, since)
    except Exception:
        return
    if block is None:
        return
    if block.get("files") and await job_disk.overlap(db, job, job.finished_at):
        block["overlap"] = True
    job.changes = json.dumps(block, ensure_ascii=False)


def _ts(v: datetime) -> float:
    return job_disk._aware(v).timestamp()


def wire(job: Job) -> dict | None:
    """任务卡上的改动区：结束了且有记录才给（ChangesBlock 形状 + overlap / shared）。坏的 → None。"""
    if job.state == "running" or not job.changes:
        return None
    try:
        d = json.loads(job.changes)
    except ValueError:
        return None
    if not isinstance(d, dict) or not isinstance(d.get("files"), list):
        return None
    return d


def total(d: dict) -> int:
    return len(d.get("files") or []) + int(d.get("more") or 0)


def text(d: dict | None) -> str:
    """给模型的一句话（describe / 结束通知）；没改文件 → ""。"""
    if not d or not total(d):
        return ""
    def one(f: dict) -> str:
        if f.get("deleted"):
            return f"{f['path']}（删了）"
        if f.get("big"):
            return f"{f['path']}（大文件）"
        mode = f" {f['mode']}" if f.get("mode") else ""
        return f"{f['path']}（{'新建 ' if f.get('created') else ''}{file_edit.stat(f)}{mode}）"
    files = d["files"]
    names = "、".join(one(f) for f in files[:NAMES_SHOWN])
    more = f" 等 {total(d)} 个文件" if total(d) > NAMES_SHOWN else ""
    line = f"它改了 {names}{more}"
    if d.get("undone"):
        return line + "——用户已在任务卡上撤销，这些文件已回到任务开始前；之前读到的内容已过期"
    if d.get("overlap"):
        line += "（同时还有别的后台任务，可能也算进来了）"
    return line + ("（用户可在任务卡上撤销）" if d.get("token") else "")


async def undo(db: AsyncSession, job: Job) -> list[str]:
    """撤销这个任务改的文件。运行中 / 没有记录 / 撤过 → turn_changes.UndoError；之后又被改过 → Conflict（一个都不动）。"""
    from . import jobs, quota  # jobs 引用本模块：延迟导入避免循环
    if job.state == "running":
        raise turn_changes.UndoError("任务还在运行，结束后才能撤销它改的文件")
    d = wire(job)
    if not d or not total(d):
        raise turn_changes.UndoError("这个任务没有改动文件")
    if d.get("undone"):
        raise turn_changes.UndoError("已经撤销过了")
    done = await asyncio.to_thread(turn_changes.undo, job.project_id, d.get("token") or "")
    quota.forget(job.project_id)
    job.changes = json.dumps({**d, "undone": True}, ensure_ascii=False)
    await jobs.patch_blocks(db, job)
    await db.commit()
    return done
