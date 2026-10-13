"""模型把工具调用“写成了文字”（没走 function call）：唯一规则（v2.54，E2E 第十轮 B26）。

起因（l1）：step-3.7-flash 改好简历后，回复正文是
    <display_file>\n  <args>\n    <paths>["/workspace/简历_已改.docx"]</paths>\n  </args>\n</display_file>
用户看到一段标签，文件也没交出去。别的模型也会这样写 <tool_call>{...}</tool_call>、<function=name>、<invoke name=…>。
refs：Codex / Gemini / deepseek-harness 都假设供应商的 tool_calls 可靠，没有这道检查 → 自己的规则。

做法：只认“标签名 = 一个真实工具名”或通用的 tool_call / function_call / invoke / function= 标签，且里面带参数样子
（<args> / <parameter / <arguments / JSON 花括号）——普通回复里提到 `display_file` 这个词、写 HTML 示例不算
（代码块里的不算）。认出 → loop 撤回这段（不交付），提醒模型用真正的工具调用重做，一轮最多一次（ONCE）。
不尝试把文字解析成调用：参数格式五花八门，猜错了比不做更糟。"""
import re

ONCE = 1

_FENCE = re.compile(r"```.*?(?:```|$)", re.S)
_GENERIC = re.compile(r"<(?:tool_call|function_call|tool_use|invoke)\b[^>]*>|<function=[\w.-]+>", re.I)
_ARGS = re.compile(r"<args>|<arguments>|<parameter\b|<parameters>|\{\s*\"")


def found(said: str, tool_names) -> str | None:
    """回复里写成文字的工具调用：返回工具名（通用标签认不出名字 → "工具"）；没有 → None。"""
    text = _FENCE.sub("", said or "")
    if "<" not in text:
        return None
    names = set(tool_names)
    for m in re.finditer(r"<([a-z][a-z0-9_]{2,63})>", text):
        name = m.group(1)
        if name in names:
            rest = text[m.end():]
            end = rest.find(f"</{name}>")
            body = rest if end < 0 else rest[:end]
            if _ARGS.search(body):
                return name
    g = _GENERIC.search(text)
    if g and _ARGS.search(text[g.start():]):
        n = re.search(r"(?:name=[\"']?|function=|\"name\"\s*:\s*\")([\w.-]+)", text[g.start():g.start() + 400])
        return n.group(1) if n and n.group(1) in names else "工具"
    return None


def nudge(name: str) -> str:
    what = "工具" if name == "工具" else f" {name} "
    return (f"[系统提示] 你刚才把{what}调用写成了回复里的文字（标签 / JSON），它没有执行，那段回复也没有交给用户。"
            "现在用真正的工具调用（function call）去做；回复正文里不要再写这些标签。"
            "这条是系统自动检查，用户看不到它：回复里不要提这次检查。")
