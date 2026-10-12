"""活动时间线（"它刚才干了什么"）的唯一规则：一条回复里每次工具调用记一步。

对标 Manus "Manus's computer" 侧栏、Hark 的工作过程可回看：回复上方一行“用了 N 步 · 用时”，点开按顺序看
每一步做了什么（运行命令 `ls`、读文件 a.txt、打开网页 x.com…）、成功/失败/没批准、各用了多久。
步骤跟着消息落库（messages.steps），换设备、重新打开对话都还在；实时由 WS tool.status 事件推（带完整 step）。

一步 = {"id", "tool", "title", "detail", "state", "at", "ms"[, "note"]}：
- title：工具 label 去掉“正在”（“正在运行命令” → “运行命令”）；
- detail：从参数里按白名单取一个摘要（命令、路径、网址、搜索词…）。只取白名单里的键——
  browser_type 的 text、run_command 的 stdin、write_file 的 content 这类可能含隐私/很长的值永远不进时间线；
- state：running | done | error | denied（没批准/没填表）| stopped（这一轮被停掉时还在跑）；
- at：开始时间（ISO，带时区，经 wire_time）；ms：用时毫秒（running 时没有）；
- note：只在 error / denied 时带一句原因（≤ NOTE_MAX 字）；
- change：只在工具改了工作区文件时（write_file / edit_file，v1.34）带 {"path","added","removed","diff"[,"created"]}，
  形状和截断规则在 file_edit.py；两端在这一步上显示 “+3 −1”，点开看 diff。
"""
import time
from datetime import datetime, timezone

from .wire_time import iso

# 摘要从这些参数里取，按顺序第一个有值的（值是列表就拼前几个）。新工具想上时间线摘要，参数名用这些之一即可。
DETAIL_KEYS = ("command", "url", "query", "pattern", "port", "path", "paths", "job_id", "title", "name", "skill", "server", "tool", "reason", "tasks")
DETAIL_MAX = 120
NOTE_MAX = 160
KEEP = 80  # 一条回复最多记这么多步（长任务可走到 agent_max_steps 次模型调用；更早的步骤只是噪音，留最近的）


def title(label: str) -> str:
    return label.removeprefix("正在").strip() or label


def _short(text: str, limit: int) -> str:
    text = " ".join(str(text).split())  # 换行/多空格压成一行：时间线一步一行
    return text if len(text) <= limit else text[: limit - 1] + "…"


def detail(args: dict) -> str:
    for key in DETAIL_KEYS:
        v = args.get(key)
        if isinstance(v, list):
            v = [x.get("title") if isinstance(x, dict) else x for x in v]  # 子任务 [{title, prompt}] 只列标题
            v = "、".join(str(x) for x in v[:3] if x) + (f" 等 {len(v)} 个" if len(v) > 3 else "")
        if isinstance(v, (str, int)) and str(v).strip():
            return _short(str(v), DETAIL_MAX)
    return ""


class Recorder:
    """一条回复的步骤记录。由 MessageBuilder 持有（和块一样随回复落库）。"""

    def __init__(self) -> None:
        self.steps: list[dict] = []
        self._t0: dict[str, float] = {}

    def start(self, call_id: str, tool: str, label: str, args: dict) -> dict:
        step = {"id": call_id, "tool": tool, "title": title(label), "detail": detail(args), "state": "running",
                "at": iso(datetime.now(timezone.utc))}
        self._t0[call_id] = time.monotonic()
        self.steps.append(step)
        del self.steps[:-KEEP]
        return dict(step)

    def finish(self, call_id: str, state: str, note: str = "", change: dict | None = None,
               detail: str | None = None) -> dict | None:
        """detail：结束时才知道的摘要（如上文压缩的结果）替换开始时的。"""
        step = next((s for s in self.steps if s["id"] == call_id), None)
        if step is None:
            return None
        step["state"] = state
        if detail is not None:
            step["detail"] = _short(detail, DETAIL_MAX)
        if (t0 := self._t0.pop(call_id, None)) is not None:
            step["ms"] = int((time.monotonic() - t0) * 1000)
        if note and state in ("error", "denied"):
            step["note"] = _short(note, NOTE_MAX)
        if change and state == "done":
            step["change"] = change
        return dict(step)

    def denied(self, call_id: str, tool: str, label: str, args: dict, note: str) -> dict:
        """没走到执行（没批准 / 表单取消）：直接记一条 denied。"""
        self.start(call_id, tool, label, args)
        return self.finish(call_id, "denied", note)  # type: ignore[return-value]

    def partial(self) -> list[dict]:
        """这一轮被停掉：还在跑的步骤记为 stopped。"""
        return [{**s, "state": "stopped"} if s["state"] == "running" else dict(s) for s in self.steps]

