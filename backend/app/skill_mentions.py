# Copyright 2025 OpenAI
# SPDX-License-Identifier: Apache-2.0
# Ported from openai/codex codex-rs/skills/src/mentions.rs + selection.rs (Apache-2.0), modified:
#   - 只认“已存在且启用”的技能 id（我们的 id 唯一，不需要 Codex 的同名计数 / 连接器冲突判断）；
#   - id 可以是中文，所以不按“名字字符”截断，而是在已知 id 里取最长的前缀匹配，后面紧跟英文名字字符就不算
#     （`$web-research帮我查` 认，`$web-researcher` 不认）；
#   - `$` 前面是英文字母 / 数字 / 下划线 / `$` 不算（US$5、$$ 不误认）；代码段 / 代码块里的不认（同 file_mentions）；
#   - 不支持 Codex 的 `[$name](path)` 链接写法（我们的技能不是磁盘路径）。
"""消息里的 `$技能`：用户点名“这次按这个技能做”（学 Codex 的 `$skill` 显式调用）。这是唯一规则。
发消息时 routes/ws 用 ids() 认出来，存成 skill 引用块（只存 id + 名字）；正文每轮由 agent/context 按当前技能库给模型，
模型不用再 use_skill。停用 / 删掉的技能不认（和 use_skill 同一个开关）。"""
import re

from . import skills_store

SKILL_MENTIONS_MAX = 3      # 一条消息最多点名几个技能（每个正文都要进上下文，控 token）
SKILL_BODY_CHARS = 8000     # 每个技能正文最多给模型多少字
SIGIL = "$"

_NAME_CHAR = re.compile(r"[A-Za-z0-9_:\-]")  # Codex is_mention_name_char
_BLOCKED_BEFORE = re.compile(r"[A-Za-z0-9_$]")
_CODE = re.compile(r"```.*?(?:```|$)|`[^`\n]*`", re.S)  # 代码块 / 行内代码：里面的 $ 是 shell 变量

# Codex is_common_env_var：这些名字永远当环境变量，不当技能
COMMON_ENV_VARS = frozenset({"PATH", "HOME", "USER", "SHELL", "PWD", "TMPDIR", "TEMP", "TMP", "LANG", "TERM",
                             "XDG_CONFIG_HOME"})


def _blank_code(text: str) -> str:
    return _CODE.sub(lambda m: " " * len(m.group(0)), text)


def find(text: str, known: list[str]) -> list[str]:
    """text 里点名的技能 id（按出现顺序、去重、最多 SKILL_MENTIONS_MAX 个）。known = 可用的技能 id。纯函数。"""
    if SIGIL not in text or not known:
        return []
    text = _blank_code(text)
    by_len = sorted({k for k in known if k and k.upper() not in COMMON_ENV_VARS}, key=len, reverse=True)
    out: list[str] = []
    i = text.find(SIGIL)
    while i >= 0 and len(out) < SKILL_MENTIONS_MAX:
        if not (i > 0 and _BLOCKED_BEFORE.match(text[i - 1])):
            rest = text[i + 1:]
            for k in by_len:  # 最长的先试：web-research-pro 不会被 web-research 截走
                if rest.startswith(k) and not (len(rest) > len(k) and _NAME_CHAR.match(rest[len(k)])):
                    if k not in out:
                        out.append(k)
                    break
        i = text.find(SIGIL, i + 1)
    return out


def ids(text: str) -> list[str]:
    """用当前启用的技能库认 text 里的 `$技能`。"""
    return find(text, [s.id for s in skills_store.enabled_skills()])


def blocks(text: str, have: list[dict] | None = None) -> list[dict]:
    """认出来的技能 → skill 引用块；have 里已有的不重复（编辑后重答时用）。"""
    taken = {b.get("id") for b in have or [] if b.get("type") == "skill"}
    room = SKILL_MENTIONS_MAX - len(taken)
    out = []
    for sid in ids(text):
        if sid in taken or len(out) >= room:
            continue
        if (s := skills_store.get_skill(sid)) is not None:
            out.append({"type": "skill", "id": s.id, "name": s.name})
    return out


def render(b: dict) -> str:
    """给模型看的样子（学 Codex 的 <skill> 片段）：按当前技能库取正文；停用 / 删了就说明，别让模型瞎按。"""
    s = skills_store.get_skill(b.get("id") or "")
    name = b.get("name") or b.get("id") or ""
    if s is None:
        return f"[用户点名的技能「{name}」已被删除，按常识完成即可]"
    if not s.enabled:
        return f"[用户点名的技能「{s.name}」已被停用，不要按它做]"
    body = s.body if len(s.body) <= SKILL_BODY_CHARS else s.body[:SKILL_BODY_CHARS] + "\n…（太长已截断，需要全文用 use_skill）"
    return (f"<skill>\n<name>{s.name}</name>\n<id>{s.id}</id>\n"
            f"用户点名这次按这个技能做（正文已给出，不用再 use_skill）：\n{s.description}\n\n{body}\n</skill>")
