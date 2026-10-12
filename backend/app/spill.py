# Portions ported from deepseek-ai/deepseek-harness (MIT License, Copyright (c) 2026 DeepSeek):
#   packages/spill/spill-policy/src/{index,notice,retention}.ts, packages/spill/spill-local/src/{store,cleanup}.ts
"""长输出落盘的唯一入口：工具结果太长时，给模型留开头 + 结尾，完整原文存进工作区 .spill/，
告诉它路径，需要时用 read_file 按 offset 分段读回来——既不撑爆上下文（省 token），也不丢信息。

v1.38 回炉：移植自 deepseek-harness 的 spill-policy + spill-local（三家里它最完整，Codex/Gemini 只截断或只存临时文件）：
  - 预留"最坏情况"的省略说明再切（spill-policy index.ts）：结果总长严格 ≤ limit，不再靠估一个 240 的余量；
  - 说明本身都放不下预算时，宁可原样保留，不把结果切成只剩一句话（同上，"keeping the inline content"）；
  - 落盘失败（磁盘满、权限）只截断不落盘，绝不声称"全文存在某处"（session-reference spill.ts）；
  - 文件名：调用方给的名字只是提示，单段可逆编码（encode_segment，spill-local store.ts），独占创建 'x'，同名并发不覆盖；
  - 清理：只扫我们自己生成的文件名形状（cleanup.ts 的 SESSION_DIR_RE 思路），不跟随符号链接，
    严格早于截止时间才删（正好在边界上的留下），删的时候别人先删了算成功，清理出错绝不影响这次落盘；
  - 识别已有的说明（notice.ts hasSpillNotice）：沙盒那边已经落过盘的结果再被总闸截断时，沿用原文件，不再存第二份。
我们自己的部分（保留）：切口尽量落在换行处（SNAP），不把一行日志拦腰截断；按数量 KEEP 再兜一层。
不搬：0600/0700 私有目录（.spill 在用户自己的工作区里，沙盒用户要能 cat 它）、图片块计价（我们的工具结果是纯文本）。
沙盒服务 sandbox/runner.py 的 _spill 是同一套约定的镜像（独立部署单元，不能 import 这里）。
"""
import os
import re
import secrets
import stat
import time
from datetime import datetime, timezone

from .storage import project_dir

SPILL_DIR = ".spill"
MARK = "\n…（中间省略）…\n"  # 沙盒服务截断前台命令输出时放在切口的标记（sandbox/runner.py 里同一个字面量）
KEEP = 50          # 每个工作区最多留多少个落盘文件
DAYS = 30          # 超过这么多天的落盘文件清掉（deepseek cleanupPeriodDays 默认 30；0 = 不按时间清）
SNAP = 0.2         # 切口往回找换行最多退让预算的 20%
# 我们生成的文件名：20261012-081500-<编码后的名字>-<4 位 hex>.txt；清理只认这个形状
NAME_RE = re.compile(r"^\d{8}-\d{6}-[A-Za-z0-9._~-]{1,160}-[0-9a-f]{4}\.txt$")
_SAFE = re.compile(r"[A-Za-z0-9._-]")
# 说明的固定写法（notice() 产出）；existing() 靠它认出已经落过盘的结果
_NOTICE_RE = re.compile(r"\n…（中间省略 (\d+) 字符；完整内容（(\d+) 字符）存在 (\.spill/[^\s，/]+\.txt)，")


def encode_segment(raw: str, cap: int = 40) -> str:
    """把任意名字编码成一个安全的路径段（移植 spill-local encodeSegment）：[A-Za-z0-9._-] 原样，其余（含 ~）写成 ~XXXX，
    可逆、不同输入不撞；整段 . / .. 也转义，永远走不出目录；空串 → ~。cap 截短只截在完整的转义单元之间。"""
    if raw == "":
        return "~"
    if raw in (".", ".."):
        return "~002E" * len(raw)
    out, n = [], 0
    for ch in raw:
        piece = ch if ch != "~" and _SAFE.fullmatch(ch) else "".join(
            f"~{u:04X}" for u in _utf16(ch))
        if n + len(piece) > cap:
            break
        out.append(piece)
        n += len(piece)
    return "".join(out) or "~"


def _utf16(ch: str) -> list[int]:
    b = ch.encode("utf-16-be", "surrogatepass")
    return [int.from_bytes(b[i:i + 2], "big") for i in range(0, len(b), 2)]


def _snap_head(text: str, n: int) -> str:
    cut = text.rfind("\n", int(n * (1 - SNAP)), n)
    return text[:cut + 1] if cut >= 0 else text[:n]


def _snap_tail(text: str, n: int) -> str:
    if n <= 0:
        return ""
    start = len(text) - n
    cut = text.find("\n", start, start + int(n * SNAP))
    return text[cut + 1:] if cut >= 0 else text[start:]


def cut(text: str, budget: int) -> tuple[str, str, int]:
    """(开头, 结尾, 省略的字符数)。budget 是开头 + 结尾的总字符数；开头拿 ceil(一半)、结尾拿 floor(一半)，
    两段永不重叠、合计永不超 budget（retention.ts retainContent）。"""
    budget = max(0, budget)
    if len(text) <= budget:
        return text, "", 0
    head = _snap_head(text, (budget + 1) // 2)
    tail = _snap_tail(text, budget // 2)
    return head, tail, len(text) - len(head) - len(tail)


def _sweep(d) -> None:
    """清理：只认 NAME_RE 形状的普通文件（符号链接、子目录、用户放进来的别的文件都不碰）；
    严格早于 DAYS 天前的删掉，再按新旧只留 KEEP 个。任何出错都吞掉——清理失败不能连累落盘本身。"""
    try:
        cutoff = time.time() - DAYS * 86400 if DAYS > 0 else None
        ours = []
        with os.scandir(d) as it:
            for e in it:
                if not NAME_RE.match(e.name):
                    continue
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISREG(st.st_mode):
                    ours.append((st.st_mtime, e.path))
        ours.sort(reverse=True)
        doomed = [p for m, p in ours if cutoff is not None and m < cutoff] + [p for _, p in ours[KEEP:]]
        for p in dict.fromkeys(doomed):
            try:
                os.unlink(p)
            except FileNotFoundError:  # 别人先删了：目标已达成
                pass
    except OSError:
        pass


def save(project_id: str, name: str, text: str) -> str:
    """存进 .spill/，返回相对工作区根的路径；独占创建（同名同秒也不覆盖），顺手清掉过期 / 超量的旧文件。
    存不下（磁盘满、权限）就抛 OSError，由调用方决定退化成只截断。"""
    d = project_dir(project_id) / SPILL_DIR
    d.mkdir(parents=True, exist_ok=True)
    safe = encode_segment(name)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    for _ in range(8):
        p = d / f"{stamp}-{safe}-{secrets.token_hex(2)}.txt"
        try:
            with open(p, "x", encoding="utf-8") as f:
                f.write(text)
            break
        except FileExistsError:
            continue
    else:
        raise FileExistsError(f"{SPILL_DIR}/{stamp}-{safe}-*.txt")
    _sweep(d)
    return f"{SPILL_DIR}/{p.name}"


def notice(omitted: int, path: str | None, total: int) -> str:
    where = f"完整内容（{total} 字符）存在 {path}，要看中间用 read_file path=\"{path}\" offset=<字符位置> 分段读" \
        if path else "要看全文就缩小范围重新查（比如 grep / head / tail）"
    return f"\n…（中间省略 {omitted} 字符；{where}）…\n"


def existing(text: str) -> tuple[str, int] | None:
    """结果里已有一条落盘说明（沙盒那边存过全文）就返回 (路径, 全文字符数)，否则 None。只认 notice() 的完整写法。"""
    m = _NOTICE_RE.search(text)
    if not m or not NAME_RE.match(m.group(3)[len(SPILL_DIR) + 1:]):
        return None
    return m.group(3), int(m.group(2))


def bound(text: str, limit: int, project_id: str | None = None, name: str = "output") -> str:
    """不超过 limit 原样返回；超过就开头 + 省略说明 + 结尾，总长严格 ≤ limit。
    已经落过盘的结果沿用原文件；没有工作区 / 存不下就只截断，说明里不提路径。"""
    if len(text) <= limit:
        return text
    path, total = None, len(text)
    if (prior := existing(text)) is not None:
        path, total = prior
    elif project_id:
        try:
            path = save(project_id, name, text)
        except OSError:
            path = None
    worst = notice(len(text), path, total)  # 省略数最多就是全长：按它预留，实际说明只会更短
    if len(worst) > limit:
        return text  # 说明本身都放不下：保留原文（spill-policy 的同一取舍）
    head, tail, omitted = cut(text, limit - len(worst))
    return head + notice(omitted, path, total) + tail
