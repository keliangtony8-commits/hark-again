"""模型把工具调用“写成了文字”（没走 function call）：唯一规则（v2.54，E2E 第十轮 B26）。

起因（l1）：step-3.7-flash 改好简历后，回复正文是
    <display_file>\n  <args>\n    <paths>["/workspace/简历_已改.docx"]</paths>\n  </args>\n</display_file>
用户看到一段标签，文件也没交出去。别的模型也会这样写 <tool_call>{...}</tool_call>、<function=name>、<invoke name=…>。
refs：Codex / Gemini / deepseek-harness 都假设供应商的 tool_calls 可靠，没有这道检查 → 自己的规则。

做法：只认“标签名 = 一个真实工具名”或通用的 tool_call / function_call / invoke / function= 标签，且里面带参数样子
（<args> / <parameter / <arguments / JSON 花括号）——普通回复里提到 `display_file` 这个词、写 HTML 示例不算
（代码块里的不算）。认出 → loop 撤回这段（不交付），提醒模型用真正的工具调用重做，一轮最多一次（ONCE）。
v2.87 补（用户 10-14 19:00 截图：深度档 step-5 把 show_draft 写成 <tool_call><function=show_draft><parameter=body>…，
提醒一次后它又照写，标签原样交给了用户）：
  · parse —— 两种“格式本身无歧义”的写法直接还原成真调用（零额外模型调用，也不用提醒）：
      Qwen3-Coder / Step 的 XML：<function=名><parameter=键>值</parameter>…</function>（外面可有 <tool_call>）；
      Hermes 的 JSON：<tool_call>{"name": 名, "arguments": {…}}</tool_call>。
    名字必须是真实可用的工具；参数按该工具 JSON Schema：string 原样，其余类型先试 JSON。认不全就不还原（走原来的提醒）。
    格式依据 Qwen3-Coder 聊天模板；思路参考 vLLM qwen3coder_tool_parser（Apache-2.0），代码为本项目自写。
  · scrub —— 定稿前最后一道（reply_fix 调）：还残留的工具调用标签整段去掉，永远不把标签交给用户。
其余写法（<display_file><args>…）仍然不猜，走提醒。"""
import json
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


_FN = re.compile(r"<function=([\w.-]+)>(.*?)(?:</function>|$)", re.S)
_PARAM = re.compile(r"<parameter\s*(?:=|name\s*=?)?\s*[\"']?([A-Za-z_][\w-]*)[\"']?\s*>(.*?)(?=</parameter>|<parameter\b|</function>|$)", re.S)
_HERMES = re.compile(r"<tool_call>\s*(\{.*?\})\s*(?:</tool_call>|$)", re.S)
_BLOCK = re.compile(r"<tool_call>.*?(?:</tool_call>|$)|<function=[\w.-]+>.*?(?:</function>|$)", re.S)


def _value(raw: str, schema: dict):
    v = raw.strip(" \t")
    v = v[1:] if v.startswith("\n") else v
    v = v[:-1] if v.endswith("\n") else v
    if (schema or {}).get("type", "string") == "string":
        return v.strip(" \t")
    try:
        return json.loads(v.strip())
    except ValueError:
        return v.strip()


def parse(said: str, tools: dict) -> list[tuple[str, dict]] | None:
    """tools = {工具名: 参数 JSON Schema}。整段能无歧义地还原 → [(名, 参数)]；否则 None。"""
    text = _FENCE.sub("", said or "")
    calls: list[tuple[str, dict]] = []
    if "<function=" in text:
        for m in _FN.finditer(text):
            name = m.group(1)
            if name not in tools:
                return None
            props = (tools[name] or {}).get("properties") or {}
            args = {k: _value(v, props.get(k) or {}) for k, v in _PARAM.findall(m.group(2))}
            if not args and (tools[name] or {}).get("required"):
                return None
            calls.append((name, args))
    elif "<tool_call>" in text:
        for m in _HERMES.finditer(text):
            try:
                obj = json.loads(m.group(1))
            except ValueError:
                return None
            name, args = obj.get("name"), obj.get("arguments", obj.get("parameters", {}))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    return None
            if name not in tools or not isinstance(args, dict):
                return None
            calls.append((name, args))
    return calls or None


def prose(said: str) -> str:
    """去掉工具调用标签后剩下的正文（还原成真调用时，模型写在标签前后的话照常保留）。"""
    return re.sub(r"\n{3,}", "\n\n", _BLOCK.sub("", said or "")).strip()


def scrub(reply: str) -> tuple[str, list[tuple[str, str]]]:
    """reply_fix 规则：定稿里还残留工具调用标签（found 认得出的那种）→ 整段去掉。"""
    names = set(re.findall(r"<([a-z][a-z0-9_]{2,63})>\s*<(?:args|arguments|parameters)>", _FENCE.sub("", reply or "")))
    if not found(reply, names):
        return reply, []
    text = prose(reply)
    for n in names:  # <display_file><args>…</display_file> 这种写法也去掉
        text = re.sub(rf"<{n}>\s*<(?:args|arguments|parameters)>.*?(?:</{n}>|$)", "", text, flags=re.S).strip()
    if not text:
        text = "抱歉，这一步没有执行成功。请再发送一次，我会重新处理。"
    return text, [("tool_markup", "去掉了回复里残留的工具调用标签")]
