# 冒烟：v2.72 B38 find_duplicates（app/duplicates.py ONLY “内容相同的文件”规则）。无迁移。
# 1) 规则：按大小 → 开头 64KB → 全文 SHA-256；名字不同内容相同算重复、名字相同内容不同不算；开头相同结尾不同不算；
#    空文件不算；include 过滤；隐藏 / 依赖目录跳过；组里像原件的排前；按可省字节排组；预算到顶如实说。
# 2) 一轮模拟模型（真机 r5 原样相册）：工具结果分组完整含 IMG_9001.jpg，计划模式也可用。
# 运行：python tests/smoke_duplicates.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', NEXT_SPEAKER_CHECK="off")
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from pathlib import Path
from app import duplicates, plan_mode, workspace_search
from app.storage import project_dir

WS = "dupws"
base = project_dir(WS)
def put(rel, data):
    p = base / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
night = os.urandom(3000); sea = os.urandom(5000); big = os.urandom(200_000)
put("相册/夜景.jpg", night); put("相册/夜景 副本.jpg", night)
put("相册/海边(1).jpg", sea); put("相册/IMG_9001.jpg", sea); put("相册/海边.jpg", sea)
put("相册/独一张.jpg", os.urandom(5000))                       # 同尺寸不同内容
put("相册/big.png", big); put("相册/big copy.png", big)
put("相册/big_tail.png", big[:-1] + bytes([big[-1] ^ 1]))       # 开头 64KB 相同、结尾不同
put("相册/空1.txt", b""); put("相册/空2.txt", b"")
put("相册/sub/海边.jpg", sea)                                    # 子目录也算
put("node_modules/x/a.jpg", sea); put(".spill/a.jpg", sea)       # 默认不进

r = duplicates.find(WS, "相册")
assert len(r.groups) == 3, r.groups
assert r.groups[0] == ["相册/big.png", "相册/big copy.png"], r.groups   # 可省 200KB 排最前
sea_g = r.groups[1]
assert sorted(sea_g) == sorted(["相册/海边(1).jpg", "相册/IMG_9001.jpg", "相册/海边.jpg", "相册/sub/海边.jpg"]), sea_g
assert sea_g[-1] == "相册/海边(1).jpg" and "相册/IMG_9001.jpg" in sea_g
assert r.groups[2] == ["相册/夜景.jpg", "相册/夜景 副本.jpg"], r.groups
assert r.empty == 2 and r.seen == 12, (r.empty, r.seen)
text = duplicates.render(WS, "相册", "", r)
for rel in ["相册/IMG_9001.jpg", "相册/夜景 副本.jpg", "相册/big copy.png", "相册/sub/海边.jpg"]:
    assert f"  - {rel}" in text, text
assert "其中有 3 组内容完全相同的文件，共 8 个" in text and "第 2 组：4 个" in text and "2 个空文件" in text, text
assert "独一张" not in text and "big_tail" not in text and "node_modules" not in text
r2 = duplicates.find(WS, "", "*.png")
assert r2.groups == [["相册/big.png", "相册/big copy.png"]], r2.groups
assert "没有内容完全相同" in duplicates.render(WS, "相册", "*.txt", duplicates.find(WS, "相册", "*.txt"))
r3 = duplicates.find(WS, "")   # 根目录：node_modules / .spill 不进
assert not any("node_modules" in p or ".spill" in p for g in r3.groups for p in g)
try:
    duplicates.find(WS, "", "*.jpg,*.png"); raise SystemExit("include list accepted")
except workspace_search.SearchError:
    pass
try:
    duplicates.find(WS, "没有这个"); raise SystemExit("missing path accepted")
except workspace_search.SearchError:
    pass
old = duplicates.HASH_BYTES_MAX
duplicates.HASH_BYTES_MAX = 50_000
r4 = duplicates.find(WS, "相册")
duplicates.HASH_BYTES_MAX = old
assert r4.hash_capped and ["相册/big.png", "相册/big copy.png"] not in r4.groups and len(r4.groups) == 2, r4.groups
assert "没比完" in duplicates.render(WS, "相册", "", r4)
assert duplicates._original_first("a/IMG_9001.jpg")[0] is False and duplicates._original_first("a/海边(1).jpg")[0]
assert "find_duplicates" in plan_mode.READ_TOOLS
print("duplicates rules ok")

# 2) 一轮模拟模型
from app import llm
from app.agent.runner import run_turn
from app.agent.tools import load_builtin, REGISTRY
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message
load_builtin()
assert "find_duplicates" in REGISTRY and not REGISTRY["find_duplicates"].deferred
from app.agent.subagent import CHILD_TOOLS
assert "find_duplicates" in CHILD_TOOLS

seen, script = [], []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
ids = iter(range(10_000))
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append(([dict(m) for m in messages], [t["function"]["name"] for t in (tools or [])]))
    step = script.pop(0)
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"c{next(ids)}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create

async def seed(ask):
    async with SessionLocal() as db:
        conv = Conversation(title="t"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks(ask)))
        await db.commit(); return conv.id, conv
async def turn(cid):
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))

cid, _ = asyncio.run(seed("相册里有没有内容完全一样的照片？先别删"))
import shutil
from app import workspaces
shutil.copytree(base / "相册", project_dir(workspaces.of(None)) / "相册")
script.extend([[("find_duplicates", {"path": "相册", "include": "*.jpg"})], "有 2 组。"])
reply = asyncio.run(turn(cid))
assert not script
msgs, names = seen[-1]
assert "find_duplicates" in seen[0][1]
tool_msgs = [m for m in msgs if m.get("role") == "tool"]
assert tool_msgs, msgs
out = str(tool_msgs[-1].get("content"))
assert "  - 相册/IMG_9001.jpg" in out and "第 1 组：4 个" in out, out
print("tool result:", out[:200].replace("\n", " | "))
print("smoke_duplicates OK")
