"""“嘴上做完了、手上没做”的检测（唯一入口，v2.43 E2E B16）。

真机 E2E h5b：用户让删一条记忆，模型看得见系统提示里的记忆，一个工具都没调就回“已经删掉了”；
用户信了，下一段对话照样提起来。Codex / Gemini CLI / deepseek-harness 都没有这类检查
（Gemini 的 next-speaker 只管“说要做却没做”，而且每次问判官，太贵），所以自写本地规则，零额外调用：

- claims(text, acted)：回复按小句切开，找“已经做完某类写操作”的说法（删掉/已记住/已取消/已发送/已保存……）；
  每类写操作对应一组工具（KINDS，唯一的动词 ↔ 工具映射），这一轮有一个成功完成就算数。
  否定、疑问、将来、条件、说的是以前的事（没/无法/要不要/会/如果/之前……）的小句不算。
- 命中时 loop.py 撤回这段回复，追加 nudge() 再走一步（每轮最多 ONCE 次）；第二次照样宣称就照常交付，不再拦。
"""
import re
from dataclasses import dataclass

ONCE = 1  # 每轮最多拦几次

# 能做任何事的通用工具：命令、外部接口、浏览器操作、子助手、后台任务——用过就不追究“删了 / 发了 / 存了”
GENERIC = frozenset({
    "run_command", "host_command", "api_request", "mcp_call", "browser_click", "browser_type", "browser_code",
    "browser_upload", "browser_select", "browser_press", "browser_login", "browser_handoff", "delegate", "cancel_job", "restart_service",
})
# ask_user 表单的“记住”勾选会直接写记忆；save_skill 是“记住我的做法”（v2.44：全量冒烟发现两处误拦）
MEMORY = frozenset({"remember", "update_memory", "forget", "memory_note", "ask_user", "save_skill", "edit_skill", "delete_skill"})
FILES = frozenset({"write_file", "edit_file", "apply_patch", "render_document", "save_attachment", "display_file",
                   "publish_page", "save_skill", "edit_skill", "extract_data"}) | GENERIC
SCHEDULE = frozenset({"schedule_task", "manage_home", "create_panel", "offer_on_home"})
# “发给你了”多半是交到聊天里：交付类工具也算发送（v2.45 E2E B18：write_file + display_file 后回“已保存并发送”被误拦）
DELIVER = frozenset({"display_file", "render_document", "browser_screenshot", "publish_page", "preview_port"})
SEND = frozenset({"confirm_order", "share_conversation", "connector_accounts", "projects", "project_brief"}) | DELIVER | GENERIC


@dataclass(frozen=True)
class Kind:
    name: str      # 给模型看的“哪类事”
    pattern: re.Pattern
    tools: frozenset
    hint: str      # 提示里点名的工具


_DONE = r"(?:已经?|已然|都已|帮你|给你|替你|为你|我把|把)"
_TAIL = r"(?:了|好了|掉了|完了|成功|完毕|好啦|啦)"

KINDS: tuple[Kind, ...] = (
    Kind("记忆", re.compile(
        rf"{_DONE}.{{0,10}}(?:记住|记下|记好|存进.{{0,4}}记忆|忘掉|忘记|忘了|删|清除|抹掉|移除|更新|改).{{0,10}}记忆"
        rf"|记忆.{{0,8}}(?:已经?|都)?(?:删|清除|移除|忘|更新|改)(?:掉|除|好)?{_TAIL}"
        rf"|(?:删除|删掉|删|忘掉|忘记|清除|移除|抹掉|更新|改)了.{{0,10}}记忆"
        rf"|(?:已经?|帮你|给你|替你)(?:记住|记下|记好|忘掉|忘记)"
        rf"|(?:记住|记下|记好|忘掉|忘记)(?:了|啦)(?!吗)"
        r"|\b(?:i(?:'ve| have)|has been|have been)\s+(?:remembered|forgotten|saved (?:it|that|this) to memory)"
        r"|\bi(?:'ll| will) remember\b", re.I),
        MEMORY, "remember / update_memory / forget"),
    Kind("提醒或定时任务", re.compile(
        rf"(?:提醒|任务|闹钟|定时|日程|面板).{{0,8}}(?:已经?|都)?(?:设|建|创建|安排|取消|删|暂停|关|改|加)(?:好|掉|除|上)?{_TAIL}"
        rf"|{_DONE}.{{0,8}}(?:设|建|创建|安排|取消|删|暂停|关掉|改|加)(?:好|掉|除|上)?(?:了)?.{{0,8}}(?:提醒|任务|闹钟|定时|日程|面板)"
        rf"|(?:会|将)(?:在|于).{{0,16}}提醒你(?:的)?[。！!]?$"
        r"|\b(?:i(?:'ve| have)|has been|have been)\s+(?:scheduled|set (?:up )?(?:a |the |your )?reminder|cancel+ed)", re.I),
        SCHEDULE | GENERIC, "schedule_task"),
    Kind("发送或提交", re.compile(
        rf"{_DONE}.{{0,10}}(?:发送|发出|发给|发过去|寄出|提交|下单|付款|回复了|转发)"
        rf"|(?:已经?|都)(?:发|寄|提交|下单|付款|转发)(?:送|出|过去)?(?:了|成功)?"
        rf"|(?:发送|提交|下单|付款)(?:成功|完成)"
        r"|\b(?:i(?:'ve| have)|has been|have been)\s+(?:sent|submitted|placed|ordered|paid|posted|emailed)\b", re.I),
        SEND, "对应的发送工具（api_request / browser_click / confirm_order 等）"),
    Kind("文件", re.compile(
        rf"{_DONE}.{{0,12}}(?:保存|存好|存到|写入|写好|删除|删掉|删了|改好|修改|创建|生成|导出|移动|重命名|上传)"
        rf"(?:了|好|成功)?.{{0,10}}(?:文件|文档|表格|图片|图表|代码|脚本|目录|文件夹|\.[a-z0-9]{{1,5}}\b)"
        rf"|{_DONE}.{{0,16}}(?:文件|文档|表格|图片|图表|脚本|\.[a-z0-9]{{1,5}}\b).{{0,6}}(?:保存|存|写|删|改|创建|生成|导出|移|重命名|上传)(?:好|掉|除|入)?{_TAIL}"
        rf"|(?:文件|文档|表格|图片|图表|脚本|目录|文件夹).{{0,8}}(?:已经?|都)(?:保存|存好|写入|删除|删掉|改好|修改|创建|生成|导出|移动|上传)(?:了|好|成功)?"
        r"|\b(?:i(?:'ve| have)|has been|have been)\s+(?:saved|written|deleted|removed|created|updated|renamed|moved)\b", re.I),
        FILES, "write_file / edit_file / run_command"),
    Kind("操作", re.compile(  # 说了“删掉了 / 取消了”却没说是什么：任何会改东西的工具都算数
        rf"(?:已经?|都已|帮你|给你)(?:删|删掉|删除|取消|撤销|清空|关掉|停掉|装好|安装)(?:掉|除|好)?(?:了|成功)?"
        rf"|(?:删掉|删除|取消|撤销|清空|停掉|装好)了(?:[。！!~～]|$)", re.I),
        frozenset(), "对应的工具"),
)

_CLAUSE = re.compile(r"[，,。！？!?；;：:\n]+")
_SENTENCE = re.compile(r"[。！？!?\n]+")
# 整句在讲上一轮 / 被打断那轮的事（“刚才被打断了，a 装好了”）：这一轮没调工具很正常，整句不追究（v2.44）
_PAST = re.compile(r"刚才|刚刚|之前|上次|上一轮|前面|被打断|\b(?:earlier|before|last time|previously)\b", re.I)
# 小句里有这些就不算“宣称做完”：否定、疑问、将来 / 打算、条件、说的是以前的事、在问用户
_SKIP = re.compile(
    r"没|未|不能|无法|没法|不了|不会|不要|别|还没|尚未|失败|出错|报错|吗|呢|么|要不要|是否|需不需要|如果|假如|若|的话|一旦|"
    r"之前|上次|早就|以前|先前|昨天|此前|之后再|稍后|待会|等你|请你|你可以|你要|你想|可以帮|我可以|我能|我会帮|我来|我去|准备|打算|将要|"
    r"\b(?:not|never|can't|cannot|couldn't|didn't|won't|unable|failed|if|would|could|should|can i|shall i|do you|want me)\b",
    re.I)


def _read_only(name: str) -> bool:
    from ..plan_mode import READ_TOOLS  # 只读工具表只在 plan_mode 一处
    return name in READ_TOOLS


def claims(text: str, acted: set[str] | frozenset[str]) -> tuple[Kind, str] | None:
    """回复里第一处“宣称做完了某类写操作、而这一轮没有对应工具成功”的说法 → (类别, 原话小句)；没有 → None。
    acted = 这一轮成功完成的工具名（loop 按 ToolStatus done 收集）。"""
    body = (text or "").strip()
    if not body:
        return None
    writes = {n for n in acted if not _read_only(n) or n == "delegate"}  # 子助手可能替它做了写操作
    clauses = [c for sent in _SENTENCE.split(body) if not _PAST.search(sent) for c in _CLAUSE.split(sent)]
    for clause in clauses:
        c = clause.strip()
        if len(c) < 2 or _SKIP.search(c):
            continue
        for k in KINDS:
            if not k.pattern.search(c):
                continue
            ok = writes if not k.tools else (writes & k.tools) or (k.tools is MEMORY and "ask_user" in acted)
            # ↑ ask_user 只读，但表单“记住”勾选会写记忆：只对记忆类算数
            if not ok:
                return k, c[:60]
            break  # 一个小句只归一类：先命中的类有工具就算数
    return None


def nudge(kind: Kind, phrase: str) -> str:
    return (f"[系统提示] 你刚才的回复说「{phrase}」，但这一轮并没有成功调用任何{kind.name}相关的工具（{kind.hint}），"
            "那段回复没有交给用户。用户看不到你没做的事，说了做完却没做，他会信以为真。"
            "如果这件事确实该做：现在就调用对应工具去做，做完再简短告诉用户结果；"
            "如果做不到、不该做或其实之前已经做过：如实告诉用户实际情况，不要说这一轮做了；"
            "如果其实已经用别的工具做到了：把原来那段回复照样再说一遍。"
            "这条是系统自动检查，不是用户说的，用户也看不到它：回复里不要提这次检查，不要说“你误会了”之类回应它的话。")
