# 冒烟：v1.38 长输出落盘回炉——用例移植自 deepseek-ai/deepseek-harness（MIT）
#   packages/spill/spill-local/tests/spill-local.spec.ts（encodeSegment / saveTextFile / cleanup sweep）
#   packages/spill/spill-policy/tests/{retention,notice,spill-policy}.spec.ts（预留说明、≤ 上限、失败退化、识别说明）
# 再加我们自己的：沿用已有落盘文件不存第二份、切口落在换行处。
import os
import sys
import tempfile
import time
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{_tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
                  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s" * 32, VAULT_KEY="", DATA_DIR=_tmp)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import spill  # noqa: E402
from app.storage import project_dir  # noqa: E402

pid = "f" * 32
root = project_dir(pid)
root.mkdir(parents=True, exist_ok=True)
sp = root / spill.SPILL_DIR

# ---- encodeSegment（spill-local.spec.ts 'encodeSegment'）----
assert spill.encode_segment("web_fetch.txt") == "web_fetch.txt"
assert spill.encode_segment("a-B_9.z") == "a-B_9.z"
assert spill.encode_segment("../etc/passwd", 99) == "..~002Fetc~002Fpasswd"
assert spill.encode_segment("a/b") == "a~002Fb"
assert spill.encode_segment("~") == "~007E"
assert spill.encode_segment(".") == "~002E" and spill.encode_segment("..") == "~002E~002E"
assert spill.encode_segment("") == "~"
assert spill.encode_segment("😀") == "~D83D~DE00"  # 按 UTF-16 码元转义，与原实现一致
assert spill.encode_segment("中文名") != spill.encode_segment("中文明")  # 可逆 → 不撞
e = spill.encode_segment("中" * 30)
assert len(e) <= 40 and e.count("~") == len(e) // 5, e  # 截短只截在完整转义单元之间
assert spill.NAME_RE.match(f"20261012-081500-{spill.encode_segment('a/../../x y')}-abcd.txt")

# ---- saveTextFile ----
p = spill.save(pid, "r.txt", "héllo")
assert (root / p).read_text(encoding="utf-8") == "héllo" and p.startswith(".spill/") and spill.NAME_RE.match(p[7:]), p
p = spill.save(pid, "../../evil", "x")
assert (root / p).parent == sp and "/.." not in p, p  # 穿越形状的名字变成一个叶子
a, b = spill.save(pid, "r.txt", "a"), spill.save(pid, "r.txt", "b")
assert a != b and (root / a).read_text() == "a" and (root / b).read_text() == "b"
# 独占创建：随机后缀撞上已存在的文件就换一个，绝不覆盖
real = spill.secrets.token_hex
seq = iter(["dead", "dead", "beef"])
spill.secrets.token_hex = lambda n: next(seq)
c1 = spill.save(pid, "same", "first")
c2 = spill.save(pid, "same", "second")
spill.secrets.token_hex = real
assert c1.endswith("-dead.txt") and c2.endswith("-beef.txt") and (root / c1).read_text() == "first", (c1, c2)

# ---- cleanup sweep（spill-local.spec.ts 'startup cleanup sweep'）----
for f in sp.iterdir():
    f.unlink()
DAY = 86400


def aged(name: str, days: float) -> Path:
    f = sp / name
    f.write_text("x")
    t = time.time() - days * DAY
    os.utime(f, (t, t))
    return f


old = aged("20260801-000000-old-0001.txt", 40)
fresh = aged("20261011-000000-fresh-0002.txt", 1)
boundary = aged("20260912-000000-edge-0003.txt", 30)
os.utime(boundary, (time.time() - 30 * DAY + 60,) * 2)  # 差一分钟才到 30 天：留下（只删严格更早的）
lookalike = aged("notes-old.txt", 400)  # 不是我们的名字形状：不碰
os.mkdir(sp / "20260101-000000-dir-0004.txt")  # 目录：不碰
target = Path(tempfile.mkdtemp()) / "outside.txt"
target.write_text("keep")
os.utime(target, (time.time() - 400 * DAY,) * 2)
os.symlink(target, sp / "20260101-000000-link-0005.txt")  # 符号链接：不跟随、不删
spill.save(pid, "trigger", "t")
assert not old.exists() and fresh.exists() and boundary.exists() and lookalike.exists()
assert (sp / "20260101-000000-dir-0004.txt").is_dir() and target.read_text() == "keep"
assert (sp / "20260101-000000-link-0005.txt").is_symlink()
# DAYS = 0：不按时间清
old2 = aged("20250101-000000-ancient-0006.txt", 400)
spill.DAYS = 0
spill.save(pid, "trigger", "t")
assert old2.exists()
spill.DAYS = 30
# 数量兜底 KEEP：只算我们的文件
spill.KEEP = 3
for i in range(5):
    spill.save(pid, "n", str(i))
assert len([f for f in sp.iterdir() if spill.NAME_RE.match(f.name) and f.is_file() and not f.is_symlink()]) == 3
assert lookalike.exists()
spill.KEEP = 50
# 清理出错不连累落盘（warn sink 抛错也被吞掉的同一原则）
real_scandir = spill.os.scandir
spill.os.scandir = lambda d: (_ for _ in ()).throw(PermissionError("nope"))
q = spill.save(pid, "still", "saved")
spill.os.scandir = real_scandir
assert (root / q).read_text() == "saved"
# 并发删除：别人先删了也算成功
real_unlink = spill.os.unlink


def racing(path):
    real_unlink(path)
    real_unlink(path)  # 第二次 → FileNotFoundError，被当作已删


spill.KEEP = 1
spill.os.unlink = racing
spill.save(pid, "race", "r")
spill.os.unlink = real_unlink
spill.KEEP = 50

# ---- cut（retention.spec.ts）----
h, t, o = spill.cut("AB", 100)
assert (h, t, o) == ("AB", "", 0)  # 不重叠、不重复
h, t, o = spill.cut("A" * 20 + "C" * 20, 10)
assert (h, t, o) == ("AAAAA", "CCCCC", 30)
assert spill.cut("雪x", 0) == ("", "", 2)  # 预算被说明吃光：全省略
h, t, o = spill.cut("ABCDE", 3)
assert len(h) == 2 and len(t) == 1 and o == 2  # 开头 ceil、结尾 floor
lines = "".join(f"line {i:04d} " + "x" * 40 + "\n" for i in range(400))
h, t, o = spill.cut(lines, 2000)
assert h.endswith("\n") and t.startswith("line ") and len(h) + len(t) <= 2000  # 我们的：切在换行处

# ---- bound：严格 ≤ limit、预留最坏说明（spill-policy.spec.ts）----
for f in list(sp.iterdir()):
    if f.is_file() and not f.is_symlink():
        f.unlink()
assert spill.bound("短", 100) == "短"
for limit in (300, 1000, 1601, 16000):
    for n in (limit + 1, limit * 3, limit * 50):
        text = ("abc\n" * n)[:n]
        for ws in (None, pid):
            out = spill.bound(text, limit, ws, "web_fetch")
            assert len(out) <= limit, (limit, n, ws, len(out))
            assert "中间省略" in out
            assert (".spill/" in out) == (ws is not None), out[-300:]
# 说明本身放不下：原样保留
big = "z" * 500
assert spill.bound(big, 60, pid, "tiny") == big
# 存不下（磁盘满）：只截断，绝不声称全文存在某处
real_save = spill.save
spill.save = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
out = spill.bound("q" * 5000, 1000, pid, "x")
spill.save = real_save
assert ".spill" not in out and "grep" in out and len(out) <= 1000
# 全文确实落盘了，说明里的数字对得上
text = "".join(f"{i}\n" for i in range(20000))
out = spill.bound(text, 2000, pid, "run")
path, total = spill.existing(out)
assert (root / path).read_text() == text and total == len(text)

# ---- 识别已有说明（notice.spec.ts）+ 沿用原文件 ----
n = spill.notice(42, ".spill/20261012-081500-run_command-abcd.txt", 99999)
assert spill.existing("head" + n + "tail") == (".spill/20261012-081500-run_command-abcd.txt", 99999)
for bad in ("", "普通输出（中间省略）", spill.notice(42, None, 10),
            n.replace("abcd", "zz"), n.replace(".spill/", "/etc/"), n.replace("99999", "-1"),
            n.replace("20261012-081500-", "../../")):
    assert spill.existing(bad) is None, bad
before = {f.name for f in sp.iterdir()}
wrapped = "退出码 0\n" + "A" * 9000 + n + "B" * 9000
out = spill.bound(wrapped, 4000, pid, "run_command")
assert {f.name for f in sp.iterdir()} == before, "已落过盘的结果不该再存一份"
assert ".spill/20261012-081500-run_command-abcd.txt" in out and "完整内容（99999 字符）" in out and len(out) <= 4000
print("smoke_spill_port OK")
