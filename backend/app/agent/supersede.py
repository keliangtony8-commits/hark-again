# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
#
# Ported from google-gemini/gemini-cli packages/core/src/agents/browser/snapshotSuperseder.ts (Apache-2.0), modified:
#   supersedeStaleSnapshots translated to Python over OpenAI-style messages.
# 修改：①快照不是独立工具，而是每个 browser_* 动作结果里的“页面：…可操作元素：…”段——只换掉这一段，
#       前面的说明（下载搬进了哪里、登录过期提示、会话名）原样保留，并留下标题 + 网址两行；
#       ②截图（vision.for_tool 补的图片消息）同理只留最新一张；③由 loop 记下位置，不必每步全量扫描。
"""一轮里旧的页面快照 / 截图 → 一句占位：模型只看到最新的那一份（唯一入口）。

每个浏览器动作都返回整页快照（元素清单 + 页面文字，常常上万字），一个十几步的网页任务
会把同一页的旧快照反复发给模型。旧快照只代表“当时的页面”，留着既费 token 又容易让模型
拿旧编号去点。loop 在每次调模型前调用 apply()：除最新一份外全部换成占位。
"""
from __future__ import annotations

import re

PLACEHOLDER = "[这份页面快照已过期：后面有更新的快照。要看当前页面就用 browser_read。]"
IMAGE_PLACEHOLDER = "（这里原有一张页面截图，已过期省略：后面有更新的截图。要看当前画面就用 browser_look。）"

# browser._render 的固定开头：一行“页面：标题”、一行网址、空行、“可操作元素：”
_HEAD = re.compile(r"^页面：[^\n]*\n[^\n]*\n\n可操作元素：", re.M)


def start(content: str) -> int | None:
    """快照段在工具结果里的起点；没有快照 → None。"""
    m = _HEAD.search(content) if isinstance(content, str) else None
    return m.start() if m else None


def stale(content: str) -> str:
    """把一份工具结果里的快照段换成占位（保留前面的说明和标题、网址两行）。已换过 / 没快照 → 原样。"""
    if PLACEHOLDER in content:
        return content
    at = start(content)
    if at is None:
        return content
    head = content[at:].split("\n", 2)[:2]
    return content[:at] + "\n".join(head) + "\n" + PLACEHOLDER


class Tracker:
    """loop 一轮里的记账：哪些消息带快照、哪些是浏览器截图。"""

    def __init__(self) -> None:
        self.snapshots: list[int] = []
        self.images: list[int] = []

    def note(self, messages: list[dict], index: int, tool: str) -> None:
        """刚追加的工具结果：浏览器工具且带快照 → 记下。"""
        if tool.startswith("browser_") and start(messages[index].get("content") or "") is not None:
            self.snapshots.append(index)

    def note_image(self, index: int) -> None:
        self.images.append(index)

    def apply(self, messages: list[dict]) -> int:
        """除最新一份外全部换成占位；返回这次换掉了几份（已换过的不算）。"""
        replaced = 0
        for i in self.snapshots[:-1]:
            old = messages[i].get("content") or ""
            new = stale(old)
            if new != old:
                messages[i] = {**messages[i], "content": new}
                replaced += 1
        for i in self.images[:-1]:
            if messages[i].get("content") != IMAGE_PLACEHOLDER:
                messages[i] = {**messages[i], "content": IMAGE_PLACEHOLDER}
                replaced += 1
        return replaced
