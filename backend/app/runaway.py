"""前台命令转后台那一刻“像死循环”的判断——唯一入口（v2.42，本地真模型 E2E B15）。

现象：模型明知 `while True: pass` 停不下来还是照跑，120 秒前台窗口一个字没打、一直满 CPU，转后台后又照样
占满一个核直到判卡住 / 1 小时上限——4 GB/2 核的小 VPS 上一句话吃掉一半算力。

规则（只看转后台这一刻已有的事实，不另起采样线程）：
  - 前台窗口里零输出（shown 去掉空白为空），且
  - 进程组累计 CPU 秒 / 已跑秒数 ≥ BUSY_CORES（一直在算，不是在等网络 / sleep），
    或这一刻的采样占满本沙盒 CPU 配额 ≥ BUSY_PERCENT（配额不到一个核时第一条达不到）。
满足 → looks_stuck；调用方（run_command 的转后台回执）把 idle_timeout 收紧到 SILENT_IDLE_S（再没输出就自动停），
并让模型默认停掉它（cancel_job）、告诉用户为什么；用户明说要长时间静默计算才留着。
拿不到用量（沙盒没采到 / 进程已经没了）→ 不判（宁可漏，不冤枉）。

参考：Codex（exec 超时直接杀）、Gemini CLI（shell 超时杀 / 后台不管）、deepseek-harness（promoteOnTimeout 只转后台）
都不看“零输出 + 满 CPU”，无代码可搬 → 自写。口径复用 job_usage（top 式两次采样 + 累计节拍）。
"""
from . import jobs

BUSY_CORES = 0.8       # 平均每秒至少烧掉 0.8 个核
BUSY_PERCENT = 90.0    # 或者这一刻占本沙盒 CPU 配额 ≥ 90%
SILENT_IDLE_S = 300    # 像死循环的任务：再这么久没有输出就判卡住停掉（默认 job_idle_seconds 是 20 分钟）


def looks_stuck(shown: str, seconds: float, usage: dict | None) -> bool:
    if shown.strip() or not usage or seconds <= 0:
        return False
    return usage["cpu_seconds"] / seconds >= BUSY_CORES or usage["cpu"] >= BUSY_PERCENT


def idle_cap(current: int) -> int:
    """收紧后的 idle_timeout（本来更短就不动；0 = 不判卡住也收紧）。"""
    return SILENT_IDLE_S if not current or current > SILENT_IDLE_S else current


def note(job_id: str, seconds: float, usage: dict, idle: int) -> str:
    """给模型的一句：为什么像死循环、默认怎么做。"""
    return (f"⚠ 它在前台 {jobs.duration_text(int(seconds))}里一个字都没输出，却一直在满负荷占 CPU"
            f"（累计 CPU {jobs.duration_text(int(usage['cpu_seconds']))}，现在 {usage['cpu']:g}%）——很像死循环，"
            "留着只会白白占住电脑的算力。下一步直接调用 cancel_job 停掉 " + job_id + "（不用先问用户），"
            "cancel_job 成功之后再告诉用户：它像死循环、一直占满 CPU 没有输出，已经停掉了。"
            "只有用户明确说过要它长时间静默计算时才留着它（并告诉用户它在后台占着 CPU）；"
            f"（它现在还在跑，没有停；你不停的话，要到从开始算起满 {jobs.duration_text(idle)}都没有输出才会被自动停掉。）"
            "真要长时间跑，改成会打印进度的版本再用 background=true 跑。")