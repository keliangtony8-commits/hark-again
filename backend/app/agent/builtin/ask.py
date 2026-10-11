"""ask_user：任务做到一半缺只有用户知道的信息（收货地址、几位、选哪个）时，在聊天里弹一张表单卡问他
（对标 Hark 在任务里用表单问用户要细节）。复用 v0.83 的表单卡通道（Tool.form → loop._ask_form → ws form.reply），
purpose=info：用户填的内容交给助手，提交后回显在卡片上（loop.form_answers），进历史，下一轮也记得。
- 无人值守（定时任务、后台运行）没人能答：不弹卡，告诉模型按已知信息做、在结果里说明缺什么。
- 不收密码 / 验证码（那是 browser_login / browser_code 的事，值不给模型看）。
- 勾了“记住”的答案存进长期记忆（memory_store.save，同义覆盖），附记忆卡。"""
from ... import memory_store
from ..approvals import FormReply
from ..tools import ToolContext, ToolResult, nobody, tool

KINDS = ["text", "email", "phone", "multiline"]
MAX_FIELDS, MAX_OPTIONS = 6, 6
TITLE_MAX, NOTE_MAX, LABEL_MAX, OPTION_MAX, ACTION_MAX = 40, 120, 24, 24, 8


def ask_card(args: dict) -> dict:
    """模型参数 → 表单卡（blocks.FormBlock 的样子，不含 id/state）。参数不对抛 ValueError（中文，给模型看）。
    字段名由这里编（q1…q6），模型只管写问题，免得名字不合规。"""
    title = (args.get("question") or "").strip()[:TITLE_MAX]
    if not title:
        raise ValueError("缺 question（卡片标题，一句话问什么）")
    fields = []
    for f in (args.get("fields") or [])[:MAX_FIELDS]:
        label = str((f or {}).get("label") or "").strip()[:LABEL_MAX]
        if not label:
            continue
        kind = f.get("kind") if f.get("kind") in KINDS else "text"
        options = [o for o in (str(x).strip()[:OPTION_MAX] for x in f.get("options") or []) if o][:MAX_OPTIONS]
        value = str(f.get("value") or "").strip() or None
        fields.append({"name": f"q{len(fields) + 1}", "label": label, "kind": kind, "optional": bool(f.get("optional")),
                       **({"options": options} if options else {}), **({"value": value} if value else {})})
    if not fields:
        raise ValueError("fields 至少要有一个带 label 的输入框")
    note = (args.get("note") or "").strip()[:NOTE_MAX] or None
    action = (args.get("action") or "").strip()[:ACTION_MAX] or "告诉助手"
    return {"type": "form", "purpose": "info", "title": title, "fields": fields, "action": action,
            "remember": bool(args.get("remember")), **({"note": note} if note else {})}


async def _form(ctx: ToolContext, args: dict) -> dict | None:
    if ctx.ask is nobody:  # 没人能答就不弹卡
        return None
    try:
        return ask_card(args)
    except ValueError:
        return None  # run 里再报参数错误


@tool("ask_user", "正在问你",
      "做事缺只有用户知道的具体信息（收货地址、电话、人数、在几个选项里挑一个）时调用：在聊天里弹一张表单卡，"
      "用户填完你就拿到答案继续做。一次把要问的都放进 fields（最多 6 个）；有明确候选就给 options 让他点选。"
      "简单的是非题或闲聊直接在回复里问，不用它；绝不用它要密码或验证码（用 browser_login / browser_code）。"
      "remember=true 表示这些是长期有用的事实（如收货地址），用户可勾选存进记忆。",
      {"type": "object", "properties": {
          "question": {"type": "string", "description": "卡片标题，一句话，如：送到哪里？"},
          "note": {"type": "string", "description": "可选，为什么要问，一句话"},
          "fields": {"type": "array", "items": {"type": "object", "properties": {
              "label": {"type": "string", "description": "输入框的名字，如：收货地址"},
              "kind": {"type": "string", "enum": KINDS},
              "options": {"type": "array", "items": {"type": "string"}, "description": "可点选的候选"},
              "optional": {"type": "boolean"},
              "value": {"type": "string", "description": "已知的默认值"}},
              "required": ["label"]}},
          "remember": {"type": "boolean"},
          "action": {"type": "string", "description": "按钮上的字，≤8 字，默认“告诉助手”"}},
       "required": ["question", "fields"]}, form=_form)
async def ask_user(ctx: ToolContext, question: str = "", fields: list | None = None, note: str = "",
                   remember: bool = False, action: str = "", form: FormReply | None = None) -> ToolResult:
    if form is None:
        if ctx.ask is nobody:
            return ToolResult("现在是后台运行，没人能回答。按已知信息先做，做不了的在结果里说清楚缺什么，"
                              "要用户拍板的可以用 offer_on_home 放一张建议卡。")
        try:
            ask_card({"question": question, "fields": fields})
        except ValueError as e:
            return ToolResult(f"参数有误：{e}")
        return ToolResult("没问成。")
    spec = ask_card({"question": question, "fields": fields})
    answered = {f["label"]: form.values.get(f["name"], "").strip() for f in spec["fields"]}
    lines = [f"{label}：{value}" for label, value in answered.items() if value]
    skipped = [label for label, value in answered.items() if not value]
    content = "用户在表单上回答了（卡片上已显示，不用复述）：\n" + ("\n".join(lines) or "（全都空着）")
    if skipped:
        content += f"\n没填：{'、'.join(skipped)}"
    blocks = []
    if form.remember and remember and lines:
        saved = [await memory_store.save(ctx.db, line, "profile") for line in lines]
        blocks.append(memory_store.card("saved", [(m, p if p != m.content else None) for m, p in saved]))
        content += "\n已按用户的选择记进长期记忆。"
    return ToolResult(content, blocks)
