"""终端输出 → 给人看 / 给模型读的文本：唯一的一条规则（v1.40）。

用到的地方：run_command 的结果与运行中卡片、后台任务的日志尾巴与 job_status 的增量读取。
沙盒那边（sandbox/runner.py）在流式读输出时用同一个 ANSI_PATTERN 先洗一遍，这里再兜底（旧沙盒 / 任务日志是原样写盘的）。

- ANSI 转义序列：正则移植自 chalk/ansi-regex 6.x（MIT，Copyright (c) Sindre Sorhus），Gemini CLI 的
  shellExecutionService 用的就是它（strip-ansi）。颜色、清行 \\x1b[K、光标移动、OSC 标题/超链接都去掉。
- \\r 进度帧：每行只留最后一次刷新的样子（pip、wget、tqdm）；\\r\\n 当普通换行。
- 其余控制字符（\\b、\\x07 等）丢掉，\\n 和 \\t 保留。
- 二进制：采样开头 512 字节里出现 NUL 就当二进制（Gemini CLI textUtils.isBinary 的同一判定），不把乱码塞给模型。
"""
from __future__ import annotations

import re

# Ported from chalk/ansi-regex index.js (MIT)，modified：OSC 单列一支、[ 转义 — 与 sandbox/runner.py 的 ANSI_PATTERN 必须一字不差（冒烟测试比对）
ANSI_PATTERN = (
    "(?:\u001B\\][^\u0007\u001B\u009C]*(?:\u0007|\u001B\\x5c|\u009C))|"  # OSC 整段（标题、超链接；ansi-regex 6.2 的写法）
    "[\u001B\u009B][\\[\\]()#;?]*(?:(?:(?:(?:;[-a-zA-Z\\d\\/#&.:=?%@~_]+)*"
    "|[a-zA-Z\\d]+(?:;[-a-zA-Z\\d\\/#&.:=?%@~_]*)*)?(?:\u0007|\u001B\\x5c|\u009C))"
    "|(?:(?:\\d{1,4}(?:;\\d{0,4})*)?[\\dA-PR-TZcf-nq-uy=><~]))"
)
ANSI_RE = re.compile(ANSI_PATTERN)
_CTRL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")  # 去完转义后剩下的杂控制字符（\t \n \r 留着）

BINARY_SAMPLE = 512
LIVE_LINES, LIVE_CHARS = 40, 4000  # 运行中卡片只带最近这些输出：每 0.5 秒整块推一次，别越推越大


def strip(text: str) -> str:
    """去掉 ANSI 转义和杂控制字符。"""
    if "\x1b" in text or "\x9b" in text:
        text = ANSI_RE.sub("", text)
    return _CTRL_RE.sub("", text)


def frames(text: str) -> str:
    """\\r 原地刷新的进度条：每行只留最后一帧；\\r\\n 当普通换行；行尾孤立的 \\r 去掉。"""
    if "\r" not in text:
        return text
    return "\n".join(ln.rsplit("\r", 1)[-1] if "\r" in ln.rstrip("\r") else ln.rstrip("\r")
                     for ln in text.split("\n"))


def clean(text: str) -> str:
    """给人 / 模型看的终端文本：先去转义，再折叠进度帧。"""
    return frames(strip(text))


def is_binary(raw: bytes, sample: int = BINARY_SAMPLE) -> bool:
    return b"\x00" in raw[:sample]


def binary_note(size: int) -> str:
    return (f"（输出是二进制数据，共 {size} 字节，没有显示；要保存就把命令输出重定向到文件，"
            "例如 命令 > out.bin，再用 display_file 发给用户）")


def tail(text: str, lines: int = LIVE_LINES, chars: int = LIVE_CHARS) -> str:
    """运行中给用户看的最近输出：最多 lines 行、chars 字（先洗再截，转义不占名额）。"""
    w = text[-chars * 2:]
    if len(w) < len(text):  # 从中间切进来的：开头可能是半条转义序列，从下一行（没有换行就从下一个 ESC）开始
        nl, esc = w.find("\n"), w.find("\x1b", 0, 64)
        w = w[nl + 1:] if nl >= 0 else w[esc:] if esc >= 0 else w
    text = clean(w)
    return "\n".join(text.split("\n")[-lines:])[-chars:]
