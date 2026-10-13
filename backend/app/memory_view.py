"""“内存去哪了”（v1.94，CORE 20）——唯一入口。电脑页上那一节：整台沙盒用了多少，按大小排出是谁占的。
对标 Hark / Manus 云电脑“哪个程序在吃资源”：4 GB 的小 VPS 上内存快满时，用户一眼要看出该停哪个。

build(raw, running, usage) → {used, limit, rows, other} 或 None（电脑没在跑 / 拿不到已用量）：
  - used / limit：沙盒的整台内存（docker stats 口径，和状态块那条内存条是同一个数，不会一页两个数）；
  - rows：按占用从大到小，最多 ROWS_MAX 行，小于 MIN_ROW 的不列：
      kind job / service —— 后台任务 / 常驻服务（job_usage 的进程组 PSS，整组算一个，fork 出的 worker 不重复算），带 id，
                            客户端点了打开那个任务；
      kind process        —— 不属于任何后台任务的程序（对话里直接跑的命令、nohup 起的进程），沙盒 ps 的 memory_top（RSS），带 pid；
    每行 share = 占已用的比例（0–1）；
  - other：已用减去上面所有行（系统、零碎小程序、口径差）；不足 MIN_ROW 记 0。行加起来超过已用（PSS / RSS 口径差）时 other=0、
    share 照算（客户端把条封顶到 1）。
“快满了”的门槛归客户端（和状态块的内存条同一个 computerMemoryTight），这里只给事实。

v2.00（CORE 23）给模型的那一份：
  - current(db, ws) → 同一张表（一次沙盒 status + 一次进程组采样）；电脑没开 / 连不上 → None。
  - note(view, after_oom=False) → 给模型的一句，是“内存快满 / 刚被系统杀了进程”时唯一的说法：
      平时只有整台用到 job_memory.TIGHT 以上才说；after_oom（前台命令 / 后台任务刚被内核因内存杀掉）不论多少都说——
      杀完内存多半已降下来，但模型得知道剩下谁在占，才不会原样重跑又被杀。
      列前 NOTE_ROWS 个：后台任务 / 常驻服务带编号（cancel_job / restart_service 用），零散程序带 pid 和命令（kill 用），
      再给出路：普通任务能停先停、零散程序先确认是什么再 kill、常驻服务别随手停（先问用户）。

参考：deepseek-harness / Codex / Gemini CLI 都在本机跑命令，没有“按归属汇总内存”的视图，无代码可搬；
口径借 smem（PSS 按进程组汇总）+ systemd-cgtop / Docker Desktop（按服务排、余下归“其它”）。
"""
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from . import job_memory, job_usage, jobs, quota, sandbox_client
from .models import Job

ROWS_MAX = 6
MIN_ROW = 1 << 20  # 1 MB 以下的不单列
NOTE_ROWS = 3      # 给模型的那句列几个
CMD_SHOWN = 60     # 零散程序的命令给模型看多长
KIND_TEXT = {"job": "后台任务", "service": "常驻服务", "process": "零散程序"}


def _int(v) -> int | None:
    return v if type(v) is int and v >= 0 else None


def build(raw: dict | None, running: list[Job], usage: dict[str, dict]) -> dict | None:
    if not isinstance(raw, dict) or raw.get("state") != "running":
        return None
    used = _int(raw.get("memory_used"))
    if used is None:
        return None
    limit = _int(raw.get("memory_limit")) or None
    rows: list[dict] = []
    owned: set[int] = set()
    counted = 0
    for j in running:
        g = job_usage.pgid(j)
        if g is not None:
            owned.add(g)
        u = usage.get(j.id)
        if not u:
            continue
        counted += u["memory"]
        rows.append({"kind": "service" if j.keep_alive else "job", "id": j.id, "title": j.title or j.command[:80],
                     "memory": u["memory"], "processes": u["processes"]})
    for p in raw.get("memory_top") or []:
        if not isinstance(p, dict) or _int(p.get("memory")) is None or _int(p.get("pid")) is None:
            continue
        if p.get("pgid") in owned:
            continue  # 已经算在它的后台任务里了
        counted += p["memory"]
        rows.append({"kind": "process", "pid": p["pid"], "title": str(p.get("command") or "")[:200],
                     "memory": p["memory"], "processes": 1})
    rows = sorted((r for r in rows if r["memory"] >= MIN_ROW), key=lambda r: -r["memory"])[:ROWS_MAX]
    for r in rows:
        r["share"] = round(r["memory"] / used, 3) if used else 0.0
    other = used - counted
    return {"used": used, "limit": limit, "rows": rows, "other": other if other >= MIN_ROW else 0}


async def current(db: AsyncSession, ws: str) -> dict | None:
    """现在这台电脑的内存表（给模型用）；电脑没开 / 连不上 → None。"""
    try:
        raw = await sandbox_client.status(ws)
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(raw, dict) or raw.get("state") != "running":
        return None
    running = await jobs.running(db, ws)
    return build(raw, running, await job_usage.for_jobs(running))


def _who(r: dict) -> str:
    size = quota.size_text(r["memory"])
    if r["kind"] == "process":
        cmd = r["title"] if len(r["title"]) <= CMD_SHOWN else r["title"][:CMD_SHOWN] + "…"
        return f"零散程序 pid {r['pid']}「{cmd}」约 {size}"
    return f"{KIND_TEXT[r['kind']]} {r['id']}「{r['title']}」约 {size}"


def note(view: dict | None, after_oom: bool = False) -> str:
    """给模型的一句；不紧张（且不是刚被杀）或拿不到表 → 空。"""
    if not view:
        return ""
    used, limit = view["used"], view["limit"]
    box = {"used": used, "limit": limit} if limit else None
    tight = job_memory.tight(box)
    if not tight and not after_oom:
        return ""
    amount = (f"{round(used * 100 / limit)}%（{quota.size_text(used)} / {quota.size_text(limit)}）" if limit
              else f"约 {quota.size_text(used)}")
    rows = view["rows"][:NOTE_ROWS]
    who = "；".join(_who(r) for r in rows)
    who = f"占得最多的：{who}" if who else "没有哪个程序特别大（多半是系统和零碎小程序）"
    kinds = {r["kind"] for r in rows}
    ways = []
    if "job" in kinds:
        ways.append("用不着的后台任务用 cancel_job 停掉")
    if "process" in kinds:
        ways.append("零散程序先用 ps -p <pid> -o args= 确认是什么，确定没用再 kill <pid>")
    if "service" in kinds:
        ways.append("常驻服务别随手停，要停先问用户")
    ways.append("大任务改成分批处理，或给它设 memory_limit")
    head = "注意：这台电脑内存已用" if tight else "这台电脑现在内存已用"
    tail = "再涨系统会强制结束进程（先结束普通后台任务，尽量保住常驻服务）。" if tight else ""
    return f"{head} {amount}，{who}。{tail}要腾内存：{'；'.join(ways)}。"
