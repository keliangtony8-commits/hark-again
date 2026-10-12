# Copyright 2026 Google LLC
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
#
# Ported from google-gemini/gemini-cli packages/core/src/sandbox/utils/commandSafety.ts (Apache-2.0), modified:
#   isKnownSafeCommand / isSafeToCallWithExec / findGitSubcommand / gitHasConfigOverrideGlobalOption /
#   gitSubcommandArgsAreReadOnly / gitBranchIsReadOnly / isValidSedNArg translated to Python.
# 修改：
#   - 去掉“路径不能逃出工作区”的检查和 rg 必须是受信路径：我们的命令跑在沙盒容器里，容器就是边界，读文件不伤人；
#   - 脚本拆分换成 shlex（标点单独成词）：只接受 && || ; | 连接，任何 ( ) < > & 或 $ ` <<（展开、子 shell、重定向、
#     后台、heredoc）一律不算只读——比 Gemini 的“出现 ()<> 字符就拒”更准：引号里的括号不误伤；
#   - 补了几条明显只读的命令（tree du df file sort diff cmp basename dirname realpath date printf jq ps free uptime nproc），
#     会写文件的选项（sort -o、tree -o、diff --output）照 base64 -o 的办法拒掉。
"""判断一段 shell 脚本是不是“只读”的——计划模式（app/plan_mode.py）放行 run_command 的唯一依据。

和 command_guard 相反：那边只“找危险”，这里要“证明安全”，所以白名单 + 解析不了就当不安全（fail closed）。
"""
import shlex

# Gemini safeCommands（__read / __write 是它沙盒内部的伪命令，去掉）
SAFE = {
    "cat", "cd", "cut", "echo", "expr", "false", "grep", "head", "id", "ls", "nl", "paste", "pwd", "rev", "seq",
    "stat", "tail", "tr", "true", "uname", "uniq", "wc", "which", "whoami", "numfmt", "tac",
}
# 嫁接：明显只读、没有执行别的程序能力的命令；值 = 会写文件的选项（出现就不算只读）
EXTRA = {
    "tree": {"-o"}, "du": set(), "df": set(), "file": set(), "sort": {"-o", "--output", "--compress-program"},
    "diff": {"--output"}, "cmp": set(), "basename": set(), "dirname": set(), "realpath": set(), "date": {"-s", "--set"},
    "printf": set(), "jq": set(), "ps": set(), "free": set(), "uptime": set(), "nproc": set(),
}
FIND_UNSAFE = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fls", "-fprint", "-fprint0", "-fprintf"}
RG_UNSAFE_WITH_ARGS = ("--pre", "--hostname-bin")
RG_UNSAFE = {"--search-zip", "-z"}
GIT_READ = ("status", "log", "diff", "show", "branch")
GIT_UNSAFE_FLAGS = {"--output", "--ext-diff", "--textconv", "--exec", "--paginate"}
GIT_BRANCH_READ = {"--list", "-l", "--show-current", "-a", "--all", "-r", "--remotes", "-v", "-vv", "--verbose"}
_GIT_GLOBAL_WITH_VALUE = {"-C", "-c", "--config-env", "--exec-path", "--git-dir", "--namespace", "--super-prefix", "--work-tree"}
_GIT_GLOBAL_PREFIX = ("--config-env=", "--exec-path=", "--git-dir=", "--namespace=", "--super-prefix=", "--work-tree=")
OPERATORS = {"&&", "||", ";", "|"}
_PUNCT = "();<>|&"


def split(script: str) -> list[list[str]] | None:
    """脚本 → 每段命令的词；有不认的连接符 / 展开 / 重定向 / heredoc → None（不算只读）。"""
    if not script or not script.strip() or "$" in script or "`" in script or "<<" in script:
        return None
    try:
        lex = shlex.shlex(script.replace("\n", " ; "), posix=True, punctuation_chars=_PUNCT)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:  # 引号不配对
        return None
    out: list[list[str]] = []
    cur: list[str] = []
    for t in tokens:
        if t and set(t) <= set(_PUNCT):
            if t not in OPERATORS:
                return None  # ( ) < > >> & |& ;; ……
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        out.append(cur)
    return out or None


def is_read_only(script: str) -> bool:
    """整段脚本的每一段都是已知只读命令才 True（Gemini isKnownSafeCommand 的 bash -lc 分支）。"""
    segments = split(script)
    return segments is not None and all(is_safe(args) for args in segments)


def is_safe(args: list[str]) -> bool:
    """Gemini isSafeToCallWithExec（去掉路径检查）。"""
    if not args:
        return False
    cmd = args[0]
    if cmd in SAFE:
        return True
    if cmd in EXTRA:
        bad = EXTRA[cmd]
        return not any(a in bad or any(a.startswith(f"{b}=") for b in bad if b.startswith("--")) for a in args[1:])
    if cmd == "base64":
        return not any(a in ("-o", "--output") or a.startswith("--output=") or (a.startswith("-o") and a != "-o")
                       for a in args[1:])
    if cmd == "find":
        return not any(a in FIND_UNSAFE for a in args)
    if cmd == "rg":
        for a in args[1:]:
            if a in RG_UNSAFE or any(a == o or a.startswith(o + "=") for o in RG_UNSAFE_WITH_ARGS):
                return False
        return True
    if cmd == "git":
        if git_has_config_override(args):
            return False
        idx, sub = find_git_subcommand(args, GIT_READ)
        if sub is None:
            return False
        rest = args[idx + 1:]
        if sub == "branch":
            return git_args_read_only(rest) and git_branch_read_only(rest)
        return git_args_read_only(rest)
    if cmd == "sed":  # 只放 sed -n {N|M,N}p [file]
        return len(args) <= 4 and len(args) >= 3 and args[1] == "-n" and valid_sed_n(args[2])
    return False


def find_git_subcommand(args: list[str], subcommands: tuple[str, ...]) -> tuple[int, str | None]:
    """跳过 git 的全局选项（-C dir、--git-dir=…）找子命令；第一个非选项词不在名单里 → (-1, None)。"""
    skip = False
    for idx in range(1, len(args)):
        if skip:
            skip = False
            continue
        a = args[idx]
        if a.startswith(_GIT_GLOBAL_PREFIX) or ((a.startswith("-C") or a.startswith("-c")) and len(a) > 2):
            continue
        if a in _GIT_GLOBAL_WITH_VALUE:
            skip = True
            continue
        if a == "--" or a.startswith("-"):
            continue
        if a in subcommands:
            return idx, a
        return -1, None
    return -1, None


def git_has_config_override(args: list[str]) -> bool:
    """-c / --config-env 能借 git 配置执行任意程序（core.pager 等）。"""
    return any(a == "-c" or a == "--config-env" or (a.startswith("-c") and len(a) > 2) or a.startswith("--config-env=")
               for a in args)


def git_args_read_only(args: list[str]) -> bool:
    return not any(a in GIT_UNSAFE_FLAGS or a.startswith("--output=") or a.startswith("--exec=") for a in args)


def git_branch_read_only(args: list[str]) -> bool:
    """git branch 只许列出（不带参数，或只带列出类选项）；建 / 删 / 改名都不算。"""
    if not args:
        return True
    saw = False
    for a in args:
        if a in GIT_BRANCH_READ or a.startswith("--format="):
            saw = True
        else:
            return False
    return saw


def valid_sed_n(arg: str | None) -> bool:
    if not arg or not arg.endswith("p"):
        return False
    parts = arg[:-1].split(",")
    return 1 <= len(parts) <= 2 and all(p.isdigit() and p.isascii() for p in parts)
