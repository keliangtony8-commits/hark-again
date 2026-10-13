# Copyright 2025 OpenAI
# SPDX-License-Identifier: Apache-2.0
# 目录的预算分配 Ported from openai/codex codex-rs/ext/skills/src/render.rs (Apache-2.0), modified:
#   allocate_skill_lines 的三级退让（全文放得下 → 全放；只放名字放得下 → 描述按字轮流分配剩余预算；
#   都放不下 → 只放名字到预算为止，其余省略）照搬；成本按字数算（不算字节 / token），省略时那句提示改成指向 skill_search。
"""技能目录与技能搜索：唯一规则（v2.46 大脑 (bd)，对标 Hark 的 skill search / list：技能多了照样找得到、提示不膨胀）。

两个出口共用这一处：
- 系统提示里的“可用技能”目录（agent/context.py）——prompt_section()；
- 模型的 skill_search 工具（agent/builtin/skills.py）——search()。

规则：
- 目录每行 `- id：名称——描述`，描述压成一行、超过 DESC_MAX 字截断加“…”（Codex interface.rs 给描述也设了上限）。
- 目录按技能库的固定顺序（内置在前、自己的在后，skills_store.list_skills），同一技能库逐字不变，提示缓存照样命中。
- 目录总长超过 CATALOG_CHARS 时逐级退让（Codex）：① 只留名字的行全放得下 → 剩余预算按字轮流分给各条描述
  （谁也不独占，短的先放全），描述被截的末尾加“…”；② 连名字都放不下 → 前面的只放名字，其余省略，
  末尾一句“另外 N 个技能没列出，用 skill_search 按关键词找”（这句不计入预算）。
- 搜索拆词：空格、标点都是分隔；连续的中文（>2 字）再切成两字一组（“周报模板” → 周报、报模、模板），英文按小写整词子串。
  打分：每个词命中名称 +3、描述 +2、正文 +1（id 算名称）；有一个词都没命中的技能不要；按分数、再按目录顺序。
  query 为空 = 列出全部（目录顺序），最多 LIST_MAX 条。
- 结果每条：id、名称、描述（DESC_MAX）、正文里第一个命中词附近的摘录（SNIPPET 字，没命中正文就不给）、是不是内置 / 自定义版。
- 只看启用的技能（停用的不进目录，也搜不到——和 use_skill 同一个开关）。
纯函数：传入技能列表，不碰磁盘，冒烟直接测。"""
from __future__ import annotations

import re
from collections.abc import Sequence

CATALOG_CHARS = 3000   # 目录最多占多少字（≈ 2000 token；内置 6 个约 500 字）
DESC_MAX = 120         # 目录 / 搜索结果里描述的长度上限
LIST_MAX = 30          # 空 query 或命中太多时最多列几条
SEARCH_MAX = 8         # 有 query 时默认列几条
SNIPPET = 40           # 摘录：命中词前后各多少字
QUERY_MAX = 200

_CJK = re.compile(r"[\u4e00-\u9fff]+")


def _one_line(text: str, limit: int = DESC_MAX) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


# 真机 v2.46 s1：只写“用 skill_search 找”时，模型把“按我的报销做法”当成聊天记录去 search_history 了
OMITTED = ("另外 {n} 个技能没列出（多半是用户自己存的做法）：用户说“按我的做法 / 我的流程 / 我的习惯”，"
           "或任务可能有现成做法时，先用 skill_search 按关键词找（按需工具，经 deferred_tool call），"
           "技能不在聊天记录里，别用 search_history 找。")
HEAD = "可用技能（任务和某个技能匹配时先 use_skill 读取做法）：\n"


def _minimum(s) -> str:
    return f"- {s.id}：{s.name}"


def _allocate(skills: Sequence, limit: int) -> list[int | None]:
    """每个技能放多少字描述；None = 省略这一行（Codex allocate_skill_lines）。成本 = 行字数 + 换行。"""
    descs = [_one_line(s.description) for s in skills]
    mins = [len(_minimum(s)) + 1 for s in skills]
    full = [m + (len(d) + 2 if d else 0) for m, d in zip(mins, descs)]   # “——” 两个字
    if sum(full) <= limit:
        return [len(d) for d in descs]
    if sum(mins) <= limit:
        remaining = limit - sum(mins)
        alloc = [0] * len(skills)
        changed = True
        while changed:   # 按字轮流分（Codex：Distribute description space round-robin）
            changed = False
            for i, d in enumerate(descs):
                if alloc[i] >= len(d):
                    continue
                delta = 3 if alloc[i] == 0 else 1          # 第一个字连带“——”
                if delta <= remaining:
                    alloc[i] += 1
                    remaining -= delta
                    changed = True
        return alloc
    out: list[int | None] = []
    used = 0
    for m in mins:
        if used + m <= limit:
            used += m
            out.append(0)
        else:
            out.append(None)
    return out


def prompt_section(skills: Sequence, budget: int = CATALOG_CHARS) -> str:
    """系统提示里的技能目录；没有技能返回空串。"""
    if not skills:
        return ""
    alloc = _allocate(skills, max(0, budget - len(HEAD)))
    lines: list[str] = []
    for s, n in zip(skills, alloc):
        if n is None:
            continue
        d = _one_line(s.description)
        if n <= 0 or not d:
            lines.append(_minimum(s))
        else:
            lines.append(f"{_minimum(s)}——{d[:n]}" + ("…" if n < len(d) and not d[:n].endswith("…") else ""))
    if rest := sum(1 for n in alloc if n is None):
        lines.append(OMITTED.format(n=rest))
    return HEAD + "\n".join(lines)


RELEVANT_MAX = 3       # 每轮最多点名几个“目录里没列出、但和这句话相关”的技能
RELEVANT_MIN = 6       # 至少多少分才点名（≈ 两个词命中名称或描述），且不低于最高分的一半


def omitted(skills: Sequence, budget: int = CATALOG_CHARS) -> list:
    """目录预算放不下、被省略的技能（与 prompt_section 同一分配）。"""
    alloc = _allocate(skills, max(0, budget - len(HEAD))) if skills else []
    return [s for s, n in zip(skills, alloc) if n is None]


def relevant_section(skills: Sequence, query: str) -> str:
    """每轮（VOLATILE 段）：目录省略了技能时，按用户这句话挑出可能相关的被省略技能点名给模型。
    真机 v2.46 s1：只靠目录末尾那句 + skill_search 工具，快模型仍去翻记忆 / 聊天记录——像相关记忆一样直接给出来。
    目录没省略任何技能 → 空串（目录里都看得见）。"""
    hidden = omitted(skills)
    words = terms(query)
    if not hidden or not words:
        return ""
    ranked = sorted(((score(s, words), i, s) for i, s in enumerate(hidden)), key=lambda r: (-r[0], r[1]))
    if not ranked or ranked[0][0] < RELEVANT_MIN:
        return ""
    floor = max(RELEVANT_MIN, (ranked[0][0] + 1) // 2)
    pick = [s for sc, _, s in ranked[:RELEVANT_MAX] if sc >= floor]
    return ("这句话可能用得上这些技能（目录里没列出；合适就先 use_skill 读取做法再做）：\n"
            + "\n".join(f"- {s.id}：{s.name}——{_one_line(s.description)}" for s in pick))


_TOKEN = re.compile(r"[\u4e00-\u9fff]+|[a-z0-9][a-z0-9_.+#-]*")


def terms(query: str) -> list[str]:
    """中文连续段 > 2 字切成两字一组，英文 / 数字按整词；标点、空格都是分隔。"""
    out: list[str] = []
    for tok in _TOKEN.findall((query or "")[:QUERY_MAX].lower()):
        if _CJK.fullmatch(tok) and len(tok) > 2:
            out.extend(tok[i:i + 2] for i in range(len(tok) - 1))
        else:
            out.append(tok.rstrip(".-"))
    seen: set[str] = set()
    return [t for t in out if t and not (t in seen or seen.add(t))]


def _snippet(body: str, words: list[str]) -> str:
    flat = " ".join((body or "").split())
    low = flat.lower()
    found = [(i, w) for w in words if (i := low.find(w)) >= 0]
    if not found:
        return ""
    i, w = min(found)
    start, end = max(0, i - SNIPPET), min(len(flat), i + len(w) + SNIPPET)
    return ("…" if start else "") + flat[start:end] + ("…" if end < len(flat) else "")


def score(s, words: list[str]) -> int:
    name = f"{s.id} {s.name}".lower()
    desc, body = (s.description or "").lower(), (s.body or "").lower()
    return sum(3 * (w in name) + 2 * (w in desc) + (w in body) for w in words)


def search(skills: Sequence, query: str, limit: int | None = None) -> list[dict]:
    words = terms(query)
    if not words:
        picked = list(skills)[: min(limit or LIST_MAX, LIST_MAX)]
        return [_hit(s, []) for s in picked]
    ranked = [(score(s, words), i, s) for i, s in enumerate(skills)]
    ranked = [r for r in ranked if r[0] > 0]
    ranked.sort(key=lambda r: (-r[0], r[1]))
    return [_hit(s, words) for _, _, s in ranked[: min(limit or SEARCH_MAX, LIST_MAX)]]


def _hit(s, words: list[str]) -> dict:
    d = {"id": s.id, "name": s.name, "description": _one_line(s.description)}
    if snip := _snippet(s.body, words):
        d["snippet"] = snip
    if s.customized:
        d["kind"] = "内置技能的自定义版"
    elif s.builtin:
        d["kind"] = "内置"
    return d


def render(hits: list[dict], query: str, total: int) -> str:
    """给模型看的搜索结果。"""
    if not hits:
        return (f"没有和「{query}」相关的技能（共 {total} 个启用的技能）。换个说法再搜，"
                "或者直接做；用户想把这次的做法留下来时用 save_skill。")
    head = f"找到 {len(hits)} 个技能" + (f"（关键词：{query}）" if query.strip() else f"（共 {total} 个）") + "，用 use_skill 读取全文：\n"
    rows = []
    for h in hits:
        r = f"- {h['id']}：{h['name']}——{h['description']}" + (f"（{h['kind']}）" if h.get("kind") else "")
        if h.get("snippet"):
            r += f"\n  摘录：{h['snippet']}"
        rows.append(r)
    return head + "\n".join(rows)
