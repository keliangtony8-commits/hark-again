# v2.29 E2E B6：超长输出中间省略处不再把一行拦腰截断（sandbox runner / host-agent / user_shell / spill 同一条规则）。
import importlib.util, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "sandbox"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


import tempfile  # noqa: E402
os.environ.setdefault("SANDBOX_TOKEN", "t"); os.environ.setdefault("HOST_PROJECTS_DIR", tempfile.mkdtemp())
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///" + tempfile.mkdtemp() + "/t.db"); os.environ.setdefault("LLM_BASE_URL", "http://x"); os.environ.setdefault("LITELLM_MASTER_KEY", "k")
os.environ.update(OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s" * 32, VAULT_KEY="", DATA_DIR=os.environ["HOST_PROJECTS_DIR"])
import types  # noqa: E402
_d = types.ModuleType("docker"); _d.from_env = lambda: None
_e = types.ModuleType("docker.errors"); _e.NotFound = type("NotFound", (Exception,), {}); _d.errors = _e
sys.modules.setdefault("docker", _d); sys.modules.setdefault("docker.errors", _e)
import runner  # noqa: E402
host = load("host_agent", os.path.join(ROOT, "deploy", "host-agent", "host_agent.py"))
from app import spill, user_shell  # noqa: E402

full = "".join(f"{i}\n" for i in range(1, 200001))
lines = set(full.splitlines())

# 1) 三份 line_snap 是同一条规则
cases = [("abc\ndef\ngh", "ij\nkl\nmn"), ("x" * 100, "y" * 100), ("", ""), ("a\n", "\nb"), ("1\n" * 50, "2\n" * 50)]
for h, t in cases:
    assert runner.line_snap(h, t) == host.line_snap(h, t) == spill.line_snap(h, t), (h, t)
# 一整行特别长：找不到换行就照原样
assert runner.line_snap("a" * 1000, "b" * 1000) == ("a" * 1000, "b" * 1000)
assert runner.SNAP == host.SNAP == spill.SNAP

# 2) sandbox HeadTail：seq 1 200000 那种输出，开头结尾都是完整行，省略数对得上
b = runner.HeadTail(runner.MAX_OUTPUT)
for i in range(0, len(full), 4096):
    b.push(full[i:i + 4096])
head, tail, omitted = b.cut()
assert head.split("\n")[-1] in lines and tail.split("\n")[0] in lines, (head[-20:], tail[:20])
assert head.startswith("1\n2\n") and tail.endswith("200000\n")
assert omitted == len(full) - len(head) - len(tail) and omitted > b.omitted
# 切口在中间：head 的最后一行 + 1 = 被省略的第一行；tail 第一行之前那行被省略
last = int(head.split("\n")[-1]); first = int(tail.split("\n")[0])
assert full[len(head) + 1:].startswith(f"{last + 1}\n")
assert full.endswith(tail) and not head.endswith("\n")
out = head + runner.SPILL_MARK + tail
assert "\n…（中间省略）…\n" in out and "\n\n" not in out
# 没省略：text() 原样
b2 = runner.HeadTail(100); b2.push("a\nb\n"); assert b2.omitted == 0 and b2.text() == "a\nb\n"

# 3) host-agent HeadTail
ht = host.HeadTail(12000)
for i in range(0, len(full), 3000):
    ht.push(full[i:i + 3000])
o, om = ht.result()
pre, post = o.split("\n…（中间省略 ")
assert pre.split("\n")[-1] in lines and post.split("）…\n", 1)[1].split("\n")[0] in lines
assert om == len(full) - len(pre) - len(post.split("）…\n", 1)[1]) and f"省略 {om} 字符" in o
ht = host.HeadTail(10); ht.push("abcdefghijKLMNOP")  # 没有换行：照旧
o, om = ht.result(); assert o.startswith("abcde") and o.endswith("LMNOP") and om == 6

# 4) user_shell._clip（用户 ! 命令进历史那份）
c = user_shell._clip(full, 10000)
pre, rest = c.split("\n…（中间省略 ")
n, post = rest.split(" 字符）…\n", 1)
assert pre.split("\n")[-1] in lines and post.split("\n")[0] in lines
assert int(n) == len(full) - len(pre) - len(post) and len(c) < 10100
assert user_shell._clip("short") == "short"
print("smoke_line_snap OK")
