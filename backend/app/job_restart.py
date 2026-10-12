"""常驻后台任务（keep_alive，v1.80）的唯一重启规则：哪种结束要拉起、等多久、什么时候放弃。纯函数，不碰数据库和沙盒；
重启这个动作在 jobs.py（_end / _relaunch）。

参考（只借语义，无代码可搬：deepseek-harness / Codex / Gemini CLI 都跑在用户本机，没有“替用户看着一个服务”这层）：
  - systemd Restart=on-failure / supervisord autorestart=unexpected：正常退出（0）= 它自己做完了，不拉起；
    非零、被信号/内核杀、容器重启进程没了 = 意外，拉起。用户或助手停的（cancelled）永远不拉起。
  - Docker 重启策略 / PM2 exp-backoff-restart-delay：等待时间每次翻倍、有上限，稳定跑过一段就清零。
  - systemd StartLimitBurst：短时间里一直起不来就别再试了（不然 4GB 小机上一个坏服务会一直吃 CPU、刷日志），
    交给助手看日志、告诉用户。
"""
from dataclasses import dataclass

FIRST_S = 5        # 第一次意外退出后等几秒再起（worker 本来就 5 秒一轮）
MAX_S = 300        # 等待上限
STABLE_S = 60      # 这次跑满这么久才算“起来了”：清零连续崩溃计数
CRASH_LIMIT = 5    # 连续这么多次“没跑满 STABLE_S 就退出”还会重启；再下一次就放弃
UNEXPECTED = ("failed", "lost", "timed_out")  # 常驻任务不限时，timed_out 只可能是程序自己 exit 124


@dataclass(frozen=True)
class Verdict:
    streak: int              # 新的连续崩溃次数（写回 Job.crash_streak）
    delay: int | None        # 多少秒后重启；None = 不重启（正常结束或放弃）
    give_up: str | None = None  # 放弃时给人看的原因（写进 stop_reason）


def unexpected(state: str) -> bool:
    return state in UNEXPECTED


def decide(state: str, run_seconds: float, streak: int) -> Verdict:
    """这一次进程结束了（state 是 jobs.observe 的结论或 lost），常驻任务接下来怎么办。"""
    if not unexpected(state):
        return Verdict(streak, None)
    streak = 1 if run_seconds >= STABLE_S else streak + 1
    if streak > CRASH_LIMIT:
        return Verdict(streak, None, give_up_text())
    return Verdict(streak, min(MAX_S, FIRST_S * 2 ** (streak - 1)))


def give_up_text() -> str:
    return f"连续 {CRASH_LIMIT + 1} 次启动后不到 1 分钟就退出，已停止自动重启"
