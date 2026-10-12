"""命令安全规则的唯一入口：run_command（前台/后台）执行前都先问 verdict(command)。

三级（优先级 block > unsupported > ask）：
  block  永远不执行（批准也不行）：毁掉系统或整盘、关机、fork 炸弹、杀光进程……
         沙盒本身有资源和权限隔离，这一层是“别让模型一句手滑把工作区/容器搞没”的第二道防线。
  unsupported  沙盒里根本做不到、跑了只会白白报错一轮的：sudo / su、apt / dnf / yum / apk 装系统软件
         （容器非 root）。不执行，直接告诉模型能怎么装（pip / npm 落到工作区，系统软件看预装清单）。
  ask    执行前在聊天里弹审批卡等用户点头：推送/提交代码、递归删除、发布软件包、curl | sh……
做法参考了 OpenAI Codex CLI（Apache-2.0）的命令安全分类：先把一整条 shell 拆成一段段简单命令
（; && || | 换行），去掉 sudo / env / nohup 这类前缀再逐段看程序名和参数，而不是对整串做正则——
`echo "rm -rf /"` 不会误伤，`cd x && rm -rf ~` 也逃不掉。拆不开（引号不配对）就退回整串正则。
"""
import re
import shlex
from dataclasses import dataclass

SEPARATORS = {";", "&&", "||", "|", "&", "\n", "(", ")", "|&"}
PREFIXES = {"sudo", "nohup", "time", "command", "exec", "nice", "ionice", "stdbuf", "xargs", "busybox"}
# 删了就等于毁掉系统或整个家目录的目标
SYSTEM_PATHS = {"/", "/*", "~", "~/", "~/*", "$HOME", "${HOME}", "$HOME/", "$HOME/*", "/home", "/root", "/etc",
                "/usr", "/var", "/bin", "/sbin", "/boot", "/lib", "/lib64", "/opt", "/srv", "/proc", "/sys", "/dev",
                "/workspace", "/workspace/"}
NO_ROOT = {"sudo", "su", "doas"}
SYSTEM_PKG = {"apt", "apt-get", "aptitude", "dpkg", "dnf", "yum", "apk", "pacman", "zypper", "snap"}
POWER = {"shutdown", "reboot", "halt", "poweroff"}
DISK = re.compile(r"^(mkfs(\.\w+)?|mke2fs|wipefs|fdisk|sfdisk|parted|mkswap)$")
FORK_BOMB = re.compile(r":\s*\(\s*\)\s*\{[^}]*:\s*\|\s*:[^}]*&[^}]*\}")
RAW_DEVICE = re.compile(r">\s*/dev/(sd|nvme|vd|xvd|hd|mmcblk)\w*")
PIPE_TO_SHELL = re.compile(r"\b(curl|wget)\b[^|;&]*\|\s*(sudo\s+)?(ba|z|da)?sh\b")


@dataclass(frozen=True)
class Verdict:
    level: str  # "block" | "unsupported" | "ask"
    why: str


def _segments(command: str) -> list[list[str]] | None:
    try:
        lex = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=";&|()")
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:  # 引号不配对
        return None
    out, cur = [], []
    for t in tokens:
        if t in SEPARATORS or set(t) <= set(";&|()"):
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        out.append(cur)
    return out


def _strip(words: list[str]) -> list[str]:
    """去掉 sudo / env A=B / nohup 这类前缀，留下真正的程序和参数。"""
    i = 0
    while i < len(words):
        w = words[i]
        if w in PREFIXES or w == "env" or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", w):
            i += 1
        elif words[i - 1:i] == ["sudo"] and w.startswith("-"):  # sudo -u x
            i += 2 if w in ("-u", "-g") else 1
        else:
            break
    words = words[i:]
    if words:
        words = [words[0].rsplit("/", 1)[-1], *words[1:]]  # /bin/rm → rm
    return words


def flags_only_query(prog: str, args: list[str]) -> bool:
    """只是查询（dpkg -l、apt list --installed、apt show x）不需要 root，照常放行。"""
    if prog == "dpkg":
        return bool(args) and args[0] in ("-l", "-L", "-s", "--list", "--listfiles", "--status", "-S", "--search")
    return prog in ("apt", "apt-get") and bool(args) and args[0] in ("list", "show", "search", "policy")


def _flags(args: list[str]) -> set[str]:
    out = set()
    for a in args:
        if a.startswith("--"):
            out.add(a)
        elif a.startswith("-") and len(a) > 1:
            out.update("-" + c for c in a[1:])
    return out


def _system(target: str) -> bool:
    return target in SYSTEM_PATHS or (target.rstrip("/") or "/") in SYSTEM_PATHS


def _segment(words: list[str]) -> Verdict | None:
    """一段简单命令：毁系统的照样 block（sudo rm -rf / 也是 block）；其次是沙盒做不到的；再其次 ask。"""
    first = next((w for w in words if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", w)), "")
    stripped = _strip(words)
    v = _rules(stripped)
    if v is not None and v.level == "block":
        return v
    prog = stripped[0] if stripped else ""
    if first.rsplit("/", 1)[-1] in NO_ROOT or prog in NO_ROOT:
        return Verdict("unsupported", "沙盒里没有 root 权限（sudo / su 用不了）")
    if prog in SYSTEM_PKG and not flags_only_query(prog, stripped[1:]):
        return Verdict("unsupported", "沙盒里不能装系统软件包（没有 root，apt 这类包管理器用不了）")
    return v


def _rules(words: list[str]) -> Verdict | None:
    if not words:
        return None
    prog, args = words[0], words[1:]
    flags = _flags(args)
    targets = [a for a in args if not a.startswith("-")]
    if prog == "rm":
        recursive = flags & {"-r", "-R", "--recursive"}
        if "--no-preserve-root" in flags or (recursive and any(_system(t) for t in targets)):
            return Verdict("block", "删除系统目录、整个工作区或家目录")
        if recursive:
            return Verdict("ask", "递归删除文件")
    if prog in ("chmod", "chown", "chgrp") and flags & {"-R", "--recursive"} and any(_system(t) for t in targets):
        return Verdict("block", "递归修改系统目录的权限")
    if prog in POWER or (prog == "init" and targets[:1] in (["0"], ["6"])) or \
            (prog == "systemctl" and targets[:1] and targets[0] in ("poweroff", "reboot", "halt")):
        return Verdict("block", "关机或重启")
    if DISK.match(prog):
        return Verdict("block", "格式化或改分区")
    if prog == "dd" and any(a.startswith("of=/dev/") and not a.startswith("of=/dev/null") for a in args):
        return Verdict("block", "直接写磁盘设备")
    if prog in ("kill", "pkill", "killall") and ("-1" in args[1:] or args[-1:] == ["-1"]):
        return Verdict("block", "杀掉所有进程")
    if prog == "git" and targets:
        sub = targets[0]
        if sub == "push":
            return Verdict("ask", "强制推送，会覆盖远端历史" if flags & {"-f", "--force", "--force-with-lease"} or
                           any(t.startswith("+") for t in targets[1:]) else "推送代码到远端仓库")
        if sub == "commit":
            return Verdict("ask", "提交代码")
        if sub == "reset" and "--hard" in flags:
            return Verdict("ask", "丢弃未提交的改动（git reset --hard）")
        if sub == "clean" and flags & {"-f", "--force"}:
            return Verdict("ask", "删除未跟踪的文件（git clean）")
    if prog in ("npm", "pnpm", "yarn") and targets[:1] == ["publish"] or prog == "twine" and targets[:1] == ["upload"]:
        return Verdict("ask", "发布软件包")
    return None


def verdict(command: str) -> Verdict | None:
    """block > unsupported > ask；都不是返回 None（直接执行）。"""
    if FORK_BOMB.search(command):
        return Verdict("block", "fork 炸弹")
    if RAW_DEVICE.search(command):
        return Verdict("block", "直接写磁盘设备")
    segs = _segments(command)
    found = [v for s in segs for v in [_segment(s)] if v] if segs is not None else []
    if segs is None and re.search(r"\brm\s+-[a-zA-Z]*[rR]", command):
        found.append(Verdict("ask", "递归删除文件"))
    if PIPE_TO_SHELL.search(command):
        found.append(Verdict("ask", "下载并直接执行脚本"))
    for level in ("block", "unsupported"):
        if (v := next((v for v in found if v.level == level), None)) is not None:
            return v
    return found[0] if found else None


def refusal(v: Verdict) -> str:
    """block 时给模型的话。"""
    return (f"这条命令被安全规则拦下了（{v.why}），没有执行，用户批准也不会放行。"
            "不要换个写法绕过；如果真有必要，向用户说明你想做什么、为什么，请他自己在服务器上操作。")


def unsupported(v: Verdict, environment: str) -> str:
    """unsupported 时给模型的话：没跑，告诉它能怎么做。environment 由调用方给（workspaces.ENVIRONMENT）。"""
    return f"这条命令没有执行：{v.why}。{environment}"
