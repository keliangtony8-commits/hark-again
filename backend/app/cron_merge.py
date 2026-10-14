"""同一件事一天几个时刻 → 一个 cron（v2.63，E2E 第十三轮 B34：“9 点到 21 点每 2 小时喝水”被拆成 7 个每天任务，
任务列表一长串、改一次要改 7 个）。唯一规则（纯函数，schedule_task create 用）：

几条 cron 只有“小时”不同（分钟、日、月、星期完全一样，小时都是单个数字）才合并：
- 小时排好去重；≥3 个且等差 → a-b/step（步长 1 写 a-b）；否则逗号列表 9,12,18。
- 任何一条不是 5 段、小时不是单个数字、其余段不一样 → None（不合并，各管各的）。"""

FIELDS = 5


def _hours(values: list[int]) -> str:
    hs = sorted(set(values))
    if len(hs) >= 3:
        step = hs[1] - hs[0]
        if all(b - a == step for a, b in zip(hs, hs[1:])):
            return f"{hs[0]}-{hs[-1]}" if step == 1 else f"{hs[0]}-{hs[-1]}/{step}"
    return ",".join(str(h) for h in hs)


def merge(crons: list[str]) -> str | None:
    parts = [(c or "").split() for c in crons]
    if len(parts) < 2 or any(len(p) != FIELDS for p in parts):
        return None
    rest = {(p[0], *p[2:]) for p in parts}
    if len(rest) != 1:
        return None
    hours = []
    for p in parts:
        if not p[1].isdigit() or not 0 <= int(p[1]) <= 23:
            return None
        hours.append(int(p[1]))
    m, dom, mon, dow = next(iter(rest))
    return f"{m} {_hours(hours)} {dom} {mon} {dow}"
