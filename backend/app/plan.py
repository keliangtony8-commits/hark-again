# Copyright (c) 2026 DeepSeek — MIT License.
# Ported from deepseek-ai/deepseek-harness packages/todo/tool-todo/src/index.ts (MIT), adapted:
#   整张清单替换（last-write-wins）、三态 pending | in_progress | completed、toTodoList 的校验
#   （去空白后非空、内容不能重复、单人干活时最多一项 in_progress）、按状态计数回给模型、
#   “清单只属于这一轮”（turn/start 清空 → 这里是：卡片属于这一轮的回复，下一轮重新写）。
# 嫁接：Gemini CLI write-todos.ts（Apache-2.0）——回给模型时把整张清单逐条列出（压缩/剪枝后模型仍知道计划），
#       空清单 = 清掉；Codex update_plan（Apache-2.0）——可选的 explanation（为什么改计划），卡片上显示一行。
# 我们加的：条数上限 / 每条长度上限（手机卡片放得下）、settled（这一轮结束后“进行中”不再闪）、
#       历史里的一行文字（用户回“继续”时模型知道上一轮的计划做到哪）。
"""一轮回复里的计划清单（唯一规则）：update_plan 工具校验、回给模型的文字、卡片块、历史文字、收尾。

块：{"type": "plan", "items": [{"content", "status"}], "explanation"?, "settled"?}
一条回复里只有一张（loop.MessageBuilder.SINGLETONS），每次更新原地换掉，位置停在第一次写的地方。
"""

STATUSES = ("pending", "in_progress", "completed")
ITEMS_MAX = 12
CONTENT_MAX = 80
EXPLANATION_MAX = 120

LABEL = {"pending": "待做", "in_progress": "进行中", "completed": "完成"}


class PlanError(ValueError):
    """参数不对：原因原样回给模型让它改（时间线记一步没成）。"""


def normalize(todos: object, explanation: object = "") -> tuple[list[dict], str]:
    """模型给的清单 → 规范清单（去空白）。不合规就抛 PlanError（deepseek toTodoList + Gemini 的结构校验）。"""
    if not isinstance(todos, list):
        raise PlanError("todos 要是一个数组（完整清单）")
    if len(todos) > ITEMS_MAX:
        raise PlanError(f"步骤太多（{len(todos)} 条）：合并成不超过 {ITEMS_MAX} 条大步骤")
    out, seen, active = [], set(), 0
    for item in todos:
        if not isinstance(item, dict):
            raise PlanError("每一步要是 {content, status} 对象")
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            raise PlanError("每一步的 content 不能为空")
        content = " ".join(content.split())
        if len(content) > CONTENT_MAX:
            raise PlanError(f"「{content[:20]}…」太长：每一步写成一句短话（不超过 {CONTENT_MAX} 字）")
        if content in seen:
            raise PlanError(f"步骤重复：「{content}」")
        seen.add(content)
        status = item.get("status")
        if status not in STATUSES:
            raise PlanError(f"status 只能是 {' / '.join(STATUSES)}")
        active += status == "in_progress"
        out.append({"content": content, "status": status})
    if active > 1:
        raise PlanError(f"同一时间只能有一步 in_progress（现在有 {active} 步）")
    note = " ".join(explanation.split())[:EXPLANATION_MAX] if isinstance(explanation, str) else ""
    return out, note


def counts(items: list[dict]) -> dict[str, int]:
    return {s: sum(i["status"] == s for i in items) for s in STATUSES}


def for_model(items: list[dict]) -> str:
    """回给模型：计数 + 整张清单（Gemini 逐条回显；deepseek 计数）。"""
    if not items:
        return "计划已清空。"
    c = counts(items)
    lines = "\n".join(f"{n}. [{i['status']}] {i['content']}" for n, i in enumerate(items, 1))
    tail = "全部完成，可以收尾回复用户了。" if c["completed"] == len(items) else \
        "做完一步就立刻标 completed，并把下一步标 in_progress。"
    return f"计划已更新：完成 {c['completed']} / 共 {len(items)}，进行中 {c['in_progress']}。\n{lines}\n{tail}"


def block(items: list[dict], explanation: str = "") -> dict:
    b: dict = {"type": "plan", "items": items}
    if explanation:
        b["explanation"] = explanation
    return b


def settle(b: dict) -> dict:
    """这一轮结束（说完或被停）：卡片定格。没写完的步骤保持原状态，客户端不再闪“进行中”。"""
    return {**b, "settled": True} if b.get("type") == "plan" and not b.get("settled") else b


def history_text(b: dict) -> str:
    """喂回模型的历史一行：用户下一轮说“继续”时，模型知道上一轮的计划做到了哪。"""
    items = b.get("items") or []
    if not items:
        return ""
    done = sum(i.get("status") == "completed" for i in items)
    steps = "；".join(f"{i.get('content', '')}（{LABEL.get(i.get('status'), '')}）" for i in items)
    return f"[计划 {done}/{len(items)}：{steps}]"
