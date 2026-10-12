# Copyright 2025 OpenAI
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
#
# Ported from openai/codex codex-rs/shell-command/src/bash.rs (Apache-2.0), modified:
#   parse_shell_lc_literal_commands / parse_literal_shell_word / is_literal_word_or_number /
#   parse_double_quoted_string / parse_raw_string translated to Python (py-tree-sitter + tree-sitter-bash).
# 修改：每个参数同时保留“原样拼写”（raw），供 command_guard 判断 ~ / $HOME / /* 这类非字面目标；
#       `rm >/dev/null -r x` 这种写法 tree-sitter 会把重定向后面的参数挂到 file_redirect 下，这里补回命令。
"""把一段 shell 脚本拆成“每条简单命令的字面词”——command_guard 的唯一解析入口。

和 Codex 一样，只用来“找危险”，不能用来“证明安全”：
- 走遍整棵语法树的每个 command 节点：管道、&& ||、if/for/while 体、$( ) 和反引号（包括双引号里的）、子 shell……
- 单引号字符串是数据不是命令（`echo 'rm -rf /'` 不算）；程序名不是字面量的（`$cmd -rf x`）跳过。
- 语法树有错误 → 返回 None，调用方退回保守的分词。
没装 tree-sitter（开发机/老镜像）→ available() 为 False，同样退回。
"""
from dataclasses import dataclass

try:  # 后端镜像里有；缺了就退回 command_guard 的分词兜底
    import tree_sitter_bash as _tsb
    from tree_sitter import Language, Parser
    _PARSER = Parser(Language(_tsb.language()))
except Exception:  # pragma: no cover - 取决于环境
    _PARSER = None

# Codex is_literal_word_or_number：带这些字符的词运行时会被展开/转义，源码拼写不等于真实 argv
_NOT_LITERAL = set("{}*?[]\\~^#$`")
_ESCAPES_IN_DQ = set('$`"\\\n')


@dataclass(frozen=True)
class Word:
    text: str | None  # 字面值；None = 运行时才知道（变量、通配、~ ……）
    raw: str          # 源码拼写（去掉外层引号），用来认 ~ / $HOME / /* 这类目标


def available() -> bool:
    return _PARSER is not None


def _src(node) -> str:
    return node.text.decode("utf-8", "replace")


def _is_literal(node) -> bool:
    if node.type not in ("word", "number") or node.named_children:
        return False
    w = _src(node)
    return not w.startswith("=") and not (set(w) & _NOT_LITERAL)


def _double_quoted(node) -> str | None:
    if node.type != "string" or any(p.type != "string_content" for p in node.named_children):
        return None
    raw = _src(node)
    if not (raw.startswith('"') and raw.endswith('"') and len(raw) >= 2):
        return None
    inner = raw[1:-1]
    if any(a == "\\" and b in _ESCAPES_IN_DQ for a, b in zip(inner, inner[1:])):
        return None
    return inner


def _raw_string(node) -> str | None:
    raw = _src(node)
    return raw[1:-1] if node.type == "raw_string" and len(raw) >= 2 and raw[0] == raw[-1] == "'" else None


def literal(node) -> str | None:
    """Codex parse_literal_shell_word。"""
    t = node.type
    if t in ("word", "number"):
        return _src(node) if _is_literal(node) else None
    if t == "string":
        return _double_quoted(node)
    if t == "raw_string":
        return _raw_string(node)
    if t == "concatenation":
        parts = [literal(p) for p in node.named_children]
        if any(p is None for p in parts):
            return None
        joined = "".join(parts)  # type: ignore[arg-type]
        return joined or None
    return None


def _unquote(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        return raw[1:-1]
    return raw


def _command(node) -> list[Word] | None:
    """Codex parse_literal_command_from_node，参数多带一份 raw。"""
    words: list[Word] = []
    named = False
    for child in node.named_children:
        if child.type == "command_name":
            if not child.named_children:
                return None
            name = literal(child.named_children[0])
            if name is None:
                return None  # $cmd -rf x：程序名运行时才知道，Codex 同样跳过
            words.append(Word(name, name))
            named = True
        elif named and child.type in ("word", "number", "string", "raw_string", "concatenation",
                                      "simple_expansion", "expansion"):
            words.append(Word(literal(child), _unquote(_src(child))))
    if not named:
        return None
    # tree-sitter 把 `rm >/dev/null -r x` 的 -r x 挂在 file_redirect 下（重定向目标之后的词）
    parent = node.parent
    if parent is not None and parent.type == "redirected_statement":
        for red in parent.named_children:
            if red.type == "file_redirect":
                for extra in red.named_children[1:]:
                    words.append(Word(literal(extra), _unquote(_src(extra))))
    return words


def commands(script: str) -> list[list[Word]] | None:
    """整段脚本里的每条简单命令（源码顺序）。解析不了 / 语法错 → None。"""
    if _PARSER is None:
        return None
    tree = _PARSER.parse(script.encode("utf-8"))
    root = tree.root_node
    if root.has_error:
        return None
    found = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "command":
            words = _command(node)
            if words:
                found.append((node.start_byte, words))
        stack.extend(node.named_children)
    found.sort(key=lambda x: x[0])
    return [w for _, w in found]
