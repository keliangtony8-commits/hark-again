"""定稿回复的“纯文本就地修正”串联（唯一入口，v2.71）。

loop.py 在一轮最终接受回复时只调这里一次；每条规则都是确定性的、零模型调用，按顺序作用在同一段文字上：
  1. weekday_check —— 日期配的星期几按日历改正（v2.70 B37）；
  2. md_table      —— Markdown 表格列数对齐，免得多出的格子被渲染器丢掉（v2.71）。
新增同类规则（不需要问模型就能确定改对的）加在 RULES 里，不要在 loop.py 里再开分支。
"""
from __future__ import annotations

from . import md_table, weekday_check


def polish(reply: str, question: str) -> tuple[str, list[tuple[str, str]]]:
    text, changes = weekday_check.fix(reply, question)
    text, more = md_table.fix(text)
    return text, changes + more
