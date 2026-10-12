# Copyright 2025 OpenAI
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
#
# Ported from openai/codex (Apache-2.0), modified:
#   codex-rs/execpolicy/src/{decision.rs,policy.rs}      Decision 三档、按段取最严（check_multiple）、前缀规则匹配
#   codex-rs/core/src/exec_policy.rs                      UnlessTrusted 的未匹配命令 → Prompt、Never → Forbidden、
#                                                         BANNED_PREFIX_SUGGESTIONS、derive_requested_execpolicy_amendment_from_prefix_rule、
#                                                         try_derive_execpolicy_amendment_for_prompt_rules、prefix_rule_would_approve_all_commands
#   codex-rs/core/src/command_canonicalization.rs          canonicalize_command_for_approval（会话内“这次对话都允许”的键）
#   codex-rs/core/src/tools/sandboxing.rs                  with_cached_approval（全部键都批过才跳过）
# 修改：只实现 Codex 的 UnlessTrusted 一档（主机命令默认每条都问）；command_guard 的 block 一律禁止，用户批准也不放行；
#       去掉 sudo 前缀再匹配（host agent 本来就是 root）；“会停掉助手自己”的命令（docker/systemctl 停服务）只许“仅这一次”。
"""服务器主机命令的审批策略——host_command 的唯一规则。

三档（Codex Decision）：allow（用户留下的前缀规则或这段对话里批过）/ prompt（弹卡问）/ forbidden（不执行）。
- 每段简单命令单独判，整条取最严：一段没被规则覆盖就要问（Codex check_multiple）。
- 解析不出字面词（$变量、通配、语法错）→ 整条当一段，只能“仅这一次”或“这段对话都允许这一整条”，不给前缀规则。
- 无人值守（定时任务）没人能批 → 需要问的直接 forbidden（Codex AskForApproval::Never + Prompt）。
"""
from dataclasses import dataclass, field

from . import command_guard, shell_parse

# Codex BANNED_PREFIX_SUGGESTIONS（POSIX 部分原样）+ 我们补的提权/包装器：这些前缀太宽，等于“以后什么都允许”
BANNED_PREFIXES: set[tuple[str, ...]] = {tuple(p) for p in [
    ["/bin/bash"], ["/bin/bash", "-c"], ["/bin/bash", "-lc"], ["/bin/sh"], ["/bin/sh", "-c"], ["/bin/sh", "-lc"],
    ["/bin/zsh"], ["/bin/zsh", "-c"], ["/bin/zsh", "-lc"], ["Rscript"], ["bash"], ["bash", "-c"], ["bash", "-lc"],
    ["bun"], ["bun", "-e"], ["bun", "run"], ["dash"], ["dash", "-c"], ["deno"], ["deno", "eval"], ["env"],
    ["fish"], ["fish", "-c"], ["git"], ["julia"], ["julia", "-e"], ["ksh"], ["ksh", "-c"], ["lua"], ["lua", "-e"],
    ["node"], ["node", "-e"], ["nodejs"], ["nodejs", "-e"], ["npm", "run"], ["perl"], ["perl", "-e"],
    ["php"], ["php", "-r"], ["pnpm", "run"], ["pypy"], ["pypy3"], ["python"], ["python", "-"], ["python", "-c"],
    ["python3"], ["python3", "-"], ["python3", "-c"], ["rm"], ["ruby"], ["ruby", "-e"], ["sh"], ["sh", "-c"],
    ["sh", "-lc"], ["sudo"], ["zsh"], ["zsh", "-c"], ["zsh", "-lc"],
    # 补充
    ["su"], ["doas"], ["xargs"], ["eval"], ["exec"], ["nohup"], ["timeout"], ["nice"], ["setsid"], ["watch"],
    ["find"], ["docker"], ["docker", "exec"], ["docker", "run"], ["systemctl"], ["apt"], ["apt-get"], ["curl"], ["wget"],
]}
# 会停掉 / 删掉助手自己（整套服务跑在 docker 里）的命令：照样能批，但只许“仅这一次”
SELF_HARM = [
    (("docker", "stop"), "停掉容器"), (("docker", "kill"), "强杀容器"), (("docker", "rm"), "删除容器"),
    (("docker", "compose", "down"), "停掉整套服务"), (("docker", "compose", "stop"), "停掉整套服务"),
    (("docker", "system", "prune"), "清理 Docker 数据"), (("docker", "volume", "rm"), "删除 Docker 数据卷"),
    (("systemctl", "stop", "docker"), "停掉 Docker"), (("systemctl", "restart", "docker"), "重启 Docker"),
    (("systemctl", "disable", "docker"), "停用 Docker"), (("systemctl", "stop", "assistant-host"), "停掉主机代理"),
    (("ufw", "enable"), "开启防火墙（可能挡住 SSH）"), (("iptables", "-F"), "清空防火墙规则"),
    (("passwd",), "改密码"), (("userdel",), "删除系统用户"),
]
PREFIX_MAX = 8      # 一条前缀规则最多几个词（Codex 没限；太长的规则等于只放行这一条）
KEY_MAX = 4000      # 会话批准键里整段脚本的长度上限


@dataclass(frozen=True)
class Requirement:
    """Codex ExecApprovalRequirement：skip（直接跑）/ ask（弹卡）/ forbid（不执行，reason 给模型）。"""
    kind: str
    reason: str = ""            # forbid：为什么不执行；ask：卡上那句“为什么要你看一眼”（危险提示，可空）
    rule: tuple[str, ...] | None = None   # ask：卡上“以后都允许以 … 开头的命令”的前缀；None = 不给这个选项
    session: bool = True        # ask：给不给“这段对话都允许”
    key: tuple[str, ...] = ()   # 会话批准键（canonical）
    commands: list[list[str]] | None = field(default=None, compare=False)


def strip_sudo(words: list[str]) -> list[str]:
    """host agent 以 root 跑：sudo [选项] 不改变命令是什么，匹配前去掉（sudo -u 别人 不去，换身份是另一回事）。"""
    if not words or words[0] not in ("sudo", "/usr/bin/sudo"):
        return words
    i = 1
    while i < len(words) and words[i].startswith("-"):
        if words[i] in ("-u", "-g", "--user", "--group") or words[i].startswith(("-u", "-g")) and len(words[i]) > 2:
            return words  # 换成别的用户跑：不是同一条命令
        if words[i] == "--":
            i += 1
            break
        i += 1
    return words[i:] or words


def commands(script: str) -> list[list[str]] | None:
    """每段简单命令的字面词（去掉 sudo）；任何一个词不是字面量 / 解析不了 → None（Codex parse_shell_lc_plain_commands）。"""
    parsed = shell_parse.commands(script)
    if not parsed:
        return None
    out = []
    for words in parsed:
        if any(w.text is None for w in words):
            return None
        out.append(strip_sudo([w.text for w in words]))
    return out


def approval_key(script: str, cmds: list[list[str]] | None) -> tuple[str, ...]:
    """Codex canonicalize_command_for_approval：只有一段 → 它的词（/bin/bash -lc 和 bash -lc 一样）；否则整段原文。"""
    if cmds is not None and len(cmds) == 1:
        return tuple(cmds[0])
    return ("__script__", script.strip()[:KEY_MAX])


def matches(prefix: tuple[str, ...] | list[str], cmd: list[str]) -> bool:
    """Codex PrefixRule::matches（我们的模式只有字面词，没有多选）。"""
    return 0 < len(prefix) <= len(cmd) and tuple(cmd[:len(prefix)]) == tuple(prefix)


def _self_harm(cmds: list[list[str]] | None, script: str) -> str | None:
    if cmds is None:
        lowered = " ".join(script.split())
        return next((why for p, why in SELF_HARM if " ".join(p) in lowered), None)
    return next((why for cmd in cmds for p, why in SELF_HARM if matches(p, cmd)), None)


def usable_rule(prefix: list[str] | tuple[str, ...] | None, cmds: list[list[str]] | None) -> tuple[str, ...] | None:
    """Codex derive_requested_execpolicy_amendment_from_prefix_rule：非空、不在禁用表、能覆盖这条命令的每一段才给。"""
    if not prefix or cmds is None:
        return None
    rule = tuple(str(w) for w in prefix)
    if len(rule) > PREFIX_MAX or rule in BANNED_PREFIXES or any(not w or "\n" in w for w in rule):
        return None
    return rule if all(matches(rule, c) for c in cmds) else None


def evaluate(script: str, rules: list[list[str]], granted: set[tuple[str, ...]] | frozenset = frozenset(),
             unattended: bool = False, proposed: list[str] | None = None) -> Requirement:
    """一条主机命令要不要问用户。rules = 已存的前缀规则；granted = 这段对话里点过“都允许”的键；
    proposed = 模型建议的前缀（Codex prefix_rule 参数），用不了就退回 Codex 的“整条命令当前缀”。"""
    if not script.strip():
        return Requirement("forbid", "命令是空的。")
    found = command_guard.verdicts(script)
    if (b := next((v for v in found if v.level == "block"), None)) is not None:
        return Requirement("forbid", command_guard.refusal(b))
    cmds = commands(script)
    key = approval_key(script, cmds)
    covered = cmds is not None and all(any(matches(r, c) for r in rules) for c in cmds)
    if covered or key in granted:  # Codex with_cached_approval：全部键都批过才跳过
        return Requirement("skip", key=key, commands=cmds)
    if unattended:
        return Requirement("forbid", "定时任务里没人能批准，主机命令只能跑你事先在审批卡上点过“以后都允许”的那类；"
                                     "这条没被覆盖，没有执行。告诉用户要在服务器上做什么，请他在聊天里让你来做。",
                           key=key, commands=cmds)
    risky = next((v.why for v in found if v.level == "ask"), None)
    harm = _self_harm(cmds, script)
    reason = f"会{harm}" if harm else (risky or "")
    rule = None
    if not risky and not harm:
        rule = usable_rule(proposed, cmds)
        # Codex try_derive_execpolicy_amendment_for_prompt_rules：没人建议时，第一段没被覆盖的命令整条当前缀
        if rule is None and cmds is not None and len(cmds) == 1:
            rule = usable_rule(cmds[0], cmds)
    return Requirement("ask", reason, rule, session=harm is None, key=key, commands=cmds)


def describe_rule(prefix: list[str] | tuple[str, ...]) -> str:
    return " ".join(prefix)
