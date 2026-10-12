# Ported from deepseek-harness/packages/fs/fs-observation-policy/src/index.ts (MIT), adapted:
# 同一套“看过才许覆盖、看过之后变了就拒”的规则，换成按对话记账、用 (mtime_ns, size, inode) 当版本。
"""工作区文件“看过的版本”记账：防止助手覆盖它没看过、或看过之后已被别人改过的文件。唯一规则在这里。

为什么要：云端电脑上同一个文件可能被后台任务、用户上传/保存、另一段对话、助手自己的 run_command 改掉；
助手凭旧印象 write_file 整篇覆盖，就把别人的改动冲没了。deepseek-harness 的做法（本模块的底子）：
- 每个“主人”（这里 = 一段对话 c:<id>，定时任务 t:<id>）各记各的：路径 → 看到时的版本 / 确认不存在。
- read_file 读到（哪怕只读一段）= 看过这个版本；读到不存在 = 确认不存在。write_file / edit_file 成功后记新版本，
  下一次改不用重读。
- write_file 覆盖已存在的文件：没看过 → 拒（先 read_file）；看过但版本变了 → 拒（先重读）；
  当时确认不存在、现在却有了（别人刚建的）→ 拒。新建文件、看过且没变 → 放行。
- 主人之间互不授权：A 对话读过不等于 B 对话能覆盖。
取舍（对比写在 docs/core-research.md）：
- 不照搬 “edit_file 必须先读”：我们的 edit_file 要求 old_string 一字不差且唯一，本身就证明助手知道那段原文
  （可能来自 grep / 命令输出），强制再读一遍只是多花 token。但看过的版本已经变了 → 照样拒，让它重读再改。
- 没有主人（内部直接调用、测试）→ 不管，和改造前一样。
- 只记在内存（deepseek 也不落库）：后端重启后要重读一次才能覆盖。上限 OWNERS_MAX 个主人、每个 PATHS_MAX 条。
"""
import os
from pathlib import Path

OWNERS_MAX = 200
PATHS_MAX = 500
ABSENT = "absent"

Version = tuple[int, int, int]  # (st_mtime_ns, st_size, st_ino)

_seen: dict[str, dict[str, Version | str]] = {}


def owner_of(conversation_id: str | None, task_id: str | None) -> str | None:
    """定时任务按任务记（跨次运行也算同一个主人），聊天按对话；都没有 → None（不管）。"""
    if task_id:
        return f"t:{task_id}"
    return f"c:{conversation_id}" if conversation_id else None


def version(p: Path) -> Version | None:
    try:
        st = os.stat(p)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def _key(p: Path) -> str:
    return str(p.resolve())


def observe(owner: str | None, p: Path) -> None:
    """记下此刻看到的样子：存在 → 版本；不存在 → 确认不存在。写/改成功之后也调用它。"""
    if owner is None:
        return
    book = _seen.get(owner)
    if book is None:
        if len(_seen) >= OWNERS_MAX:  # 只防无限增长：丢最早的主人
            _seen.pop(next(iter(_seen)))
        book = _seen[owner] = {}
    k = _key(p)
    book.pop(k, None)  # 重新插到最后，满了丢最早看的
    if len(book) >= PATHS_MAX:
        book.pop(next(iter(book)))
    book[k] = version(p) or ABSENT


def prior(owner: str | None, p: Path) -> Version | str | None:
    """这个主人上次看到的：版本 / ABSENT / None（没看过）。"""
    return None if owner is None else _seen.get(owner, {}).get(_key(p))


class Refused(Exception):
    """不许写：消息给模型（说清怎么办），short 给时间线那一步当原因。"""

    def __init__(self, message: str, short: str):
        super().__init__(message)
        self.short = short


def _stale(path: str) -> Refused:
    return Refused(f"{path} 在你上次读过之后被改过了（可能是后台任务、命令或用户改的），没有动它。"
                   "先 read_file 看看现在的内容再改，免得冲掉别人的改动。", "读过之后文件被改过")


def check_write(owner: str | None, p: Path, path: str) -> None:
    """write_file 整篇写之前：不该覆盖就抛 Refused。"""
    if owner is None:
        return
    now, before = version(p), prior(owner, p)
    if now is None:
        return  # 新建；之前看过、后来被删了也允许重建（没有东西会被冲掉）
    if before is None:
        raise Refused(f"{path} 已经存在，而这段对话还没读过它，没有覆盖。先 read_file 看一眼（读开头一段也行）"
                      "确认可以整篇替换；只改一小段用 edit_file；要保留原文件就换个文件名。", "没读过就要覆盖")
    if before == ABSENT:
        raise Refused(f"{path} 你上次看时还不存在，现在已经有了（可能刚被别人建的），没有覆盖。"
                      "先 read_file 看看内容再决定。", "文件刚被别人建了")
    if before != now:
        raise _stale(path)


def check_edit(owner: str | None, p: Path, path: str) -> None:
    """edit_file 之前：没看过照常（old_string 一字不差已证明认得原文）；看过但已变 → 抛 Refused。"""
    before = prior(owner, p)
    if before is None or before == ABSENT:
        return
    if before != version(p):
        raise _stale(path)


def forget(owner: str) -> None:
    _seen.pop(owner, None)
