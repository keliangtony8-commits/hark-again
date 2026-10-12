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

参考：deepseek-harness / Codex / Gemini CLI 都在本机跑命令，没有“按归属汇总内存”的视图，无代码可搬；
口径借 smem（PSS 按进程组汇总）+ systemd-cgtop / Docker Desktop（按服务排、余下归“其它”）。
"""
from . import job_usage
from .models import Job

ROWS_MAX = 6
MIN_ROW = 1 << 20  # 1 MB 以下的不单列


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
