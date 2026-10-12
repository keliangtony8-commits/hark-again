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
assert words("cmd=rm; $cmd -rf x") == []  # 程序名非字面 → 跳过
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
for cmd in ["rm -- -r", "rm -f old.txt", "echo 'rm -rf /tmp/example'", "cmd=rm; $cmd -rf /tmp/example",
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
print("smoke_command_guard_port OK")
