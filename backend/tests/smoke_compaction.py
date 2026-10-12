# 冒烟：上下文压缩（滚动摘要）。模拟模型（不打真接口），预算调小到 100 字：
# 短对话不摘要 → 超预算时折叠一次（摘要进系统提示，旧原文不再发，摘要模型拿到的是缺口里的消息）→
# 下一轮还在余量内不再调摘要 → 再超时增量折叠（带上旧摘要）→ 摘要失败退化为硬截断、聊天照常 →
# 当前一问再长也是原文 → 摘要指向的消息被删（作废）后重新从头算。
# 运行：python tests/smoke_compaction.py
import os, sys, asyncio, subprocess, tempfile
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", HISTORY_CHARS="100")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from app import llm
from app.agent import loop, runner
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.llm import Turn
from app.models import Conversation, Message
from sqlalchemy import select

seen = []          # 主模型每轮看到的 (system, 非系统消息)
folds = []         # 摘要模型每次的输入
fold_fail = {"on": False}

async def fake_stream_turn(messages, tools=None, model=None, effort=None):
    seen.append((messages[0]["content"], [(m["role"], m["content"]) for m in messages[1:]]))
    yield "好"
    yield Turn(text="好")
loop.stream_turn = fake_stream_turn

async def fake_complete(messages, model=None):
    folds.append(messages[1]["content"])
    if fold_fail["on"]:
        raise RuntimeError("摘要网关挂了")
    return f"摘要{len(folds)}"
llm.complete = fake_complete

async def say(cid, text):
    async with SessionLocal() as db:
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks(text)))
        await db.commit()
        await runner.run_turn(db, await db.get(Conversation, cid))

async def main():
    async with SessionLocal() as db:
        conv = Conversation(); db.add(conv); await db.commit(); cid = conv.id

    await say(cid, "a" * 20)                      # 20 + 1
    assert folds == [] and "摘要" not in seen[-1][0]
    assert seen[-1][1] == [("user", "a" * 20)]

    for ch in "bcde":                              # 每轮 20+1 字，累计超过 100
        await say(cid, ch * 20)
    assert len(folds) == 1, folds
    assert "【已有摘要】\n（无）" in folds[0] and "a" * 20 in folds[0], folds[0]
    assert "这段对话更早的内容" in seen[-1][0] and "摘要1" in seen[-1][0]
    raw = seen[-1][1]
    assert sum(len(c) for _, c in raw) <= 100 and raw[-1] == ("user", "e" * 20), raw
    assert all("a" * 20 != c for _, c in raw)      # 已折叠的原文不再发
    async with SessionLocal() as db:
        conv = await db.get(Conversation, cid)
        assert conv.summary == "摘要1" and conv.summary_upto

    await say(cid, "f" * 20)                       # 折叠到 50% 留了余量：这一轮不再调摘要
    assert len(folds) == 1, folds

    for ch in "ghi":
        await say(cid, ch * 20)
    assert len(folds) == 2 and "【已有摘要】\n摘要1" in folds[1], folds   # 增量：带旧摘要，只给缺口
    assert "a" * 20 not in folds[1]
    assert "摘要2" in seen[-1][0]

    fold_fail["on"] = True                         # 摘要失败：硬截断，照样回复，摘要不变
    for ch in "jklm":
        await say(cid, ch * 20)
    assert len(folds) > 2 and all("摘要2" in f for f in folds[2:]), folds  # 每轮都重试过、带的还是旧摘要
    assert sum(len(c) for _, c in seen[-1][1]) <= 100 and seen[-1][1][-1] == ("user", "m" * 20)
    assert "摘要2" in seen[-1][0]
    fold_fail["on"] = False

    await say(cid, "Z" * 500)                      # 当前一问超预算也是原文
    assert seen[-1][1] == [("user", "Z" * 500)], seen[-1][1]

    async with SessionLocal() as db:               # 摘要指向的消息被删：作废并重新从头折叠
        conv = await db.get(Conversation, cid)
        await db.delete(await db.get(Message, conv.summary_upto)); await db.commit()
    n = len(folds)
    await say(cid, "y" * 20)
    assert len(folds) == n + 1 and "【已有摘要】\n（无）" in folds[-1] and "b" * 20 in folds[-1], folds[-1]

    # regenerate 只动原文区：重答后摘要还在
    async with SessionLocal() as db:
        conv = await db.get(Conversation, cid); before = (conv.summary, conv.summary_upto)
        _, _, gone = await runner.rewind(db, cid, None)
        conv = await db.get(Conversation, cid)
        assert gone and (conv.summary, conv.summary_upto) == before

asyncio.run(main())
print("compaction smoke OK")
