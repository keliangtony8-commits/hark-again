# Copyright 2025 OpenAI
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
#
# Ported from openai/codex codex-rs/shell-command/src/bash.rs (Apache-2.0), modified:
#   parse_shell_lc_literal_commands / parse_literal_shell_word / is_literal_word_or_number /
#   parse_double_quoted_string / parse_raw_string translated to Python (py-tree-sitter + tree-sitter-bash).
# 修改：每个参数同时保留“原样拼写”（raw），供 command_guard 判断 ~ / $HOME / /* 这类非字面目标；
#       `rm >/dev/null -r x` 这种写法 tree-sitter 会把重定向后面的参数挂到 file_redirect 下，这里补回命令。
# v2.26 修改（E2E B3）：Codex 遇到非字面程序名整条跳过 → `\rm -rf /`、`R=rm; $R -rf /` 什么都不报（fail-open）。
#       现在非字面的词多一份 guess（去掉反斜杠/引号；前面赋过字面值的变量），程序名非字面也照样返回
#       （text=None），交给 command_guard fail closed；每条命令带 piped（管道里不是第一段）。
"""把一段 shell 脚本拆成“每条简单命令的字面词”——command_guard 的唯一解析入口。

和 Codex 一样，只用来“找危险”，不能用来“证明安全”：
- 走遍整棵语法树的每个 command 节点：管道、&& ||、if/for/while 体、$( ) 和反引号（包括双引号里的）、子 shell……
- 单引号字符串是数据不是命令（`echo 'rm -rf /'` 不算）。
- 词不是字面量时 text=None，另给 guess（运行时最可能的值）：`\\rm` → rm、`r"m"` 照样字面、
  `R=rm; $R` → rm（取源码里它前面最后一次独立赋值）。guess 只用来找危险，不能当真实 argv（审批键只认 text）。
- 程序名不是字面量（`$cmd -rf x`）也返回，第一个词 text=None——调用方必须当“看不清”处理，不能当安全。
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
    guess: str | None = None  # text 为 None 时最可能的运行时值（只给“找危险”用）

    @property
    def value(self) -> str | None:
        return self.text if self.text is not None else self.guess


class Command(list):
    """一条简单命令的词；piped = 在管道里且不是第一段（标准输入来自前一条命令）。"""
    piped = False


# 不带引号时会被 shell 展开的字符：出现就猜不出（通配、花括号、变量、命令替换）
_EXPANDS = set("$`*?[{}")


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


def dequote(raw: str) -> str | None:
    """按 bash 的规则去掉引号和反斜杠（`\\rm` → rm、`r'm'` → rm、`\\/` → /）；
    碰到会展开的东西（$ ` 通配 花括号、开头的 ~）→ None。"""
    out: list[str] = []
    i, n = 0, len(raw)
    while i < n:
        c = raw[i]
        if c == "\\":
            if i + 1 >= n:
                return None
            if raw[i + 1] != "\n":
                out.append(raw[i + 1])
            i += 2
        elif c == "'":
            j = raw.find("'", i + 1)
            if j < 0:
                return None
            out.append(raw[i + 1:j])
            i = j + 1
        elif c == '"':
            i += 1
            while i < n and raw[i] != '"':
                d = raw[i]
                if d in "$`":
                    return None
                if d == "\\" and i + 1 < n and raw[i + 1] in _ESCAPES_IN_DQ:
                    if raw[i + 1] != "\n":
                        out.append(raw[i + 1])
                    i += 2
                    continue
                out.append(d)
                i += 1
            if i >= n:
                return None
            i += 1
        elif c in _EXPANDS or (c == "~" and i == 0):
            return None
        else:
            out.append(c)
            i += 1
    return "".join(out) or None


def _variable(node) -> str | None:
    """词恰好是一个变量（$R、${R}、"$R"、"${R}"）→ 变量名。"""
    if node.type == "string" and len(node.named_children) == 1:
        inner = node.named_children[0]
        if _src(node) != '"' + _src(inner) + '"':
            return None
        node = inner
    if node.type not in ("simple_expansion", "expansion") or len(node.named_children) != 1:
        return None
    var = node.named_children[0]
    if var.type != "variable_name":
        return None
    name = _src(var)
    return name if _src(node) in ("$" + name, "${" + name + "}") else None


def _assignments(root) -> dict[str, list[tuple[int, str | None]]]:
    """独立的赋值（R=rm、export R=rm）：变量名 → [(位置, 字面值或 None)]。
    `R=x cmd $R` 这种命令前缀赋值不影响同一条命令的展开，不收。"""
    env: dict[str, list[tuple[int, str | None]]] = {}
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "variable_assignment" and (node.parent is None or node.parent.type != "command"):
            name, value = node.child_by_field_name("name"), node.child_by_field_name("value")
            if name is not None:
                v = "" if value is None else literal(value)
                if v is None and value is not None:
                    v = dequote(_src(value))
                env.setdefault(_src(name), []).append((node.start_byte, v))
        stack.extend(node.named_children)
    for vals in env.values():
        vals.sort(key=lambda x: x[0])
    return env


def _guess(node, env) -> str | None:
    g = dequote(_src(node))
    if g is not None:
        return g
    name = _variable(node)
    if name is None:
        return None
    before = [v for pos, v in env.get(name, ()) if pos < node.start_byte]
    return before[-1] if before else None


def _word(node, env) -> Word:
    text = literal(node)
    return Word(text, _unquote(_src(node)), None if text is not None else _guess(node, env))


def _piped(node) -> bool:
    stmt, parent = node, node.parent
    if parent is not None and parent.type == "redirected_statement":
        stmt, parent = parent, parent.parent
    return parent is not None and parent.type == "pipeline" and parent.named_children[0].start_byte != stmt.start_byte


def _command(node, env) -> Command | None:
    """Codex parse_literal_command_from_node，参数多带一份 raw / guess；程序名非字面也返回（text=None）。"""
    words = Command()
    named = False
    for child in node.named_children:
        if child.type == "command_name":
            if not child.named_children:
                return None
            words.append(_word(child.named_children[0], env))
            named = True
        elif named and child.type in ("word", "number", "string", "raw_string", "concatenation",
                                      "simple_expansion", "expansion"):
            words.append(_word(child, env))
    if not named:
        return None
    # tree-sitter 把 `rm >/dev/null -r x` 的 -r x 挂在 file_redirect 下（重定向目标之后的词）
    parent = node.parent
    if parent is not None and parent.type == "redirected_statement":
        for red in parent.named_children:
            if red.type == "file_redirect":
                for extra in red.named_children[1:]:
                    words.append(_word(extra, env))
    words.piped = _piped(node)
    return words


def commands(script: str) -> list[Command] | None:
    """整段脚本里的每条简单命令（源码顺序）。解析不了 / 语法错 → None。"""
    if _PARSER is None:
        return None
    tree = _PARSER.parse(script.encode("utf-8"))
    root = tree.root_node
    if root.has_error:
        return None
    env = _assignments(root)
    found = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "command":
            words = _command(node, env)
            if words:
                found.append((node.start_byte, words))
        stack.extend(node.named_children)
    found.sort(key=lambda x: x[0])
    return [w for _, w in found]
