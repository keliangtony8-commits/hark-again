"""项目档案：每个项目一份活文档（目标、已定的决定、重要文件、固定做法、进行中的事）。

和“项目规则”的分工：规则 = 用户给的几句硬要求；档案 = 用户和助手共同维护的长期记忆，
助手在项目里学到新东西就用 project_brief 工具改它，对话被压缩、换新对话都不丢。
谁改的、何时改的记在 brief_by / brief_updated_at，客户端据此显示“助手更新于…/你编辑于…”。
"""
from datetime import datetime, timezone

from fastapi import HTTPException

from .models import Project

BRIEF_MAX = 8000          # 档案最长多少字（PATCH 和工具都按它截断/拒绝）
PROMPT_CHARS = 6000       # 注入系统提示的上限：超出部分截掉并提示模型精简

GUIDE = ("这个项目有一份「项目档案」，是项目的长期记忆：目标与范围、已经定下的决定和原因、重要文件、固定做法（遇到 X 就做 Y）、进行中/卡住的事。"
         "开工前先按它办；目标、决定、文件或做法有变化时，当轮就用 project_brief 工具更新（edit 小改，write 重写）。"
         "只写长期有用的内核，不写一次性的细节；保持简短，按小标题组织。")


def _stamp(p: Project, by: str) -> None:
    p.brief_by, p.brief_updated_at = by, datetime.now(timezone.utc)


def on_patch(p: Project, changes: dict) -> None:
    """PATCH /api/projects/{id} 的钩子：用户改了档案正文才盖“你编辑于”的戳（内容没变不算）。"""
    if "brief" not in changes:
        return
    text = (changes["brief"] or "").strip()
    if text == (p.brief or ""):
        changes.pop("brief")
        return
    changes["brief"] = text
    _stamp(p, "user")


def write(p: Project, text: str) -> str | None:
    """整份重写。返回错误文本（给模型看），成功返回 None。"""
    text = (text or "").strip()
    if len(text) > BRIEF_MAX:
        return f"档案太长（{len(text)} 字，上限 {BRIEF_MAX}）：请精简后再写。"
    p.brief = text
    _stamp(p, "assistant")
    return None


def edit(p: Project, find: str, replace: str) -> str | None:
    """精确查找替换：find 必须在档案里恰好出现一次（和技能编辑同样的规矩，避免改错地方）。"""
    cur = p.brief or ""
    if not find:
        return "find 不能为空；要追加内容请把末尾一段原文作为 find，或用 write 重写。"
    n = cur.count(find)
    if n == 0:
        return "档案里没有这段原文：先 read 看当前内容，再精确复制要改的部分。"
    if n > 1:
        return f"这段原文出现了 {n} 次：多带一点上下文让它唯一。"
    return write(p, cur.replace(find, replace, 1))


def prompt_section(p: Project) -> str:
    body = (p.brief or "").strip()
    if not body:
        return GUIDE + "\n项目档案目前是空的：了解到项目的目标后，先用 project_brief write 建一份。"
    if len(body) > PROMPT_CHARS:
        body = body[:PROMPT_CHARS] + f"\n…（档案超过 {PROMPT_CHARS} 字，后面被截断了：请把它精简一下）"
    return GUIDE + "\n项目档案：\n<<<\n" + body + "\n>>>"
