# 冒烟：v2.77 B45 交付后同一轮又改了源文件 → 收尾时卡片重拍成最终版（app/deliver.py refresh）。
# 1) 规则：没变不动；文件变了 → 同一个 upload id 换成新内容、size 跟上；同一路径交付两次只留最后一张；
#    源删了/变空 → 保留原快照；目录变了 → 重新打包；CSV 重拍仍加 BOM；不在 tracker 里的卡不碰。
# 2) 一轮（模拟模型）：写坏文件 → display_file → 覆盖成好文件 → 回答：落库的卡片下载到的是好文件。
# 运行：python tests/smoke_deliver_refresh.py
import os, sys, asyncio, subprocess, tempfile, json, time, zipfile
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import deliver as D, storage, workspaces
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message
from app.storage import project_dir

load_builtin()
WS = workspaces.PERSONAL
r0 = project_dir(WS)
r0.mkdir(parents=True, exist_ok=True)

def bump(p):  # 保证 mtime 变（有的文件系统精度粗）
    t = time.time() + 5
    os.utime(p, (t, t))

def body(b):
    return (storage.UPLOADS / b["id"] / b["name"]).read_bytes()

# ---- 1. 规则 ----
(r0 / "歌词_utf8.txt").write_text("ÇçÌì 乱码", encoding="utf-8")
tr = D.Tracker()
d1 = D.deliver(WS, "歌词_utf8.txt", tr)
assert d1.block["id"] in tr.seen
same = D.refresh(tr, [d1.block])
assert same == [d1.block]  # 没变不动
(r0 / "歌词_utf8.txt").write_text("晴天\n故事的小黄花\n", encoding="utf-8"); bump(r0 / "歌词_utf8.txt")
out = D.refresh(tr, [{"type": "text", "text": "已转好"}, d1.block])
assert out[0]["type"] == "text" and out[1]["id"] == d1.block["id"], out
assert body(out[1]).decode() == "晴天\n故事的小黄花\n" and out[1]["size"] == len("晴天\n故事的小黄花\n".encode())
assert len(list((storage.UPLOADS / d1.block["id"]).iterdir())) == 1  # 旧文件没留下
# 同一路径交付两次：只留最后一张
tr = D.Tracker()
a = D.deliver(WS, "歌词_utf8.txt", tr).block
b = D.deliver(WS, "./歌词_utf8.txt", tr).block
other = {"type": "file", "source": "upload", "id": "not-tracked", "name": "x.txt"}
out = D.refresh(tr, [a, {"type": "text", "text": "x"}, b, other])
assert [x.get("id") for x in out] == [None, b["id"], "not-tracked"], out
# 源删了 / 变空：保留原快照
(r0 / "临时.txt").write_text("v1", encoding="utf-8")
tr = D.Tracker(); c = D.deliver(WS, "临时.txt", tr).block
(r0 / "临时.txt").unlink()
assert D.refresh(tr, [c]) == [c] and body(c) == b"v1"
(r0 / "临时.txt").write_text("", encoding="utf-8"); bump(r0 / "临时.txt")
assert D.refresh(tr, [c]) == [c] and body(c) == b"v1"
# CSV 重拍仍加 BOM
(r0 / "表.csv").write_text("名字,分数\n张三,90\n", encoding="utf-8")
tr = D.Tracker(); s = D.deliver(WS, "表.csv", tr).block
(r0 / "表.csv").write_text("名字,分数\n张三,95\n", encoding="utf-8"); bump(r0 / "表.csv")
s2 = D.refresh(tr, [s])[0]
assert body(s2).startswith(b"\xef\xbb\xbf") and "95".encode() in body(s2)
# 目录：里面多了文件 → 重新打包
(r0 / "图").mkdir(exist_ok=True); (r0 / "图" / "a.txt").write_text("a", encoding="utf-8")
tr = D.Tracker(); z = D.deliver(WS, "图", tr).block
assert z["name"] == "图.zip"
(r0 / "图" / "b.txt").write_text("b", encoding="utf-8")
z2 = D.refresh(tr, [z])[0]
names = zipfile.ZipFile(storage.UPLOADS / z2["id"] / z2["name"]).namelist()
assert sorted(names) == ["a.txt", "b.txt"], names
# 没交付过东西：原样返回
assert D.refresh(D.Tracker(), [other]) == [other]

# ---- 1b. GBK 文字文件按 GBK 显示（file_read.decode，E2E w5 第二个问题）----
from app import file_read as FR
g = r0 / "歌词.txt"; g.write_bytes("晴天\n故事的小黄花\n".encode("gbk"))
text, det = FR.read(g)
assert text.startswith(FR.GBK_NOTE) and "故事的小黄花" in text and det == "GBK 编码", (text, det)
u = r0 / "u.txt"; u.write_text("普通 UTF-8", encoding="utf-8")
assert FR.read(u) == ("普通 UTF-8", None)
assert FR.decode(b"caf\xe9") is None  # Latin-1 不是中文：不硬按 GBK
assert FR.decode(b"a\0b") is None and FR.decode("\ufeff你好".encode("utf-8")) == ("你好", "")
from app import attachment_save
ud = storage.UPLOADS / "gbkup"; ud.mkdir(parents=True, exist_ok=True); (ud / "歌词.txt").write_bytes("晴天\n".encode("gbk") * 20000)
h = attachment_save.hint([{"type": "file", "source": "upload", "id": "gbkup", "name": "歌词.txt"}])
assert "歌词.txt 是 GBK 编码" in h, h
ud2 = storage.UPLOADS / "u8up"; ud2.mkdir(parents=True, exist_ok=True); (ud2 / "a.txt").write_text("你好", encoding="utf-8")
assert "GBK" not in attachment_save.hint([{"type": "file", "source": "upload", "id": "u8up", "name": "a.txt"},
                                          {"type": "file", "source": "upload", "id": "../x", "name": "b.txt"}])
from app.archives import decode_text
assert decode_text("考试通知：周五".encode("gbk")) == ("考试通知：周五", "按 GBK 解码")

# ---- 2. 一轮（模拟模型）----
from app import llm
script = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    step = script.pop(0)
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"c{len(script)}-{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
async def seed():
    async with SessionLocal() as db:
        conv = Conversation(title="转码"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("帮我把歌词转成正常编码发我")))
        await db.commit()
        return conv.id
cid = asyncio.run(seed())
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))
script.extend([[("write_file", {"path": "歌.txt", "content": "ÇçÌì"})], [("display_file", {"paths": ["歌.txt"]})],
               [("write_file", {"path": "歌.txt", "content": "晴天"})], "已转好，内容是《晴天》。"])
reply = asyncio.run(turn())
files = [b for b in reply.blocks if b["type"] == "file"]
assert len(files) == 1 and body(files[0]).decode() == "晴天", (files, body(files[0]))
async def stored():
    async with SessionLocal() as db:
        m = await db.get(Message, reply.id)
        return [b for b in m.blocks if b["type"] == "file"]
assert (stored_files := asyncio.run(stored()))
assert stored_files[0]["size"] == len("晴天".encode())
print("smoke_deliver_refresh ok")
