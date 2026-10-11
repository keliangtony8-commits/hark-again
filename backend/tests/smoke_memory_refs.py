# 冒烟：记忆按条引用（v0.70）。不调真模型，向量接口模拟（同文同向量、不同文正交；也测接口挂了的退路）：
# 上下文每条记忆带 #短引用 → update_memory 按引用改（向量清空、出 updated 卡带 previous）→ 引用找不到/太短/有歧义不乱改 →
# remember 新记出 saved 卡、重复不出卡、相似覆盖出 updated 卡 → forget 按多条引用删 + 关键词兜底，出 forgotten 卡（删前快照）→
# 卡片过 blocks.Block 校验、blocks_to_text 给模型一行摘要。
# 运行：python tests/smoke_memory_refs.py
import os, sys, asyncio, subprocess, tempfile
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from pydantic import TypeAdapter
from sqlalchemy import select
from app import llm, memory_store
from app.blocks import Block, blocks_to_text
from app.db import SessionLocal
from app.models import Memory
from app.agent.tools import REGISTRY, ToolContext, load_builtin
load_builtin()
from app.agent.context import build_system_prompt

vocab: dict[str, int] = {}
down = {"on": False}
async def fake_embed(texts):
    if down["on"]:
        raise RuntimeError("向量接口挂了")
    out = []
    for t in texts:
        key = t.replace("真的", "")  # “真的不吃香菜”与“不吃香菜”算同义
        i = vocab.setdefault(key, len(vocab))
        out.append([1.0 if j == i else 0.0 for j in range(64)])
    return out
llm.embed = fake_embed
check = TypeAdapter(Block)

async def main():
    async with SessionLocal() as db:
        ctx = ToolContext(db=db)
        call = lambda name, **kw: REGISTRY[name].run(ctx, **kw)
        db.add_all([Memory(id="aaaa1111" + "0" * 24, category="food", content="不吃辣"),
                    Memory(id="bbbb2222" + "0" * 24, category="profile", content="大二学生"),
                    Memory(id="bbbb3333" + "0" * 24, category="work", content="学计算机")])
        await db.commit()

        sp = await build_system_prompt(db, None, "")
        assert "- [food] 不吃辣 (#aaaa1111)" in sp and "update_memory" in sp, sp

        # 按引用改
        r = await call("update_memory", ref="#AAAA1111", content="能吃一点微辣", category="food")
        assert r.content.startswith("已修改（原来是：不吃辣）"), r.content
        m = await db.get(Memory, "aaaa1111" + "0" * 24)
        assert m.content == "能吃一点微辣" and m.embedding is None
        b = check.validate_python(r.blocks[0]).model_dump()
        assert b["action"] == "updated" and b["items"][0]["previous"] == "不吃辣" and b["items"][0]["content"] == "能吃一点微辣"
        # 找不到 / 太短 / 歧义 → 不改
        for bad in ["#zzzz9999", "#aa", "#bbbb"]:
            r = await call("update_memory", ref=bad, content="x")
            assert "找不到" in r.content and not r.blocks, (bad, r.content)
        assert (await db.get(Memory, "bbbb2222" + "0" * 24)).content == "大二学生"

        # remember：新记 / 重复 / 同义覆盖
        r = await call("remember", content="不吃香菜", category="food")
        assert r.content == "已记住。" and r.blocks[0]["action"] == "saved" and r.blocks[0]["items"][0]["id"]
        saved_id = r.blocks[0]["items"][0]["id"]
        r = await call("remember", content="不吃香菜", category="food")
        assert r.content == "已经记过了。" and not r.blocks
        r = await call("remember", content="真的不吃香菜", category="food")
        assert r.blocks[0]["action"] == "updated" and r.blocks[0]["items"][0] == {
            "id": saved_id, "content": "真的不吃香菜", "category": "food", "previous": "不吃香菜"}, r.blocks
        # 向量接口挂了照样能记（退回精确查重）
        down["on"] = True
        r = await call("remember", content="早上八点有课", category="bogus")
        assert r.blocks[0]["action"] == "saved" and r.blocks[0]["items"][0]["category"] == "general"
        down["on"] = False

        # forget：多条引用 + 关键词兜底 + 坏引用报出来
        r = await call("forget", refs=["#bbbb2222", saved_id[:8], "#nope0000"], keyword="早上")
        b = check.validate_python(r.blocks[0]).model_dump()
        assert b["action"] == "forgotten" and {i["content"] for i in b["items"]} == {"大二学生", "真的不吃香菜", "早上八点有课"}, b
        assert "#nope0000" in r.content
        left = {m.content for m in (await db.scalars(select(Memory))).all()}
        assert left == {"能吃一点微辣", "学计算机"}, left
        r = await call("forget", keyword="不存在的事")
        assert r.content == "没有找到相关记忆。" and not r.blocks
        r = await call("forget")
        assert r.content == "没有找到相关记忆。"

        text = blocks_to_text([b])
        assert text.startswith("[已忘掉：") and "大二学生" in text, text
        print("smoke_memory_refs OK")

asyncio.run(main())
