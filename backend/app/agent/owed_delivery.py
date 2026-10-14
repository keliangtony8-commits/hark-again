"""“用户要你把文件发给他，你改好了却没交付”的检测（唯一入口，v2.69 E2E B36）。

真机 E2E r8：用户发来 GBK 编码的 txt，“帮我弄成正常的再发我”；模型用命令解码、把内容贴在回复里，
说“已修复”，最后一句“如果你要，我也可以另存成 UTF-8 版本发你”——用户明确要了，文件却没给。
claimed_action 管不到（run_command 是通用工具，“已修复”算数）。Codex / Gemini CLI / deepseek-harness
都是开发者工具，产物就在本地磁盘，没有“交到聊天里”这一步，所以自写本地规则，零额外调用：

- owed(question, reply, acted)：同时满足才算“欠一份交付”——
  ① 用户这一轮要文件回来（ASK：发我 / 发给我 / 传给我 / 发回来 / 导出给我 / send it back…，且没说“先别发”）；
  ② 说的是文件（FILEISH：文件 / 表格 / txt / 附件…，或这一轮存过附件 save_attachment）；
  ③ 这一轮动过文件（MADE：写 / 改 / 跑命令 / 抽取）——只读了文件、在聊天里总结的不算，免得逼它把总结做成文件；
  ④ 没有任何交付或另有去向的工具成功（claimed_action.DELIVER + 定时/发送类：每天发我 = 建任务）；
  ⑤ 回复没有如实说做不到（HONEST：失败 / 无法 / 做不到…）。
- 命中时 loop.py 撤回这段回复，追加 nudge() 再走一步（每轮最多 ONCE 次）。
"""
import re

from .claimed_action import DELIVER, SCHEDULE, SEND

ONCE = 1

ASK = re.compile(
    r"(?:再|重新|直接|然后|顺便)?(?:发|传|丢|甩)(?:一份|一下|个)?(?:给)?我(?!们)"
    r"|给我(?:发|传)(?:回|过)?"
    r"|发(?:回|过)来|传(?:回|过)来"
    r"|(?:导出|打包|生成|做|转)(?:成)?(?:一份|一个|个)?(?:\S{0,8})?给我"
    r"|\bsend (?:it|them|me|back|the file)|\bgive me (?:the|a) (?:file|copy)", re.I)
_NO_SEND = re.compile(r"(?:别|不用|不要|先不|不必|无需)(?:.{0,4})(?:发|传)|don't send", re.I)
FILEISH = re.compile(
    r"文件|表格|文档|附件|图片|照片|图表|压缩包|报告|简历|版本|excel|word|pdf|ppt|zip"
    r"|\.[a-z0-9]{1,5}\b|\b(?:txt|csv|xlsx?|docx?|png|jpe?g|json|md)\b", re.I)
MADE = frozenset({"write_file", "edit_file", "apply_patch", "run_command", "host_command", "extract_data",
                  "render_document", "browser_code"})
ELSEWHERE = DELIVER | SCHEDULE | (SEND - MADE)  # 交付过 / 发到外部（邮件接口、MCP、网页上传）/ 建了定时任务：文件有别的去向，不追究
HONEST = re.compile(r"失败|无法|做不到|没能|没法|不能|出错|报错|找不到|不支持|\b(?:can't|cannot|unable|failed|couldn't)\b", re.I)


def owed(question: str, reply: str, acted: set[str] | frozenset[str]) -> str | None:
    """这一轮欠用户一份文件交付 → 用户原话里要文件的那几个字；不欠 → None。"""
    q = (question or "").strip()
    if not q or not (m := ASK.search(q)) or _NO_SEND.search(q):
        return None
    if not (FILEISH.search(q) or "save_attachment" in acted):
        return None
    if not (acted & MADE) or acted & ELSEWHERE:
        return None
    if HONEST.search(reply or ""):
        return None
    return m.group(0)


def nudge(phrase: str) -> str:
    return (f"[系统提示] 用户这一轮要你把文件交给他（原话「{phrase}」），这一轮你处理了文件，但还没有用 display_file 把成品交到聊天里，"
            "那段回复没有交给用户。现在就用 display_file 交付成品文件（改好的文件存成新文件名更稳，别覆盖原件），"
            "再一两句话说明是什么；不要再问“要不要发你”。如果用户其实只要你在聊天里说结果、不需要文件，就把原来那段回复照样再说一遍；"
            "如果做不到，如实说明原因。这条是系统自动检查，用户看不到它：回复里不要提这次检查。")
