# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
#
# Ported from google-gemini/gemini-cli packages/core/src/agents/browser/snapshotSuperseder.ts (Apache-2.0), modified:
#   supersedeStaleSnapshots translated to Python over OpenAI-style messages.
# 修改：①快照不是独立工具，而是每个 browser_* 动作结果里的“页面：…可操作元素：…”段——只换掉这一段，
#       前面的说明（下载搬进了哪里、登录过期提示、会话名）原样保留，并留下标题 + 网址两行；
#       ②截图（vision.for_tool 补的图片消息）同理只留最新一张；③由 loop 记下位置，不必每步全量扫描；
#       ④（v2.48，真机 E2E j1 比价）别的网址的旧快照不整段抹掉：元素清单照删（编号已失效），页面文字留一段节选
#         （TEXT_KEEP 字，每个网址只留最近那份）——多页比较时先看过的页上的价格、库存不能跟着“过期”丢掉。
"""一轮里旧的页面快照 / 截图 → 一句占位：模型只看到最新的那一份（唯一入口）。

每个浏览器动作都返回整页快照（元素清单 + 页面文字，常常上万字），一个十几步的网页任务
会把同一页的旧快照反复发给模型。旧快照只代表“当时的页面”，留着既费 token 又容易让模型
拿旧编号去点。loop 在每次调模型前调用 apply()：除最新一份外全部换成占位。
"""
from __future__ import annotations

import re

PLACEHOLDER = "[这份页面快照已过期：后面有更新的快照。要看当前页面就用 browser_read。]"
PLACEHOLDER_KEPT = "[这份页面快照已过期：元素编号已失效，不能再点。当时这页上的文字节选如下；要看当前页面就用 browser_read。]"
TEXT_KEEP = 600  # 别的网址的旧快照留下的页面文字节选（字）
_TEXT = "\n\n页面文字：\n"
IMAGE_PLACEHOLDER = "（这里原有一张页面截图，已过期省略：后面有更新的截图。要看当前画面就用 browser_look。）"

# browser._render 的固定开头：一行“页面：标题”、一行网址、空行、“可操作元素：”
_HEAD = re.compile(r"^页面：[^\n]*\n[^\n]*\n\n可操作元素：", re.M)


def start(content: str) -> int | None:
    """快照段在工具结果里的起点；没有快照 → None。"""
    m = _HEAD.search(content) if isinstance(content, str) else None
    return m.start() if m else None


def url(content: str) -> str:
    """快照段里的网址（“页面：标题”下一行）；没有快照 → 空串。"""
    at = start(content)
    return content[at:].split("\n", 2)[1].strip() if at is not None else ""


def stale(content: str, keep_text: bool = False) -> str:
    """把一份工具结果里的快照段换成占位（保留前面的说明和标题、网址两行）。已换过 / 没快照 → 原样。
    keep_text：再留页面文字的前 TEXT_KEEP 字（压成一行）——用于别的网址的旧快照。"""
    if PLACEHOLDER in content or PLACEHOLDER_KEPT in content:
        return content
    at = start(content)
    if at is None:
        return content
    head = "\n".join(content[at:].split("\n", 2)[:2])
    text = content[at:].split(_TEXT, 1)[1] if keep_text and _TEXT in content[at:] else ""
    text = " ".join(text.split())
    if not text:
        return content[:at] + head + "\n" + PLACEHOLDER
    cut = text if len(text) <= TEXT_KEEP else text[:TEXT_KEEP - 1] + "…"
    return content[:at] + head + "\n" + PLACEHOLDER_KEPT + "\n" + cut


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

    def splice(self, start: int, end: int) -> None:
        """compact.py 把 [start, end) 换成了一条检查点：区间里的记录作废，后面的下标前移。"""
        def move(xs: list[int]) -> list[int]:
            return [i if i < start else i - (end - start) + 1 for i in xs if not start <= i < end]
        self.snapshots, self.images = move(self.snapshots), move(self.images)

    def apply(self, messages: list[dict]) -> int:
        """除最新一份外全部换成占位；返回这次换掉了几份（已换过的不算）。"""
        replaced = 0
        latest = url(messages[self.snapshots[-1]].get("content") or "") if self.snapshots else ""
        kept: set[str] = {latest}  # 每个网址只留最近一份节选；和最新快照同网址的不留（最新的里就有）
        keep: set[int] = set()
        for i in reversed(self.snapshots[:-1]):
            u = url(messages[i].get("content") or "")
            if u and u not in kept:
                kept.add(u)
                keep.add(i)
        for i in self.snapshots[:-1]:
            old = messages[i].get("content") or ""
            new = stale(old, i in keep)
            if new != old:
                messages[i] = {**messages[i], "content": new}
                replaced += 1
        for i in self.images[:-1]:
            if messages[i].get("content") != IMAGE_PLACEHOLDER:
                messages[i] = {**messages[i], "content": IMAGE_PLACEHOLDER}
                replaced += 1
        return replaced
