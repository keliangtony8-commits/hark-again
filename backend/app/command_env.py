"""命令环境变量：保险箱里 kind="env" 的条目，按变量名注入沙盒里跑的每条命令（前台命令、后台 / 常驻任务、
定时脚本、用户 `!命令`），输出回到模型和界面之前把值打码。唯一规则在这里。

为什么要有：常驻机器人、定时脚本要用用户自己的 Token（TELEGRAM_BOT_TOKEN、OPENAI_API_KEY…），
api_request 那种“按域名进请求头”管不到沙盒里的程序；把值写进工作区文件又会被模型读到、留在磁盘上。

参考：Codex core/src/exec_env.rs（运行时注入的变量最后写、覆盖继承值）+ Gemini CLI
services/environmentSanitization.ts（PATH/HOME/LANG… 永远放行的那张表）。两家做的都是“别把本机的密钥漏进
shell”，没有“把用户的密钥按名字给 shell、再从输出里抹掉”，这部分是自写的。

边界（说清楚，不夸大）：打码挡的是“原样出现”的值（echo、报错里带出、日志里打印）；程序把它 base64、拆开
再打印就挡不住——这层防的是不小心泄露，不是对抗模型。服务器主机模式（host_command）不注入。"""
import re
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import vault
from .models import Secret

KIND = "env"
NAME_RE = re.compile(r"[A-Z][A-Z0-9_]{1,63}")
# Gemini ALWAYS_ALLOWED_ENVIRONMENT_VARIABLES 的 Unix 部分 + 沙盒自己用的：用户不能覆盖，否则命令跑不起来
RESERVED = frozenset({"PATH", "HOME", "LANG", "SHELL", "TMPDIR", "USER", "LOGNAME", "TERM", "COLORTERM", "PWD",
                      "OLDPWD", "HOSTNAME", "SHLVL", "IFS", "BASH_ENV", "ENV", "PS1", "LD_PRELOAD",
                      "LD_LIBRARY_PATH", "STDIN_B64"})
ENV_MAX = 30          # 最多几个（sandbox/runner.py 同一个数）
VALUE_MIN = 6         # 太短的值打码会误伤正常输出，干脆不让存
VALUE_MAX = 8192      # 单个值上限（sandbox/runner.py 同一个数）
EDGE_MIN = 6          # 输出窗口边上露出的半截值，至少这么长才抹
MAX_AGE_S = 60        # 别的进程（worker）里的缓存多久重读一次


def mask(name: str) -> str:
    return f"[${name}]"


def check_name(name: str) -> str:
    """规范化（去空白、转大写、开头的 $ 去掉）并校验；不合格抛 ValueError（中文一句，接口直接给用户看）。"""
    n = (name or "").strip().lstrip("$").upper()
    if not NAME_RE.fullmatch(n):
        raise ValueError("变量名只能用大写字母、数字和下划线，字母开头，2–64 个字符，比如 TELEGRAM_BOT_TOKEN")
    if n in RESERVED:
        raise ValueError(f"{n} 是系统变量，不能覆盖，换个名字")
    return n


def check_value(value: str) -> str:
    if "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError("值不能有换行")
    if len(value) < VALUE_MIN:
        raise ValueError(f"值至少 {VALUE_MIN} 个字符（太短没法在输出里可靠地打码）")
    if len(value) > VALUE_MAX:
        raise ValueError(f"值最多 {VALUE_MAX} 个字符")
    return value


def preview(value: str) -> str:
    """界面辨认用的末 4 位：值够长才露（短值露 4 位等于露了一大半）。"""
    return value[-4:] if len(value) >= 16 else ""


# ---- 进程内缓存：打码是同步的（日志读取、终端尾巴都在同步代码里），值在这里常驻 ----
_values: dict[str, str] = {}
_loaded_at = 0.0


def _set(values: dict[str, str]) -> None:
    global _values, _loaded_at
    _values, _loaded_at = dict(values), time.monotonic()


async def load(db: AsyncSession) -> dict[str, str]:
    """解密全部 env 条目 → {变量名: 值}，并刷新打码缓存。保险箱不可用 / 某条解不开 → 跳过它（不让命令整个跑不了）。"""
    out: dict[str, str] = {}
    rows = (await db.scalars(select(Secret).where(Secret.kind == KIND).order_by(Secret.created_at))).all()
    for s in rows[:ENV_MAX]:
        try:
            out[s.name] = vault.reveal(s)
        except Exception:  # noqa: BLE001 — VAULT_KEY 换了 / 没配：这一条当不存在
            continue
    _set(out)
    return out


async def ensure(db: AsyncSession, max_age: float = MAX_AGE_S) -> None:
    """长跑进程（worker）定期调：缓存过期才重读。没有库会话（个别测试桩）就不动。"""
    if db is not None and time.monotonic() - _loaded_at > max_age:
        await load(db)


async def names(db: AsyncSession) -> list[str]:
    return sorted((await db.scalars(select(Secret.name).where(Secret.kind == KIND))).all())


def prompt(var_names: list[str]) -> str:
    """系统提示里的一段（稳定段，按名字排序）：模型只知道名字。"""
    if not var_names:
        return ""
    return ("沙盒里每条命令（含后台 / 常驻任务、定时脚本）都已注入这些环境变量，值来自用户的保险箱："
            + "、".join(f"${n}" for n in var_names)
            + "。程序里直接读环境变量（os.environ / process.env / \"$NAME\"），别把值写进文件、别打印它；"
            "输出里出现的值会显示成 [$NAME]。缺哪个就请用户在「我的 → 保险箱 → 环境变量」里加。")


def scrub(text: str, values: dict[str, str] | None = None) -> str:
    """把值换成 [$NAME]；长值先换（一个值是另一个的一部分时不留半截）。
    文本开头是某个值的后半截、结尾是某个值的前半截（≥EDGE_MIN 字）也抹掉：日志尾巴、流式片段是从中间切的。"""
    vals = _values if values is None else values
    if not text or not vals:
        return text
    pairs = sorted(((v, n) for n, v in vals.items() if v), key=lambda p: -len(p[0]))
    for v, n in pairs:
        if v in text:
            text = text.replace(v, mask(n))
    for v, n in pairs:
        for k in range(len(v) - 1, EDGE_MIN - 1, -1):
            if text.startswith(v[-k:]):
                text = mask(n) + text[k:]
                break
        for k in range(len(v) - 1, EDGE_MIN - 1, -1):
            if text.endswith(v[:k]):
                text = text[:-k] + mask(n)
                break
    return text
