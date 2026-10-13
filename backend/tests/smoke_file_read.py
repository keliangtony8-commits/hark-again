# 冒烟：v2.12 CORE 29 大文件安全读——app/file_read.py 唯一规则 + read_file mode=chars/lines/bytes。
# 1) 规则：行窗口（行号、CRLF、没有结尾换行、空文件、超范围报错、倒数 N 行、超长行截断、字节上限、跨块边界的汉字）、
#    数行、按字节对齐 UTF-8、字符分页不变；
# 2) 大文件（> STREAM_MIN）：按行读中间 / 尾巴、按字节读结尾，内存峰值远小于文件；默认字符分页改按行并说明；
# 3) 工具：参数校验、附件也能按行读、文档抽出的文字按行读；
# 4) 一轮（模拟模型）：read_file mode=lines offset=-3 读后台任务日志尾巴，时间线 detail = “第 a–b 行 / 共 N 行”。
# 运行：python tests/smoke_file_read.py
import os, sys, asyncio, subprocess, tempfile, json, tracemalloc
from pathlib import Path
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import file_read as F, storage, workspaces
from app.agent.runner import run_turn
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message
from app.storage import project_dir

# ---- 1. 规则 ----
t = "第一行\nsecond\r\nthird".encode()
w = F.window(t)
assert w.lines == [(1, "第一行"), (2, "second"), (3, "third")] and w.total == 3 and not w.cut and not w.capped
assert "已到结尾，共 3 行" in F.render(w) and F.render(w).startswith("1: 第一行\n2: second\n3: third")
assert F.window(t, 2, 1).lines == [(2, "second")] and "下一段用 mode=lines offset=3" in F.render(F.window(t, 2, 1))
assert F.window(t, -2).lines == [(2, "second"), (3, "third")]
assert F.window(t, -99).lines[0] == (1, "第一行")  # 倒数超过总行数 = 从头
assert F.window(t + b"\n").total == 3 and F.window(b"a\n\nb\n").lines == [(1, "a"), (2, ""), (3, "b")]
assert F.window(b"").total == 0 and F.render(F.window(b"")) == "（空文件）"
try:
    F.window(t, 9); raise AssertionError("超范围")
except F.ReadError as e:
    assert "只有 3 行" in str(e)
assert F.count_lines(b"") == 0 and F.count_lines(b"x") == 1 and F.count_lines(b"x\n") == 1 and F.count_lines(b"x\ny") == 2
long = ("y" * 9000 + "\nok\n").encode()
w = F.window(long)
assert w.cut and len(w.lines[0][1]) < F.LINE_CHARS + 40 and w.lines[1] == (2, "ok") and "mode=bytes" in F.render(w)
many = "".join(f"行{i:05d}\n" for i in range(1, 20001)).encode()
w = F.window(many, 1, F.LINES_MAX)
assert w.total == 20000 and len(w.lines) == F.LINES_MAX and not w.capped
w = F.window(("z" * 1500 + "\n").encode() * 100)
assert w.capped and 10 <= len(w.lines) < 20 and "输出到上限" in F.render(w)
assert F.window(many, 0).lines[0] == (1, "行00001")  # offset 0 当第 1 行
# 汉字跨 1 MB 块边界也不坏
edge = ("a" * (F.CHUNK - 1) + "汉字\n尾").encode()
w = F.window(edge)
assert w.lines[0][1].endswith("…（这行太长，只显示前 2000 字）") and w.lines[1] == (2, "尾")
edge2 = (("a" * (F.CHUNK - 1)) + "\n" + "汉" * 10 + "\n").encode()  # 第二行从块边界前后开始
assert F.window(edge2, 2).lines == [(2, "汉" * 10)]
# 字节
s = "汉字abc".encode()
txt, d = F.read_bytes(s, 1, 5)
assert txt.startswith("字\n") and "第 3–6 字节，共 9 字节" in txt and d == "第 3–6 字节 / 共 9"
txt, _ = F.read_bytes(s, -3)
assert txt.startswith("abc\n") and "已到结尾" in txt
txt, _ = F.read_bytes(s, 0, 4)
assert txt.startswith("汉\n") and "offset=3" in txt
assert F.read_bytes(s, 99)[0].startswith("\n…（第 9–9 字节")
# 字符分页（老行为）
assert F.page("abc") == "abc" and "下一段用 offset=200" in F.page("x" * 500, 0, 200)
assert F.read("x" * 50, "chars")[0] == "x" * 50
try:
    F.read("x", "pages"); raise AssertionError("mode")
except F.ReadError:
    pass

# ---- 2. 大文件 ----
big = Path(tmp) / "big.log"
line = "2026-10-13 12:00:00 INFO 处理第 {:07d} 条记录 ok\n"
with big.open("w") as f:
    for i in range(1, 400001):
        f.write(line.format(i))
size = big.stat().st_size
assert size > F.STREAM_MIN, size
tracemalloc.start()
w = F.window(big, 200000, 5)
txt_tail, d_tail = F.read(big, "lines", -3)
txt_b, _ = F.read(big, "bytes", -100)
txt_c, d_c = F.read(big, "chars")
peak = tracemalloc.get_traced_memory()[1]
tracemalloc.stop()
assert peak < 8 * 1024 * 1024, f"峰值 {peak} 太大（文件 {size}）"
assert w.lines[0] == (200000, "2026-10-13 12:00:00 INFO 处理第 0200000 条记录 ok") and w.total == 400000
assert txt_tail.startswith("399998: ") and "已到结尾，共 400000 行" in txt_tail and d_tail == "第 399998–400000 行 / 共 400000 行"
assert "0400000 条记录 ok" in txt_b and "已到结尾" in txt_b
assert txt_c.startswith("（文件有 ") and "改按行给" in txt_c and "1: 2026" in txt_c and d_c.startswith("第 1–")
txt_c2, _ = F.read(big, "chars", -10)
assert "最后 200 行" in txt_c2 and "400000: " in txt_c2

# ---- 3. 工具 ----
load_builtin()
WS = workspaces.PERSONAL
ws_root = project_dir(WS)
(ws_root / ".jobs/j1").mkdir(parents=True, exist_ok=True)
(ws_root / ".jobs/j1/log").write_text("".join(f"step {i}\n" for i in range(1, 51)) + "error: 磁盘满了\n")
(ws_root / "a.txt").write_text("一\n二\n三\n")
read = REGISTRY["read_file"].run
ctx = ToolContext(db=None, conversation_id="c-r")
async def call(**kw): return await read(ctx, **kw)
res = asyncio.run(call(path="a.txt", mode="lines", offset=2))
assert res.content.startswith("2: 二\n3: 三") and res.detail == "第 2–3 行 / 共 3 行", res.content
res = asyncio.run(call(path="a.txt", mode="lines", offset=8))
assert res.failed == "超出范围" and "只有 3 行" in res.content
res = asyncio.run(call(path="a.txt", mode="nope"))
assert res.failed == "参数不对"
res = asyncio.run(call(path="a.txt"))
assert res.content == "一\n二\n三\n" and res.detail is None  # 默认字符读法不变
res = asyncio.run(call(path="a.txt", mode="bytes", offset=4, limit=3))
assert res.content.startswith("二\n") and res.detail == "第 4–7 字节 / 共 12"
up = storage.save_upload("记录.csv", "".join(f"{i},v\n" for i in range(1, 101)).encode())
res = asyncio.run(call(attachment=up["id"], mode="lines", offset=-1))
assert res.content.startswith("100: 100,v") and "共 100 行" in res.content
schema = REGISTRY["read_file"].parameters["properties"]
assert schema["mode"]["enum"] == ["chars", "lines", "bytes"] and schema["limit"]["default"] == 0
assert "行号: " in REGISTRY["edit_file"].description

# ---- 4. 一轮（模拟模型）----
from app import llm
seen, script = [], []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append([dict(m) for m in messages])
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
        conv = Conversation(title="日志"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("任务 j1 最后报了什么错？")))
        await db.commit()
        return conv.id
cid = asyncio.run(seed())
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))
script.extend([[("read_file", {"path": ".jobs/j1/log", "mode": "lines", "offset": -3})], "最后一行：磁盘满了。"])
reply = asyncio.run(turn())
tool_msg = next(m for m in seen[1] if m["role"] == "tool")
assert tool_msg["content"].startswith("49: step 49\n50: step 50\n51: error: 磁盘满了"), tool_msg["content"]
assert [(x["tool"], x["state"], x.get("detail")) for x in reply.steps] == [("read_file", "done", "第 49–51 行 / 共 51 行")], reply.steps
print("smoke_file_read ok")
