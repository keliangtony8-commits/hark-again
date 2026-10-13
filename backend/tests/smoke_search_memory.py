# 冒烟：v2.11 大脑 (au) 翻记忆——memory_store.search / overflow_note / relevant 字面退路 + search_memory 工具。模拟模型，无迁移。
# - 拆“词”：中文两字一组、英文按单词小写；overlap 比例；
# - relevant：≤30 条全带；多了且向量不可用 → 按字面重合排（以前只取最近 12 条，老记忆永远看不到）；向量可用 → 余弦；profile 始终带；
# - search：引号整词、分类过滤、空 query 列分类、limit 上限、向量命中标“意思相近”、无命中提示、向量缺失时的提示；
# - 上下文：记忆超过 30 条时提示总数和 search_memory；不超过不提；
# - 一轮对话：模型并行调 search_memory（两次）→ 结果带 # 引用；再 update_memory 改那条；时间线 detail；计划模式 / 子助手可用；系统提示。
# 运行：python tests/smoke_search_memory.py
import os, sys, asyncio, subprocess, tempfile, json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from sqlalchemy import select
from app import llm, memory_store as ms, plan_mode
from app.agent import runner, subagent
from app.agent.context import build_system_prompt
from app.agent.tools import REGISTRY, load_builtin
from app.blocks import text_to_blocks
from app.config import settings
from app.db import SessionLocal
from app.models import Conversation, Memory, Message

def run(c):
    return LOOP.run_until_complete(c)
LOOP = asyncio.new_event_loop()

# --- 拆词 ---
assert ms.grams("我对花生过敏") == {"我对", "对花", "花生", "生过", "过敏"}
assert ms.grams("Likes Oat-Milk 2 x") == {"likes", "oat", "milk"}
assert ms.grams("猫") == {"猫"} and ms.grams("") == set()
assert ms.overlap("花生", "对花生过敏") == 1.0 and ms.overlap("", "x") == 0.0
assert 0 < ms.overlap("花生酱好吃", "花生过敏") < 1
assert ms.overflow_note(30, 30) == "" and "共 40 条" in ms.overflow_note(40, 13) and "search_memory" in ms.overflow_note(40, 13)

# --- 准备：40 条记忆，花生过敏那条最老 ---
NOW = datetime.now(timezone.utc)
EMB = {"过敏": [1, 0, 0], "坚果": [0.9, 0.1, 0], "咖啡": [0, 1, 0]}
def vec(text):
    for k, v in EMB.items():
        if k in text:
            return list(map(float, v))
    return [0.0, 0.0, 1.0]
embed_ok = [False]
calls = [0]
async def fake_embed(texts):
    calls[0] += 1
    if not embed_ok[0]:
        raise RuntimeError("no embeddings")
    return [vec(t) for t in texts]
llm.embed = fake_embed

async def seed():
    async with SessionLocal() as db:
        db.add(Memory(id="m" * 8 + "old1", category="food", content="对花生过敏，吃了会起疹子",
                      created_at=NOW - timedelta(days=90), updated_at=NOW - timedelta(days=90)))
        db.add(Memory(id="p" * 8 + "prof", category="profile", content="叫小王，在读研究生",
                      created_at=NOW - timedelta(days=80), updated_at=NOW - timedelta(days=80)))
        db.add(Memory(id="c" * 8 + "cof1", category="food", content="喜欢燕麦拿铁 Oat latte",
                      created_at=NOW - timedelta(days=70), updated_at=NOW - timedelta(days=70)))
        for i in range(37):
            db.add(Memory(id=f"z{i:07d}fill", category="general", content=f"杂事第{i}条：周{i % 7}要交作业",
                          created_at=NOW - timedelta(hours=i), updated_at=NOW - timedelta(hours=i)))
        await db.commit()
run(seed())

async def rel(q):
    async with SessionLocal() as db:
        return [m.content for m in await ms.relevant(db, q)]
r = run(rel("我能吃花生吗"))
assert len(r) == 1 + ms.TOP_K and "叫小王，在读研究生" == r[0], r  # profile 先
assert r[1] == "对花生过敏，吃了会起疹子", r  # 向量不可用 → 字面把最老的那条顶上来
assert run(rel("")) == run(rel("  "))  # 空 query → 最近 30 条
assert len(run(rel(""))) == ms.ALWAYS_ALL

# --- search，向量不可用 ---
async def S(q, cat=None, limit=ms.SEARCH_LIMIT):
    async with SessionLocal() as db:
        hits, total, vectors = await ms.search(db, q, cat, limit)
        return hits, total, vectors, ms.search_text(q, cat, hits, total, vectors)
hits, total, vectors, text = run(S("花生"))
assert total == 40 and not vectors and [h.memory.id for h in hits] == ["mmmmmmmmold1"], text
assert "#mmmmmmmm" in text and "更新于" in text and "update_memory" in text, text
hits, *_ , text = run(S("坚果"))
assert hits == [] and "没找到" in text and "只按字面" in text, text
hits, total, _, text = run(S("", "food"))
assert total == 2 and [h.memory.id for h in hits] == ["cccccccccof1", "mmmmmmmmold1"] and "最近更新的 2 条" in text, text
hits, total, *_ = run(S("作业", limit=100))
assert len(hits) == ms.LIMIT_MAX and total == 40
hits, *_ = run(S("作业", limit=0))
assert len(hits) == ms.SEARCH_LIMIT  # 0 / 空 = 默认
hits, *_ = run(S("作业", limit=1))
assert len(hits) == 1
hits, *_ = run(S('"oat LATTE"'))
assert [h.memory.id for h in hits] == ["cccccccccof1"]
hits, *_ = run(S("作业", "food"))
assert hits == []
hits, total, _, text = run(S("", "travel"))
assert total == 0 and "是空的" in text

# --- 向量可用：意思相近也命中，补齐向量并提交 ---
embed_ok[0] = True
hits, total, vectors, text = run(S("坚果"))
assert vectors and [h.memory.id for h in hits] == ["mmmmmmmmold1"] and hits[0].near and not hits[0].words, text
assert "（意思相近）" in text
async def stored():
    async with SessionLocal() as db:
        return [m.embedding for m in (await db.scalars(select(Memory))).all()]
assert all(stored_v for stored_v in run(stored()))  # 懒补齐写进库了
r = run(rel("过敏的东西"))
assert r[1] == "对花生过敏，吃了会起疹子"
embed_ok[0] = False

# --- 上下文提示 ---
def ptext(q):
    async def go():
        async with SessionLocal() as db:
            return (await build_system_prompt(db, None, q)).text()
    return run(go())
pt = ptext("今天吃什么")
assert "共 40 条记忆" in pt and "search_memory" in pt, pt[-600:]
async def trim():
    async with SessionLocal() as db:
        for m in (await db.scalars(select(Memory).where(Memory.category == "general"))).all()[:20]:
            await db.delete(m)
        await db.commit()
run(trim())
pt = ptext("今天吃什么")
assert "共 " not in pt.split("关于用户你已知道")[1] and "对花生过敏" in pt

# --- 一轮对话 ---
load_builtin()
t = REGISTRY["search_memory"]
assert t.parallel and not t.deferred and "search_memory" in plan_mode.READ_TOOLS and "search_memory" in subagent.CHILD_TOOLS
assert "search_memory" in settings.system_prompt

script: list = []
tool_msgs: list[dict] = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
rnd = [0]
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    messages = [dict(m) for m in messages]
    tool_msgs.extend(m for m in messages if m["role"] == "tool" and m not in tool_msgs)
    step = script.pop(0)
    rnd[0] += 1
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"r{rnd[0]}c{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create

async def turn():
    script.extend([[("search_memory", {"query": "花生"}), ("search_memory", {})],
                   [("update_memory", {"ref": "#mmmmmmmm", "content": "对花生和腰果过敏"})],
                   "记下了：花生和腰果都不碰。"])
    async with SessionLocal() as db:
        conv = Conversation(id="c9", title="t"); db.add(conv); await db.commit()
        db.add(Message(conversation_id="c9", role="user", blocks=text_to_blocks("我对腰果也过敏，帮我更新一下")))
        await db.commit()
        return await runner.run_turn(db, conv)
reply = run(turn())
steps = [s for s in reply.steps if s["tool"] in ("search_memory", "update_memory")]
assert steps[0]["state"] == "done" and steps[0]["detail"] == "花生 · 1 条", steps[0]
assert steps[0]["title"] == "翻记忆", steps[0]
assert steps[1]["state"] == "error" and "没给要找什么" in steps[1]["note"], steps[1]
assert steps[2]["state"] == "done", steps[2]
assert "#mmmmmmmm" in tool_msgs[0]["content"]
async def after():
    async with SessionLocal() as db:
        return (await db.get(Memory, "mmmmmmmmold1")).content
assert run(after()) == "对花生和腰果过敏"
print("smoke_search_memory OK")
