"""长输出落盘的唯一入口：工具结果太长时，给模型留开头 + 结尾，完整原文存进项目工作区 .spill/，
告诉它路径，需要时用 read_file 按 offset 分段读回来——既不撑爆上下文（省 token），也不丢信息。

思路参考了 deepseek-ai/deepseek-harness（MIT）的 spill-policy：
  - 预算对半分给开头和结尾（报错和结论常在结尾），中间换成一句“省略了多少 + 去哪看全文”；
  - 落盘失败/没有工作区（主聊天）就只截断不落盘，绝不因为存不下而丢掉工具结果本身；
  - 存下来的文件按项目只留最近 KEEP 个，旧的自动清掉（.spill 是隐藏目录，不进项目文件列表）。
我们在切口上多做一步：尽量切在换行处，不把一行日志拦腰截断。
"""
import secrets
from datetime import datetime, timezone

from .storage import project_dir

SPILL_DIR = ".spill"
MARK = "\n…（中间省略）…\n"  # 沙盒服务截断前台命令输出时放在切口的标记（sandbox/runner.py 里同一个字面量）
KEEP = 50          # 每个项目最多留多少个落盘文件
SNAP = 0.2         # 切口往回找换行最多退让预算的 20%


def _snap_head(text: str, n: int) -> str:
    cut = text.rfind("\n", int(n * (1 - SNAP)), n)
    return text[:cut + 1] if cut >= 0 else text[:n]


def _snap_tail(text: str, n: int) -> str:
    start = len(text) - n
    cut = text.find("\n", start, start + int(n * SNAP))
    return text[cut + 1:] if cut >= 0 else text[start:]


def cut(text: str, budget: int) -> tuple[str, str, int]:
    """(开头, 结尾, 省略的字符数)。budget 是开头 + 结尾的总字符数。"""
    if len(text) <= budget:
        return text, "", 0
    head = _snap_head(text, budget // 2)
    tail = _snap_tail(text, budget - budget // 2)
    return head, tail, len(text) - len(head) - len(tail)


def save(project_id: str, name: str, text: str) -> str:
    """存进 .spill/，返回相对项目根的路径；顺手清掉超出 KEEP 的旧文件。"""
    d = project_dir(project_id) / SPILL_DIR
    d.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:40] or "output"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    p = d / f"{stamp}-{safe}-{secrets.token_hex(2)}.txt"
    p.write_text(text, encoding="utf-8")
    old = sorted(d.glob("*.txt"), key=lambda f: f.stat().st_mtime, reverse=True)[KEEP:]
    for f in old:
        f.unlink(missing_ok=True)
    return f"{SPILL_DIR}/{p.name}"


def notice(omitted: int, path: str | None, total: int) -> str:
    where = f"完整内容（{total} 字符）存在 {path}，要看中间用 read_file path=\"{path}\" offset=<字符位置> 分段读" \
        if path else "要看全文就缩小范围重新查（比如 grep / head / tail）"
    return f"\n…（中间省略 {omitted} 字符；{where}）…\n"


def bound(text: str, limit: int, project_id: str | None = None, name: str = "output") -> str:
    """不超过 limit 原样返回；超过就开头 + 省略说明 + 结尾（总长约 limit）。"""
    if len(text) <= limit:
        return text
    path = None
    if project_id:
        try:
            path = save(project_id, name, text)
        except OSError:
            path = None
    room = max(200, limit - 240)
    head, tail, omitted = cut(text, room)
    return head + notice(omitted, path, len(text)) + tail
