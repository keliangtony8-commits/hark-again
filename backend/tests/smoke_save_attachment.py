# 冒烟：v2.10 CORE 28 附件存进工作区——app/attachment_save.py 唯一规则 + save_attachment 工具。
# 1) target：默认 uploads/<原名>、以 / 结尾 / 已有目录放进去、/workspace/… 绝对路径、工作区外 / ../ / 隐藏目录拒绝；
# 2) save：字节一致、同内容再存 = 直接用、不同内容重名 → “名字 (2)”、配额满拒绝且不留文件、编号不对拒绝、
#    记进整轮改动（撤销删掉）、file_seen 认得（之后可以直接覆盖）、不留 .part 临时文件；
# 3) 历史：带附件的消息补“附件编号 … save_attachment”，二进制附件说“读不了内容”；
# 4) 一轮（模拟模型）：模型直接按名调用（按需加载的工具），文件进个人工作区，时间线 detail = 路径，本对话全部文件列为“助手写的”。
# 运行：python tests/smoke_save_attachment.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import attachment_save as A, conversation_files, file_seen, quota, storage, turn_changes, workspaces
from app.agent import context
from app.agent.runner import run_turn
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message
from app.storage import project_dir

WS = workspaces.PERSONAL
root_dir = project_dir(WS)
root_dir.mkdir(parents=True, exist_ok=True)

# ---- 1. target ----
T = lambda p: A.target(root_dir, "a.zip", p).relative_to(root_dir).as_posix()
assert T("") == "uploads/a.zip" and T("  ") == "uploads/a.zip" and T("/workspace") == "uploads/a.zip"
assert T("data/") == "data/a.zip" and T("data/b.zip") == "data/b.zip" and T("/workspace/x/y.zip") == "x/y.zip"
assert T("/workspace/x/") == "x/a.zip"
(root_dir / "box").mkdir()
assert T("box") == "box/a.zip"
for bad in ("/etc/passwd", "../out.zip", ".jobs/a.zip", "src/.git/x", ".home/"):
    try:
        A.target(root_dir, "a.zip", bad); raise AssertionError(bad)
    except A.SaveError as e:
        assert str(e), bad

# ---- 2. save ----
blob = bytes(range(256)) * 400  # 100 KB 二进制
up = storage.save_upload("数据.zip", blob)
tr = turn_changes.Tracker()
owner = file_seen.owner_of("c-x", None)
s = A.save(WS, up["id"], "", tr, owner)
assert s.rel == "uploads/数据.zip" and not s.reused and not s.renamed and s.size == len(blob)
assert (root_dir / s.rel).read_bytes() == blob
assert not list((root_dir / "uploads").glob(".*.part")), "临时文件残留"
again = A.save(WS, up["id"], "", tr, owner)
assert again.reused and again.rel == s.rel and "没再复制" in A.for_model(again)
up2 = storage.save_upload("数据.zip", b"different")
s2 = A.save(WS, up2["id"], "", tr, owner)
assert s2.rel == "uploads/数据 (2).zip" and s2.renamed and (root_dir / s2.rel).read_bytes() == b"different"
assert "换了名字" in A.for_model(s2) and "/workspace/uploads/数据 (2).zip" in A.for_model(s2)
assert A.save(WS, up2["id"], "", tr, owner).rel == "uploads/数据 (2).zip"  # 同内容的 (2) 直接用
# file_seen：存进来的文件算“看过”，之后 write_file 可以直接覆盖
file_seen.check_write(owner, root_dir / s.rel, s.rel)
for bad in ("nope", "../../etc", ""):
    try:
        A.save(WS, bad); raise AssertionError(bad)
    except A.SaveError as e:
        assert "没有这个附件" in str(e)
real_check = quota.check
def full(ws, adding=0): raise quota.QuotaError("工作区满了")
quota.check = full
try:
    A.save(WS, up["id"], "full/", None, None); raise AssertionError("quota")
except A.SaveError as e:
    assert "没有存" in str(e) and "满了" in str(e)
quota.check = real_check
assert not (root_dir / "full").exists()
# 整轮撤销删掉这一轮存进来的文件
card = turn_changes.finish(tr, WS)
assert card and {f["path"] for f in card["files"]} == {"uploads/数据.zip", "uploads/数据 (2).zip"}, card
turn_changes.undo(WS, card["token"])
assert not (root_dir / s.rel).exists() and not (root_dir / s2.rel).exists()

# ---- 3. 历史里的提示 ----
def fb(u, mime=None): return {"type": "file", "source": "upload", "id": u["id"], "name": u["name"], "mime": mime or u["mime"], "size": u["size"]}
img = storage.save_upload("图.png", b"\x89PNG\r\n\x1a\n" + b"0" * 20)
t = context._render([{"type": "text", "text": "解压一下"}, fb(up), fb(img)])
assert f"数据.zip = {up['id']}" in t and f"图.png = {img['id']}" in t and "save_attachment" in t, t
assert "读不了内容" in t and "暂不能" not in t
assert "附件编号" not in context._render([{"type": "text", "text": "你好"}])
assert "附件编号" not in context._render([{"type": "text", "text": "看"}, {"type": "file", "source": "project", "id": "a.txt", "name": "a.txt"}])

# ---- 4. 一轮（模拟模型）----
from app import llm
load_builtin()
assert REGISTRY["save_attachment"].deferred
seen, script = [], []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append(([dict(m) for m in messages], [t["function"]["name"] for t in tools or []]))
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
        conv = Conversation(title="解压"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("帮我解压") + [fb(up)]))
        await db.commit()
        return conv.id
cid = asyncio.run(seed())
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))
script.extend([[("save_attachment", {"attachment": up["id"], "path": "in/"})], "存好了，在 in/数据.zip。"])
reply = asyncio.run(turn())
msgs, names = seen[0]
assert "save_attachment" not in names and "deferred_tool" in names, names
first_user = next(m for m in msgs if m["role"] == "user")
assert up["id"] in str(first_user["content"]) and "save_attachment" in str(first_user["content"])
tool_msg = next(m for m in seen[1][0] if m["role"] == "tool")
assert "已把附件 数据.zip 存到 in/数据.zip" in tool_msg["content"], tool_msg
assert (root_dir / "in/数据.zip").read_bytes() == blob
assert [(x["tool"], x["state"], x.get("detail")) for x in reply.steps] == [("save_attachment", "done", "in/数据.zip")], reply.steps
async def files():
    async with SessionLocal() as db:
        from sqlalchemy import select
        conv = await db.get(Conversation, cid)
        rows = (await db.execute(select(Message).where(Message.conversation_id == cid).order_by(Message.created_at))).scalars().all()
        return conversation_files.collect(conv, rows)
items = asyncio.run(files())
assert any(i["origin"] == "written" and i["name"] == "数据.zip" for i in items), items
assert any(i["origin"] == "sent" and i["name"] == "数据.zip" for i in items), items
print("smoke_save_attachment ok")
