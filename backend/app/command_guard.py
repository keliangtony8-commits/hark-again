"""命令安全规则的唯一入口：run_command（前台/后台）执行前都先问 verdict(command)。

三级（优先级 block > unsupported > ask）：
  block  永远不执行（批准也不行）：毁掉系统或整盘、关机、fork 炸弹、杀光进程……
         沙盒本身有资源和权限隔离，这一层是“别让模型一句手滑把工作区/容器搞没”的第二道防线。
  unsupported  沙盒里根本做不到、跑了只会白白报错一轮的：sudo / su、apt / dnf / yum / apk 装系统软件
         （容器非 root）。不执行，直接告诉模型能怎么装（pip / npm 落到工作区，系统软件看预装清单）。
  ask    执行前在聊天里弹审批卡等用户点头：推送代码、递归删除、发布软件包、curl | sh……

v1.37 起解析移植自 OpenAI Codex CLI（Apache-2.0）的 is_dangerous_command.rs + bash.rs：
  - shell_parse 用 tree-sitter-bash 拆出整段脚本里每条简单命令的字面词：管道、if/for/while 体、
    $( ) / 反引号（含双引号里的）都看得到；单引号里的是数据（`echo 'rm -rf /'` 不误伤）。
  - 包装命令递归看里面那条：sudo、env（-i / -u / A=B / --）、trap 的动作、bash/sh -c/-lc 的脚本，
    外加 Codex 没有、云端常见的 eval、timeout/nice/nohup/watch/xargs 的参数、find -exec / -delete、
    git -C x 这类全局选项。递归超过 MAX_DEPTH 层按 Codex 的 fail closed → ask。
  - 和 Codex 的分歧：Codex 把任何 rm -f 都当危险；云端工作区里删单个文件很常见，这里只拦递归删除
    （系统目录 → block，其余 → ask）。
  语法树有错或没装 tree-sitter → 退回 shlex 分词（剥掉 if/then/do 这类关键字），引号不配对再退回整串正则。

v2.26（真机试跑 B3：护栏能被平凡写法绕过）——“看不清”不再等于“安全”：
  - 程序名用 Word.value：`\\rm`、`r\\m` 去掉转义就是 rm；`R=rm; $R -rf /` 用前面的字面赋值猜出 rm。
  - 还是猜不出的程序名（`$(echo rm) -rf /`）：参数是递归 + 系统目录 → block，带递归或系统目录 → ask（_opaque）。
  - 目标先规范化（_normalize）：/etc/../、/workspace/.. 都是 /；~/.. 越过家目录也算系统目录。
  - 管道里把前一条输出交给 shell 从标准输入执行（`… | base64 -d | sh`）一律 ask，不只 curl/wget。
"""
import posixpath
import re
import shlex
from dataclasses import dataclass

from . import shell_parse
from .shell_parse import Word

MAX_DEPTH = 8  # Codex MAX_DANGEROUS_COMMAND_WRAPPER_DEPTH
SEPARATORS = {";", "&&", "||", "|", "&", "\n", "(", ")", "|&"}
KEYWORDS = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!", "{", "}", "case", "esac", "time"}
# 只是改一下运行方式、真正的命令在后面的包装：值 = 带一个参数值的选项
WRAPPERS = {
    "nohup": set(), "command": set(), "exec": set(), "builtin": set(), "busybox": set(),
    "nice": {"-n", "--adjustment"}, "ionice": {"-c", "-n", "-p", "--class", "--classdata"},
    "stdbuf": {"-i", "-o", "-e"}, "time": {"-f", "-o", "--format", "--output"},
    "watch": {"-n", "--interval", "-d"}, "setsid": set(), "chrt": set(), "taskset": set(), "unbuffer": set(),
    "xargs": {"-I", "-n", "-P", "-d", "-L", "-a", "-E", "-s", "--max-args", "--max-procs", "--delimiter",
              "--arg-file", "--replace"},
    "timeout": {"-s", "-k", "--signal", "--kill-after"},
}
SHELLS = {"bash", "sh", "zsh", "dash", "ash", "ksh"}
# 删了就等于毁掉系统或整个家目录的目标
SYSTEM_PATHS = {"/", "/*", "~", "~/", "~/*", "$HOME", "${HOME}", "$HOME/", "$HOME/*", "${HOME}/*", "/home", "/root",
                "/etc", "/usr", "/var", "/bin", "/sbin", "/boot", "/lib", "/lib64", "/opt", "/srv", "/proc", "/sys",
                "/dev", "/workspace", "/workspace/", "/workspace/*", "$WORKSPACE", "${WORKSPACE}", "$WORKSPACE/*"}
NO_ROOT = {"sudo", "su", "doas"}
SYSTEM_PKG = {"apt", "apt-get", "aptitude", "dpkg", "dnf", "yum", "apk", "pacman", "zypper", "snap"}
POWER = {"shutdown", "reboot", "halt", "poweroff"}
DISK = re.compile(r"^(mkfs(\.\w+)?|mke2fs|wipefs|fdisk|sfdisk|parted|mkswap)$")
FORK_BOMB = re.compile(r":\s*\(\s*\)\s*\{[^}]*:\s*\|\s*:[^}]*&[^}]*\}")
RAW_DEVICE = re.compile(r">\s*/dev/(sd|nvme|vd|xvd|hd|mmcblk)\w*")
PIPE_TO_SHELL = re.compile(r"\b(curl|wget)\b[^|;&]*\|\s*(sudo\s+)?(ba|z|da)?sh\b")
ASSIGN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")
TOO_DEEP = "命令套了太多层包装，看不清到底要做什么"
PIPED_SHELL = "把前一条命令的输出当脚本直接执行"
OPAQUE = "程序名要到运行时才知道（变量或命令替换），参数又像递归处理或动系统目录"
OPAQUE_SYSTEM = "程序名要到运行时才知道，参数却在递归处理系统目录"
HOME_PREFIXES = ("~", "$HOME", "${HOME}", "$WORKSPACE", "${WORKSPACE}")


@dataclass(frozen=True)
class Verdict:
    level: str  # "block" | "unsupported" | "ask"
    why: str


def _segments(command: str) -> list[list[Word]] | None:
    """兜底分词（tree-sitter 不可用或语法树有错时）。"""
    try:
        lex = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=";&|()")
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:  # 引号不配对
        return None
    out: list[shell_parse.Command] = []
    cur = shell_parse.Command()
    piped = False
    for t in tokens:
        if t in SEPARATORS or set(t) <= set(";&|()"):
            if cur:
                out.append(cur)
            cur = shell_parse.Command()
            piped = t in ("|", "|&") or (piped and t in ("(", ")"))
            cur.piped = piped
        elif not cur and (t in KEYWORDS or ASSIGN.fullmatch(t)):
            continue  # if / then / do / A=B 前缀
        else:
            cur.append(_fallback_word(t))
    if cur:
        out.append(cur)
    return out


def _fallback_word(t: str) -> Word:
    return Word(None, t) if "$" in t or "`" in t else Word(t, t)


def _parse(script: str) -> list[list[Word]] | None:
    """整段脚本 → 每条命令的词（shell_parse.Command，带 piped）。None = 连兜底分词都拆不开（引号不配对）。"""
    cmds = shell_parse.commands(script)
    if cmds is not None:
        return cmds
    segs = _segments(script)
    return None if segs is None else segs


def _name(w: Word) -> str:
    return (w.value or "").rsplit("/", 1)[-1]  # /bin/rm → rm


def _arg(w: Word) -> str:
    return w.value if w.value is not None else w.raw


def flags_only_query(prog: str, args: list[str]) -> bool:
    """只是查询（dpkg -l、apt list --installed、apt show x）不需要 root，照常放行。"""
    if prog == "dpkg":
        return bool(args) and args[0] in ("-l", "-L", "-s", "--list", "--listfiles", "--status", "-S", "--search")
    return prog in ("apt", "apt-get") and bool(args) and args[0] in ("list", "show", "search", "policy")


def _flags(args: list[str]) -> set[str]:
    out = set()
    for a in args:
        if a == "--":
            break  # Codex rm_args_include_force_option：-- 之后都是文件名
        if a.startswith("--"):
            out.add(a)
        elif a.startswith("-") and len(a) > 1:
            out.update("-" + c for c in a[1:])
    return out


def _targets(args: list[str]) -> list[str]:
    out, after = [], False
    for a in args:
        if a == "--" and not after:
            after = True
        elif after or not a.startswith("-"):
            out.append(a)
    return out


def _normalize(target: str) -> str:
    """/etc/../ → /、//usr/./ → /usr、~/a/../.. → /（越过家目录）；相对路径原样。"""
    for pre in HOME_PREFIXES:
        if target == pre or target.startswith(pre + "/"):
            depth, parts = 0, []
            for part in target[len(pre):].split("/"):
                if part in ("", "."):
                    continue
                if part == "..":
                    if not parts:
                        return "/"  # 越过家目录 / 工作区
                    parts.pop()
                else:
                    parts.append(part)
            return pre + "".join("/" + p for p in parts)
    if target.startswith("/"):
        return "/" + posixpath.normpath(target).lstrip("/")
    return target


def _system(target: str) -> bool:
    for t in (target, _normalize(target)):
        if t in SYSTEM_PATHS or (t.rstrip("/") or "/") in SYSTEM_PATHS:
            return True
    return False


def _opaque(args: list[str]) -> list[Verdict]:
    """程序名猜不出：不当安全（v2.26 前整条跳过）。递归 + 系统目录 → block；有其一 → ask。"""
    flags = _flags(args)
    recursive = bool(flags & {"-r", "-R", "--recursive", "--no-preserve-root"})
    system = any(_system(t) for t in _targets(args))
    if recursive and system:
        return [Verdict("block", OPAQUE_SYSTEM)]
    return [Verdict("ask", OPAQUE)] if recursive or system else []


def _skip_options(words: list[Word], with_value: set[str]) -> list[Word]:
    """跳过包装命令自己的选项（-n 5、-oL、--signal=KILL），返回真正要跑的那条。"""
    i = 0
    while i < len(words):
        a = _arg(words[i])
        if a == "--":
            return words[i + 1:]
        if not a.startswith("-") or a == "-":
            break
        i += 2 if a in with_value else 1
    return words[i:]


def _script(script: str, depth: int) -> list[Verdict]:
    cmds = _parse(script)
    if cmds is None:
        return [Verdict("ask", "递归删除文件")] if re.search(r"\brm\s+-[a-zA-Z]*[rR]", script) else []
    return [v for c in cmds for v in _exec(c, depth + 1, getattr(c, "piped", False))]


def _exec(words: list[Word], depth: int, piped: bool = False) -> list[Verdict]:
    """一条简单命令（可能是包装）：返回它和它包着的命令命中的全部规则。piped = 标准输入来自管道前一段。"""
    if depth > MAX_DEPTH:
        return [Verdict("ask", TOO_DEEP)]
    while words and words[0].text is not None and ASSIGN.fullmatch(words[0].text):
        words = words[1:]  # 兜底分词里的 A=B 前缀
    if not words:
        return []
    rest = words[1:]
    args = [_arg(w) for w in rest]
    if words[0].value is None:
        return _opaque(args)
    prog = _name(words[0])

    if prog in ("sudo", "doas"):
        inner = _skip_options(rest, {"-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "--user", "--group"})
        return [Verdict("unsupported", "沙盒里没有 root 权限（sudo / su 用不了）"), *_exec(inner, depth + 1, piped)]
    if prog == "su":
        found = [Verdict("unsupported", "沙盒里没有 root 权限（sudo / su 用不了）")]
        for i, a in enumerate(args[:-1]):
            if a in ("-c", "--command"):
                found += _script(args[i + 1], depth)
        return found
    if prog == "env":  # Codex dangerous_command_match_for_env，加上 -u NAME
        i = 0
        while i < len(args):
            a = args[i]
            if a == "--":
                i += 1
                break
            if a in ("-i", "--ignore-environment", "-0", "--null") or (ASSIGN.fullmatch(a) and not a.startswith("-")):
                i += 1
            elif a in ("-u", "--unset", "-C", "--chdir", "-S", "--split-string"):
                if a in ("-S", "--split-string") and i + 1 < len(args):
                    return _script(args[i + 1], depth)
                i += 2
            else:
                break
        return _exec(rest[i:], depth + 1, piped)
    if prog == "timeout":
        inner = _skip_options(rest, WRAPPERS["timeout"])
        return _exec(inner[1:], depth + 1, piped)  # 第一个是时长
    if prog in WRAPPERS:
        return _exec(_skip_options(rest, WRAPPERS[prog]), depth + 1, piped and prog != "xargs")
    if prog == "trap":  # Codex dangerous_command_match_for_trap：动作是一段 shell 源码
        i = 1 if args[:1] == ["--"] else 0
        return _script(args[i], depth) if i < len(args) and not args[i].startswith("-") else []
    if prog == "eval":
        return _script(" ".join(args), depth) if args else []
    if prog in SHELLS:
        for i, a in enumerate(args):
            if a.startswith("-") and not a.startswith("--") and "c" in a[1:]:
                return _script(args[i + 1], depth) if i + 1 < len(args) else []
            if a.startswith("-") and not a.startswith("--") and "s" in a[1:]:
                break  # -s：后面都是位置参数，脚本从标准输入读
            if a == "--":
                if i + 1 < len(args):
                    return []  # bash -- script.sh
                break
            if not a.startswith("-"):
                return []  # bash script.sh：跑的是文件
        # 从标准输入读脚本（只有选项或 -s）。管道里 = 前一条命令的输出直接当脚本执行
        return [Verdict("ask", PIPED_SHELL)] if piped else []
    if prog == "find":
        return _find(rest, depth)
    v = _rules(prog, args)
    if v is not None:
        return [v]
    if prog in SYSTEM_PKG and not flags_only_query(prog, args):
        return [Verdict("unsupported", "沙盒里不能装系统软件包（没有 root，apt 这类包管理器用不了）")]
    return []


def _find(rest: list[Word], depth: int) -> list[Verdict]:
    args = [_arg(w) for w in rest]
    paths = []
    for a in args:
        if a.startswith("-") or a in ("(", "!", ")"):
            break
        paths.append(a)
    found: list[Verdict] = []
    if "-delete" in args:
        found.append(Verdict("block", "删除系统目录、整个工作区或家目录") if any(_system(p) for p in paths)
                     else Verdict("ask", "递归删除文件"))
    i = 0
    while i < len(args):
        if args[i] in ("-exec", "-execdir", "-ok", "-okdir"):
            j = i + 1
            while j < len(args) and args[j] not in (";", "+", "\\;"):
                j += 1
            inner = [w for w in rest[i + 1:j] if _arg(w) != "{}"]
            found += _exec(inner, depth + 1)
            i = j
        i += 1
    return found


def _rules(prog: str, args: list[str]) -> Verdict | None:
    flags = _flags(args)
    targets = _targets(args)
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
    if prog == "git":
        return _git(args)
    if prog in ("npm", "pnpm", "yarn") and targets[:1] == ["publish"] or prog == "twine" and targets[:1] == ["upload"]:
        return Verdict("ask", "发布软件包")
    return None


def _git(args: list[str]) -> Verdict | None:
    i = 0
    while i < len(args) and args[i].startswith("-"):  # git -C repo / -c k=v / --no-pager push
        i += 2 if args[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") else 1
    if i >= len(args):
        return None
    sub, rest = args[i], args[i + 1:]
    flags, targets = _flags(rest), _targets(rest)
    if sub == "push":
        forced = flags & {"-f", "--force", "--force-with-lease"} or any(t.startswith("+") for t in targets)
        return Verdict("ask", "强制推送，会覆盖远端历史" if forced else "推送代码到远端仓库")
    # v2.44 B17：commit 只动本地仓库（reflog / reset 能撤回），用户让提交就直接提交；离开本机的 push 才问。
    if sub == "reset" and "--hard" in flags:
        return Verdict("ask", "丢弃未提交的改动（git reset --hard）")
    if sub == "clean" and flags & {"-f", "--force"}:
        return Verdict("ask", "删除未跟踪的文件（git clean）")
    return None


def verdicts(command: str) -> list[Verdict]:
    """整条命令里命中的全部规则（源码顺序）；host_policy 要分开看 block 和 ask（主机上 sudo/apt 不算问题）。"""
    if FORK_BOMB.search(command):
        return [Verdict("block", "fork 炸弹")]
    if RAW_DEVICE.search(command):
        return [Verdict("block", "直接写磁盘设备")]
    found = _script(command, -1)
    if PIPE_TO_SHELL.search(command):  # curl | sh 说得更具体，替掉通用的那句
        found = [v for v in found if v.why != PIPED_SHELL] + [Verdict("ask", "下载并直接执行脚本")]
    return found


def verdict(command: str) -> Verdict | None:
    """block > unsupported > ask；都不是返回 None（直接执行）。"""
    found = verdicts(command)
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
