"""“用户点名要存成某个文件，回复说生成好了，工作区里却没有这个文件”的检测（唯一入口，v2.73 E2E B40）。

真机 E2E round 16 v7（第 3 次重跑）：用户“统一手机号格式，存成 通讯录_整理.csv”；模型只 read_file 了一次，
在回复里画了张表，说“整理后的内容已经生成好了……整理后文件 `通讯录_整理.csv`”——文件根本没写。
claimed_action 按说法匹配（“内容已经生成好了”不带文件名词）漏了；再往正则里加词只会越补越乱。
这里换个更硬的依据：用户原话里点名的输出文件名，回复交付前去工作区里看它在不在——看的是磁盘，不是措辞。
Codex / Gemini CLI / deepseek-harness 都是开发者工具，用户自己看得到磁盘，没有这类检查，所以自写，零额外调用：

- wanted(question)：用户这一轮要“存成 / 保存为 / 导出成 / 写到 / 命名为 / save as …”的带扩展名文件名
  （说“别存 / 先不用存”的、同一小句里说删掉的不算）；
- missing(question, reply, root, acted)：点名的文件一个都没在工作区（根目录同名路径，或任意子目录同名文件）→ 缺的那些；
  回复如实说做不到（owed_delivery.HONEST）、这一轮建了定时任务（以后才写）、回复只是反问用户（以问号结尾又没说做完）→ 不追究；
- 命中时 loop.py 撤回这段回复，追加 nudge() 再走一步（每轮最多 ONCE 次）；计划模式（不能写文件）不查。
"""
import os
import re
from pathlib import Path

from .claimed_action import SCHEDULE
from .owed_delivery import HONEST

ONCE = 1
FILES_MAX = 20_000  # 找同名文件最多看多少个文件（大工作区不拖慢交付）
_SKIP_DIRS = frozenset({".git", ".jobs", ".spill", ".home", "node_modules", ".venv", "venv", "__pycache__", ".cache"})

_NAME = r"[`'\"“‘「『]?((?:[^\s`'\"“”‘’「」『』，。,；;：:（）()<>|*?\\]{1,80}/)*[^\s`'\"“”‘’「」『』，。,；;：:（）()<>|*?\\/]{1,80}\.[A-Za-z0-9]{1,6})(?![A-Za-z0-9])"
_VERB = (r"(?:另存为|另存成|存成|存为|存到|存进|保存成|保存为|保存到|导出成|导出为|导出到|输出成|输出为|输出到|"
         r"写成|写到|写进|写入|命名为|改名为|重命名为|生成|做成|转成|新建|建一个|放到|放进)")
WANT = re.compile(rf"{_VERB}(?:一个|一份|个|份|成|为|到)?(?:文件|新文件)?\s*{_NAME}"
                  rf"|\b(?:save|export|write)\s+(?:it|this|them|that|the \w+)?\s*(?:as|to|into)\s+{_NAME}"
                  rf"|\b(?:create|make)\s+(?:a\s+(?:file\s+)?)?{_NAME}", re.I)
_NOT = re.compile(r"(?:别|不用|不要|先不|不必|无需|没让你)\S{0,3}$|\b(?:don't|do not|no need to)\s*$", re.I)
_DELETE = re.compile(r"删|移除|清掉|扔掉|\b(?:delete|remove)\b", re.I)
_CLAUSE = re.compile(r"[，,。！？!?；;\n]+")
_DONE = re.compile(r"已|好了|完成|生成|存|写|\b(?:done|saved|created)\b", re.I)


def wanted(question: str) -> list[str]:
    """用户这一轮点名要做出来的文件名（去重，按出现顺序）。"""
    out: list[str] = []
    for clause in _CLAUSE.split(question or ""):
        if _DELETE.search(clause):
            continue
        for m in WANT.finditer(clause):
            name = next(g for g in m.groups() if g)
            if _NOT.search(clause[:m.start()]):
                continue
            name = name.removeprefix("/workspace/").lstrip("./")
            if name and name not in out:
                out.append(name)
    return out


def _exists(root: Path, name: str) -> bool:
    p = root / name
    if p.is_file():
        return True
    if "/" in name:
        return False
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        if name in filenames:
            return True
        seen += len(filenames)
        if seen >= FILES_MAX:
            return True  # 看不完：不冤枉它
    return False


def _asks_back(reply: str) -> bool:
    text = (reply or "").strip()
    return text.endswith(("？", "?")) and not _DONE.search(text)


def missing(question: str, reply: str, root: Path | str | None, acted: set[str] | frozenset[str]) -> list[str]:
    """点名要的文件里，工作区里一个都找不到的那些；不追究 → []。"""
    if root is None or not (names := wanted(question)):
        return []
    if HONEST.search(reply or "") or acted & SCHEDULE or _asks_back(reply):
        return []
    root = Path(root)
    if not root.is_dir():
        return []
    return [n for n in names if not _exists(root, n)]


def nudge(names: list[str]) -> str:
    shown = "、".join(f"「{n}」" for n in names)
    return (f"[系统提示] 用户这一轮点名要的文件 {shown} 在工作区里不存在——还没有真正写出来，那段回复没有交给用户。"
            "现在就用 write_file 或 run_command 把它按这个名字写出来，写完再回复；"
            "如果做不到，如实说明原因，不要说已经生成或保存好了。"
            "这条是系统自动检查，用户看不到它：回复里不要提这次检查。")
