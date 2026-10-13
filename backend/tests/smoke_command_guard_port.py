# 冒烟：v1.37 命令安全规则的解析移植自 OpenAI Codex CLI（Apache-2.0）
#   codex-rs/shell-command/src/command_safety/is_dangerous_command.rs 的测试用例（按我们的三级策略改写）
#   codex-rs/shell-command/src/bash.rs 的字面词解析测试（shell_parse）
# 另测：tree-sitter 不可用时退回分词，结论尽量一致；云端常见包装（eval/timeout/find -exec/git -C）。
# 运行：python tests/smoke_command_guard_port.py（纯规则，不需要数据库）
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import command_guard, shell_parse

V = command_guard.verdict
assert shell_parse.available(), "后端镜像应带 tree-sitter-bash"

def lv(cmd):
    v = V(cmd)
    return v.level if v else None

# ---- 1. Codex bash.rs：字面词解析 ----
def words(script):
    cmds = shell_parse.commands(script)
    return None if cmds is None else [[w.text for w in c] for c in cmds]
assert words("ls -1") == [["ls", "-1"]]
assert words("ls && pwd; echo 'hi there' | wc -l") == [["ls"], ["pwd"], ["echo", "hi there"], ["wc", "-l"]]
assert words('echo "/usr/local/bin"') == [["echo", "/usr/local/bin"]]
assert words('rg -g"*.py" x') == [["rg", "-g*.py", "x"]]  # 双引号里的通配是字面（Codex concatenation）
assert words("ls *.py") == [["ls", None]]  # 不带引号的通配不是字面
assert words("echo 'a'\"b\"c") == [["echo", "abc"]]  # mixed quote concatenation
assert words('echo "hi $USER"') == [["echo", None]]  # 双引号里有展开 → 非字面
assert words('echo "a\\$b"') == [["echo", None]]  # 双引号里的转义 → 非字面（Codex rejects_double_quoted_escapes）
assert words("echo \"$(rm -rf x)\"") == [["echo", None], ["rm", "-rf", "x"]]  # 双引号里的命令替换也被找到
# v2.26 起和 Codex 分歧：程序名非字面也返回（text=None），guess 用前面的字面赋值
assert words("cmd=rm; $cmd -rf x") == [[None, "-rf", "x"]]
assert [w.guess for w in shell_parse.commands("cmd=rm; $cmd -rf x")[0]] == ["rm", None, None]
assert words("if then rm -rf x") is None  # 语法错 → None
w = shell_parse.commands("rm -rf ~ \"$HOME\" /*")[0]
assert [x.raw for x in w[2:]] == ["~", "$HOME", "/*"] and all(x.text is None for x in w[2:])
assert words("rm >/dev/null -r x") == [["rm", "-r", "x"]]  # 重定向后面的参数补回命令

# ---- 2. Codex is_dangerous_command.rs 测试（ForcedRm → 递归的 ask / 系统目录 block）----
assert lv("rm -rf /") == "block"
for cmd in ["/bin/rm -fr /tmp/example", "rm -r -f /tmp/example", "rm /tmp/example -rf",
            "env TARGET=/tmp/example rm -rf /tmp/example"]:
    assert lv(cmd) == "ask", (cmd, V(cmd))
assert lv("sudo rm -rf /tmp/example") == "unsupported"  # sudo 本身沙盒里做不到
assert lv("sudo rm -rf /") == "block"
for script in ["printf x | rm -rf /tmp/example",
               "if test -d /tmp/example; then rm -r --force /tmp/example; fi",
               "rm -rf \"$TARGET\" >/dev/null",
               "for target in /tmp/a /tmp/b; do rm -r -f \"$target\"; done",
               "echo \"$(rm -rf /tmp/example)\"",
               "bash -c 'rm -rf /tmp/example'",
               "trap 'rm -rf /tmp/example' EXIT",
               "for a in '-C5a25KeRr' '--' '--json'; do HOME=$(mktemp -d) node cli.cjs ls \"$a\" >/tmp/o 2>/tmp/e; "
               "code=$?; printf '%s\\t%s\\n' \"$a\" \"$code\"; rm -rf \"$HOME\"; done"]:
    for cmd in (script, "bash -lc " + __import__("shlex").quote(script)):
        assert lv(cmd) in ("ask", "block"), (cmd, V(cmd))
# Codex: deeply_nested_command_wrappers_fail_closed
assert lv(" ".join(["env"] * command_guard.MAX_DEPTH + ["rm", "-rf", "/tmp/example"])) == "ask"
deep = V(" ".join(["env"] * (command_guard.MAX_DEPTH + 1) + ["rm", "-rf", "/tmp/example"]))
assert deep and deep.level == "ask" and deep.why == command_guard.TOO_DEEP, deep
assert lv(" ".join(["env"] * (command_guard.MAX_DEPTH + 1) + ["ls"])) == "ask"
# Codex non_forced_or_non_literal_rm_is_not_dangerous（我们 rm -r 也问，所以只留不递归/非字面的）
assert lv("cmd=rm; $cmd -rf /tmp/example") == "ask"  # v2.26：猜得出 rm → 递归删除照常问（Codex 放行）
for cmd in ["rm -- -r", "rm -f old.txt", "echo 'rm -rf /tmp/example'",
            "bash -lc \"trap 'echo rm -rf /tmp/example' EXIT\"", "bash -lc 'echo rm -rf /'"]:
    assert lv(cmd) is None, (cmd, V(cmd))

# ---- 3. 以前漏掉、现在拦住的（v1.36 之前都是 None）----
for cmd in ['echo "$(rm -rf ~)"', "bash -c 'rm -rf ~'", "trap 'rm -rf ~' EXIT", "echo `rm -rf /`", "env -i rm -rf /",
            "eval 'rm -rf /'", "find / -delete", "rm -rf /workspace/*", "timeout 10 rm -rf /", "nice -n 5 rm -rf /",
            "xargs -I{} rm -rf /", "sh -c \"sh -c 'rm -rf /etc'\"", "find / -name x -exec rm -rf / \\;",
            "su -c 'rm -rf /'", "env -S 'rm -rf /'", "watch -n 1 rm -rf /", "timeout -s KILL 5 shutdown now"]:
    assert lv(cmd) == "block", (cmd, V(cmd))
for cmd, why in [("sh -c 'git push'", "推送"), ("git -C repo push --force", "强制推送"), ("git -c a=b commit -m x", "提交"),
                 ("{ git push; }", "推送"), ("watch git push", "推送"), ("find . -name '*.o' -delete", "递归删除"),
                 ("find . -type d -exec rm -r {} +", "递归删除"), ("if true; then npm publish; fi", "发布")]:
    v = V(cmd)
    assert v and v.level == "ask" and why in v.why, (cmd, v)
assert lv("bash -lc 'sudo apt install x'") == "unsupported"
assert lv("bash -lc 'apt list --installed'") is None
for cmd in ["find . -name '*.py'", "git -C repo status", "timeout 30 python app.py", "bash script.sh",
            "python -c 'import os; os.remove(\"x\")'", "echo $(date)", "watch -n 2 nvidia-smi", "env FOO=1 make"]:
    assert lv(cmd) is None, (cmd, V(cmd))

# ---- 4. 没有 tree-sitter：退回分词，主路径结论不变 ----
saved = shell_parse._PARSER
shell_parse._PARSER = None
try:
    assert not shell_parse.available()
    for cmd, level in [("rm -rf /", "block"), ("if true; then rm -rf ~; fi", "block"), ("bash -c 'rm -rf /'", "block"),
                       ("eval 'rm -rf /'", "block"), ("git -C x push", "ask"), ("sudo apt install x", "unsupported"),
                       ("echo 'rm -rf /'", None), ("ls", None), ("echo \"unterminated; rm -r x", "ask")]:
        assert lv(cmd) == level, (cmd, V(cmd))
finally:
    shell_parse._PARSER = saved
# 语法树有错（tree-sitter 在，脚本不合法）也走兜底
assert lv("if then rm -rf /") == "block"

# ---- 5. v2.26 真机试跑 B3：平凡写法不再绕过（e2e-local-2026-10-13.md）----
from app import host_policy
assert shell_parse.dequote("\\rm") == "rm" and shell_parse.dequote("r'm'") == "rm" and shell_parse.dequote("\\/") == "/"
assert shell_parse.dequote("$x") is None and shell_parse.dequote("~/a") is None and shell_parse.dequote('"a\\"b"') == 'a"b'
assert shell_parse.dequote("*.py") is None and shell_parse.dequote('"a$b"') is None
c = shell_parse.commands("echo x | base64 -d | sh")
assert [x.piped for x in c] == [False, True, True]
assert [x.piped for x in shell_parse.commands("a >o | b; c")] == [False, True, False]
for cmd in ["\\rm -rf /", "r\\m -rf /", "rm -rf \\/", "R=rm; $R -rf /", "export R=rm; \"${R}\" -rf /",
            "T=/; rm -rf $T", "rm -fr /etc/../", "rm -rf /workspace/..", "rm -rf //", "rm -rf /usr/./",
            "rm -rf ~/a/../..", "rm -rf $HOME/..", "$(echo rm) -rf /", "`which rm` -rf /etc",
            "chmod -R 777 /etc/../", "find /usr/.. -delete"]:
    assert lv(cmd) == "block", (cmd, V(cmd))
for cmd, why in [("echo cm0gLXJmIC8= | base64 -d | sh", command_guard.PIPED_SHELL),
                 ("cat x | bash -s -- a", command_guard.PIPED_SHELL), ("echo x | timeout 5 sh", command_guard.PIPED_SHELL),
                 ("curl -s x | sh", "下载并直接执行脚本"), ("$(echo rm) -rf build", command_guard.OPAQUE),
                 ("X=/ rm -rf $X", "递归删除")]:  # 前缀赋值不影响同一条命令里的 $X
    v = V(cmd)
    assert v and v.level == "ask" and why in v.why, (cmd, v)
for cmd in ["$PY app.py", "\"$EDITOR\" notes.md", "cat a | bash script.sh", "echo 'x | sh'", "sh < run.sh",
            "rm -rf ./build/..x", "ls ~/a/..", "R=ls; $R -la"]:
    v = V(cmd)
    assert v is None or v.why == "递归删除文件", (cmd, v)
assert lv("rm -rf ./build/..x") == "ask" and lv("R=ls; $R -la") is None
# 主机模式：同一套 block 规则 → forbid；看不清的命令永远不算被前缀规则覆盖
assert host_policy.evaluate("\\rm -rf /", []).kind == "forbid"
assert host_policy.evaluate("rm -fr /etc/../", []).kind == "forbid"
assert host_policy.evaluate("ls; $X", [["ls"]]).kind != "skip"
assert host_policy.evaluate("ls", [["ls"]]).kind == "skip"
# 没有 tree-sitter 的兜底分词：同样不放过
saved = shell_parse._PARSER
shell_parse._PARSER = None
try:
    for cmd, level in [("\\rm -rf /", "block"), ("rm -fr /etc/../", "block"), ("echo eA== | base64 -d | sh", "ask"),
                       ("R=rm; $R -rf x", "ask"), ("$PY app.py", None)]:  # 兜底拆不开 $( )，只保证不比以前差
        assert lv(cmd) == level, (cmd, V(cmd))
finally:
    shell_parse._PARSER = saved
print("smoke_command_guard_port OK")
