# 冒烟：v2.65 交付的 CSV 加 UTF-8 BOM（e2e o8，无迁移）。规则全在 app/csv_bom.py；deliver 只改快照 / 包里副本。
# 运行：python tests/smoke_csv_bom.py
import os, sys, io, tempfile, zipfile, asyncio
from types import SimpleNamespace as NS
from cryptography.fernet import Fernet
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY=Fernet.generate_key().decode(), DATA_DIR=tmp,
  TIMEZONE="Asia/Shanghai")
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import csv_bom, deliver, storage

BOM = b"\xef\xbb\xbf"
nb = lambda b: csv_bom.needs_bom(io.BytesIO(b))
# ---- 规则 ----
assert nb("姓名,数学\n张三,92\n".encode())
assert not nb(b"name,math\nzhang,92\n")                       # 纯 ASCII 不碰
assert not nb(BOM + "姓名\n".encode())                          # 已有 BOM
assert not nb(b"\xff\xfe" + "姓名".encode("utf-16-le"))        # UTF-16
assert not nb("姓名,数学\n".encode("gbk"))                      # 真 GBK 不碰
assert not nb(b"")
# 跨块边界切在多字节字中间仍算 UTF-8；尾部截断的半个字 → 不是合法 UTF-8
big = ("a" * (csv_bom.CHUNK - 1)).encode() + "中".encode() + b"\n"
assert nb(big)
assert not nb("中".encode()[:2])
# 后面才出现非 ASCII（第一块全 ASCII）
assert nb(b"x" * (csv_bom.CHUNK + 5) + "王".encode())
assert csv_bom.wants("成绩.CSV") and csv_bom.wants("a.tsv") and not csv_bom.wants("a.txt")

# ---- deliver：单个文件 ----
ws = "me"
root = storage.project_dir(ws)
root.mkdir(parents=True, exist_ok=True)
raw = "姓名,数学\n张三,92\n".encode()
(root / "成绩.csv").write_bytes(raw)
d = deliver.deliver(ws, "成绩.csv")
snap = storage.upload_path(d.block["id"])
assert snap.read_bytes() == BOM + raw, snap.read_bytes()[:10]
assert d.block["size"] == len(raw) + 3
assert "BOM" in d.note and "Excel" in d.note
assert (root / "成绩.csv").read_bytes() == raw                  # 工作区原件不动
assert not list(snap.parent.glob("*.bom"))
# ASCII / GBK / 已有 BOM / 非 csv：原样
for name, data in (("en.csv", b"a,b\n1,2\n"), ("gbk.csv", "姓名\n".encode("gbk")), ("has.csv", BOM + raw),
                   ("notes.txt", raw)):
    (root / name).write_bytes(data)
    d = deliver.deliver(ws, name)
    assert storage.upload_path(d.block["id"]).read_bytes() == data, name
    assert "BOM" not in d.note, name

# ---- deliver：打包目录 ----
(root / "报表").mkdir()
(root / "报表" / "一班.csv").write_bytes(raw)
(root / "报表" / "en.csv").write_bytes(b"a\n")
(root / "报表" / "说明.txt").write_bytes(raw)
d = deliver.deliver(ws, "报表")
with zipfile.ZipFile(storage.upload_path(d.block["id"])) as z:
    assert z.read("一班.csv") == BOM + raw
    assert z.read("en.csv") == b"a\n" and z.read("说明.txt") == raw
    assert z.getinfo("一班.csv").compress_type == zipfile.ZIP_DEFLATED
    assert z.testzip() is None
assert "1 个 CSV" in d.note, d.note
assert (root / "报表" / "一班.csv").read_bytes() == raw

# ---- display_file 工具把说明带给模型 ----
from app.agent.builtin.workspace import display_file
from app.agent.tools import REGISTRY, load_builtin
load_builtin()
assert "BOM" in REGISTRY["display_file"].description
r = asyncio.run(display_file(NS(workspace=ws), paths=["成绩.csv"]))
assert r.blocks and "BOM" in r.content, r.content
print("smoke_csv_bom OK")
