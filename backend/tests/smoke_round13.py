# 冒烟：v2.63 E2E 第十三轮两处修复（无迁移）。
# B33 模型用 zip 命令打的包中文名没标 UTF-8 → 交付快照时重写名字并标 UTF-8（GBK 包 / 加密包不碰，工作区原件不动）。
# B34 “9 点到 21 点每 2 小时”被拆成 7 个任务 → cron_merge.merge 合并；schedule_task create 同内容只差钟点 → 不建，给出合并后的 cron。
# 运行：python tests/smoke_round13.py
import os, sys, asyncio, tempfile, subprocess, zipfile, struct
from types import SimpleNamespace as NS
from cryptography.fernet import Fernet
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY=Fernet.generate_key().decode(), DATA_DIR=tmp,
  TIMEZONE="Asia/Shanghai")
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from app import cron_merge, deliver, storage
from app.agent.tools import REGISTRY, load_builtin
from app.db import SessionLocal

run = asyncio.run

# ---- B34 cron_merge ----
m = cron_merge.merge
assert m(["0 9 * * *", "0 11 * * *", "0 13 * * *"]) == "0 9-13/2 * * *"
assert m([f"0 {h} * * *" for h in (21, 9, 15, 11, 13, 17, 19)]) == "0 9-21/2 * * *"
assert m(["30 8 * * *", "30 12 * * *", "30 18 * * *"]) == "30 8,12,18 * * *"
assert m(["0 9 * * *", "0 10 * * *", "0 11 * * *"]) == "0 9-11 * * *"
assert m(["0 9 * * *", "0 21 * * *"]) == "0 9,21 * * *"
assert m(["0 9 * * 1-5", "0 18 * * 1-5"]) == "0 9,18 * * 1-5"
assert m(["0 9 * * *", "30 18 * * *"]) is None          # 分钟不同
assert m(["0 9 * * 1", "0 18 * * 2"]) is None           # 星期不同
assert m(["0 9-12 * * *", "0 18 * * *"]) is None        # 小时已是范围
assert m(["0 9 * * *"]) is None and m(["0 9 * *", "0 10 * *"]) is None

# ---- B34 schedule_task create ----
load_builtin()
st = REGISTRY["schedule_task"]
assert "'0 9-21/2 * * *'" in st.description and "不要一个时刻建一个" in st.description

async def b34():
    async with SessionLocal() as db:
        ctx = NS(db=db, task_id=None, project_id=None)
        r = await st.run(ctx, action="create", name="喝水提醒", prompt="提醒我：该喝水了。", cron="0 9 * * *")
        assert r.content.startswith("已安排"), r.content
        r = await st.run(ctx, action="create", name="喝水", prompt="提醒我：该喝水了。", cron="0 11 * * *")
        assert r.content.startswith("没建") and "cron='0 9,11 * * *'" in r.content and "action=update id=" in r.content, r.content
        r = await st.run(ctx, action="create", name="喝水", prompt="提醒我：该喝水了。", cron="30 15 * * *")  # 分钟不同 → 各管各的
        assert r.content.startswith("已安排"), r.content
        r = await st.run(ctx, action="create", name="背单词", prompt="提醒我：背单词。", cron="0 11 * * *")  # 内容不同
        assert r.content.startswith("已安排"), r.content
        r = await st.run(ctx, action="create", name="喝水", prompt="提醒我：该喝水了。", run_at="2099-01-01 09:00")  # 一次性不合并
        assert r.content.startswith("已安排"), r.content
        r = await st.run(ctx, action="create", name="喝水", prompt="提醒我：该喝水了。", cron="0 9 * * *")  # 一模一样 → twin
        assert r.content.startswith("一模一样"), r.content
run(b34())

# ---- B33 zip 中文名 ----
ws = "me"
d = storage.project_dir(ws); d.mkdir(parents=True, exist_ok=True)

def raw_zip(path, names, enc):
    """真 Info-ZIP 在 C locale 下打包（名字原始字节、不标 UTF-8）；enc=gbk 时磁盘上的名字就是 GBK 字节。"""
    src = tempfile.mkdtemp()
    for n in names:
        f = os.path.join(os.fsencode(src), n.encode(enc))
        os.makedirs(os.path.dirname(f), exist_ok=True)
        open(f, "wb").write(f"内容 {n}".encode())
    top = sorted({n.encode(enc).split(b"/")[0] for n in names})
    subprocess.run([b"zip", b"-qrD", os.fsencode(str(path)), *top], cwd=src, check=True,
                   env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})

raw_zip(d / "班级照片.zip", ["班级照片/说明.txt", "班级照片/IMG_0001.jpg", "readme.txt"], "utf-8")
with zipfile.ZipFile(d / "班级照片.zip") as z:
    assert not any(i.flag_bits & 0x800 for i in z.infolist()) and "班级照片/说明.txt" not in z.namelist()
before = (d / "班级照片.zip").read_bytes()
dv = deliver.deliver(ws, "班级照片.zip")
snap = storage.UPLOADS / dv.block["id"] / dv.block["name"]
with zipfile.ZipFile(snap) as z:
    assert sorted(z.namelist()) == sorted(["班级照片/说明.txt", "班级照片/IMG_0001.jpg", "readme.txt"]), z.namelist()
    assert all(i.flag_bits & 0x800 for i in z.infolist() if not i.filename.isascii())
    assert z.read("班级照片/说明.txt") == "内容 班级照片/说明.txt".encode() and z.testzip() is None
assert (d / "班级照片.zip").read_bytes() == before, "工作区原件不该动"
assert dv.block["size"] == snap.stat().st_size

raw_zip(d / "gbk.zip", ["成绩/张三.txt"], "gbk")            # 真 GBK 包：不碰
dv = deliver.deliver(ws, "gbk.zip")
assert (storage.UPLOADS / dv.block["id"] / dv.block["name"]).read_bytes() == (d / "gbk.zip").read_bytes()
with zipfile.ZipFile(d / "ok.zip", "w") as z:              # Python 打的包本来就标了：不碰
    z.writestr("照片/a.txt", "x")
dv = deliver.deliver(ws, "ok.zip")
assert (storage.UPLOADS / dv.block["id"] / dv.block["name"]).read_bytes() == (d / "ok.zip").read_bytes()
(d / "bad.zip").write_bytes(b"PK\x03\x04 not a zip")         # 坏包：原样交付，不留 .fix
dv = deliver.deliver(ws, "bad.zip")
assert not list((storage.UPLOADS / dv.block["id"]).glob("*.fix"))
assert "中文文件名也不乱码" in REGISTRY["display_file"].description
print("smoke_round13 OK")
