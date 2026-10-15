# 冒烟：v2.23 大脑 (ba) 跨项目协作——project_relay 规则 + projects 工具（按需）+ 对方接着做 + 给模型的渲染。模拟模型，无迁移。
# - find：id / 名字忽略大小写空白 / 唯一包含 / 歧义 / 没有；create 去重、档案、名字上限；list 标“就是这里”、档案第一行；
# - send：空话、太长、! 开头、发给自己、文件（隐藏目录拒绝、不存在、复制进 received/ 重名加 (2)、过配额）；
#   落在对方最近的普通对话（报告对话不算），没有就新开；origin 块 depth；转来的再转 = 第 2 手，第 3 手拒绝；每轮上限；
# - 一轮对话：主聊天调 projects message（直接名 + 经 deferred_tool call）→ relay 卡、时间线 detail、answer 钩子收到；
# - 对方那一轮：给模型的那一问开头是“不是用户本人在这里说的”，文件引用指向对方工作区；默认 answer（worker 进程）真跑一轮；
# - blocks_to_text：relay 卡进历史。
# 运行：python tests/smoke_project_relay.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from app import live_turns, llm, project_relay as pr, quota
from app.agent import runner
from app.agent.tools import REGISTRY, load_builtin
from app.blocks import blocks_to_text, text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message, Project, TaskRun
from app.storage import PROJECTS

LOOP = asyncio.new_event_loop()
def run(c):
    return LOOP.run_until_complete(c)
async def no_embed(texts):
    raise RuntimeError("no embeddings")
llm.embed = no_embed
load_builtin()
assert REGISTRY["projects"].deferred and REGISTRY["projects"].scope == "conversation"

async def go(fn, *a, **k):
    async with SessionLocal() as db:
        return await fn(db, *a, **k)

def err(coro, needle):
    try:
        run(coro)
    except pr.RelayError as e:
        assert needle in str(e), (needle, str(e))
        return
    raise AssertionError(f"应当报错：{needle}")

# --- 项目 ---
assert "还没有任何项目" in run(go(pr.list_text, None))
paper = run(go(pr.create, " 毕业  论文 ", "🎓", "# 毕业论文\n目标：五月答辩"))
assert paper.name == "毕业 论文" and paper.emoji == "🎓" and paper.brief.startswith("# 毕业论文") and paper.brief_by == "assistant"
trip = run(go(pr.create, "Japan Trip"))
assert trip.emoji == "📁"
run(go(pr.create, "Japan Notes"))
err(go(pr.create, "毕业论文"), "已经有")
err(go(pr.create, "   "), "要有名字")
err(go(pr.create, "x" * 61), "太长")
assert run(go(pr.find, paper.id)).id == paper.id
assert run(go(pr.find, "毕业论文")).id == paper.id          # 忽略空白
assert run(go(pr.find, "japan trip")).id == trip.id       # 忽略大小写
assert run(go(pr.find, "论文")).id == paper.id            # 唯一包含
err(go(pr.find, "japan"), "有几个项目")
err(go(pr.find, "火星"), "没有叫")
err(go(pr.find, ""), "没说是哪个项目")
lst = run(go(pr.list_text, paper.id))
assert "共 3 个项目" in lst and "🎓 毕业 论文（就是这里）" in lst and "毕业论文" in lst and f"id={trip.id}" in lst, lst

# --- 文件准备：主聊天工作区（me）---
me = PROJECTS / "me"
(me / "notes").mkdir(parents=True, exist_ok=True)
(me / "notes" / "提纲.md").write_text("# 提纲\n1. 引言", encoding="utf-8")
(me / ".home").mkdir(exist_ok=True)
(me / ".home" / "token.txt").write_text("secret")

# --- send 校验 ---
async def mkconv(cid, project_id=None, text="帮我把提纲交给论文项目"):
    async with SessionLocal() as db:
        db.add(Conversation(id=cid, title="t", project_id=project_id))
        await db.commit()
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks(text)))
        await db.commit()
run(mkconv("main1"))
got: list = []
pr.set_answerer(lambda cid, mid: got.append((cid, mid)))
err(go(pr.send, "main1", None, "论文", "  "), "是空的")
err(go(pr.send, "main1", None, "论文", "x" * 4001), "太长了")
err(go(pr.send, "main1", None, "论文", "!ls"), "不要以")
err(go(pr.send, "p1", paper.id, paper.id, "自己"), "这就是当前项目")
err(go(pr.send, "main1", None, "论文", "看看", [".home/token.txt"]), "隐藏目录")
err(go(pr.send, "main1", None, "论文", "看看", ["nope.txt"]), "没有文件")
err(go(pr.send, "main1", None, "论文", "看看", ["a"] * 6), "最多带")
assert not got and not (PROJECTS / paper.id / "received").exists()

# v2.95 项目 = 一段对话：落在项目建好时就有的那段；项目里的运行对话（定时脚本的报告）不算
async def report_conv():
    async with SessionLocal() as db:
        db.add(Conversation(id="rep1", title="周报", project_id=paper.id, task_id="t1"))
        db.add(TaskRun(task_id="t1", conversation_id="rep1"))
        await db.commit()
run(report_conv())
s1 = run(go(pr.send, "main1", None, "毕业论文", "这是提纲初稿，帮我扩成三级目录。", ["notes/提纲.md", "/workspace/notes/提纲.md"]))
assert not s1.new_conversation and s1.depth == 1 and s1.conversation_id != "rep1"
assert [b["id"] for b in s1.files] == ["received/提纲.md", "received/提纲 (2).md"], s1.files
assert (PROJECTS / paper.id / "received" / "提纲 (2).md").read_text(encoding="utf-8").startswith("# 提纲")
assert got == [(s1.conversation_id, s1.message_id)]
async def msg(mid):
    async with SessionLocal() as db:
        m = await db.get(Message, mid)
        c = await db.get(Conversation, m.conversation_id)
        return m, c
m1, c1 = run(msg(s1.message_id))
assert c1.project_id == paper.id and c1.task_id is None and c1.title == "毕业 论文" and c1.title_source == "fixed"
o = m1.blocks[0]
assert o == {"type": "origin", "name": "主聊天", "emoji": "💬", "project_id": None, "conversation_id": "main1", "depth": 1}, o
assert m1.blocks[1] == {"type": "text", "text": "这是提纲初稿，帮我扩成三级目录。"} and m1.blocks[2]["project_id"] == paper.id
card = pr.card(s1, "这是提纲初稿，帮我扩成三级目录。")
assert card["type"] == "relay" and card["name"] == "毕业 论文" and card["files"] == ["提纲.md", "提纲 (2).md"] and not card["new_conversation"]
assert "已交给「毕业 论文」项目" in blocks_to_text([card]) and "提纲 (2).md" in blocks_to_text([card])
# 第二次发给同一项目：还是那段
s2 = run(go(pr.send, "main1", None, paper.id, "另外参考文献用 GB/T 7714。"))
assert not s2.new_conversation and s2.conversation_id == s1.conversation_id
s3 = run(go(pr.send, "main1", None, trip.id, "第三条"))
err(go(pr.send, "main1", None, trip.id, "第四条"), "已经转交了 3 条")   # 每轮上限
run(mkconv("main1b", text="新的一轮"))  # 新一轮（不同对话/锚点）重新计数
run(go(pr.send, "main1b", None, trip.id, "新一轮可以发"))

# 转来的再转：论文项目里收到的那条是第 1 手 → 再转给旅行项目是第 2 手 → 旅行项目再转第 3 手拒绝
s4 = run(go(pr.send, s1.conversation_id, paper.id, "japan trip", "论文写完想去日本，帮我留意五月机票。"))
assert s4.depth == 2
m4, _ = run(msg(s4.message_id))
assert m4.blocks[0]["name"] == "毕业 论文" and m4.blocks[0]["emoji"] == "🎓" and m4.blocks[0]["depth"] == 2
err(go(pr.send, s4.conversation_id, trip.id, "论文", "再转回去"), "已经第 2 手")

# 配额：对方放不下
quota.forget()
old = quota.limit_bytes
quota.limit_bytes = lambda: 10
try:
    err(go(pr.send, "main1b", None, paper.id, "大文件", ["notes/提纲.md"]), "磁盘放不下")
finally:
    quota.limit_bytes = old
    quota.forget()

# --- 模拟模型：主聊天里一轮 ---
script: list = []
seen: list[list[dict]] = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
rnd = [0]
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    messages = [dict(m) for m in messages]
    seen.append(messages)
    step = script.pop(0)
    rnd[0] += 1
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"r{rnd[0]}c{i}", function=NS(name=nm, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (nm, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create

async def turn(cid, steps, project_id=None, text="q"):
    script.extend(steps)
    await mkconv(cid, project_id, text)
    async with SessionLocal() as db:
        return await runner.run_turn(db, await db.get(Conversation, cid))

got.clear()
reply = run(turn("main2", [
    [("projects", {"action": "list"})],
    [("deferred_tool", {"action": "call", "tool": "projects", "arguments": {"action": "message", "project": "日本", "text": "x"}})],
    [("deferred_tool", {"action": "call", "tool": "projects", "arguments": {"action": "message", "project": "Japan Trip",
                                                                            "text": "帮我看五月东京酒店", "files": ["notes/提纲.md"]}})],
    [("projects", {"action": "create", "name": "健身"})],
    [("projects", {"action": "fly"})],
    "交给旅行项目了，结果在那边。"]))
steps = [s for s in reply.steps if s["tool"] == "projects"]
assert steps[0]["state"] == "done" and steps[1]["state"] == "error" and "没有叫" in steps[1]["note"], steps
assert steps[2]["state"] == "done" and steps[2]["detail"] == "交给 Japan Trip", steps[2]
assert steps[3]["detail"] == "新建 健身" and steps[4]["state"] == "error"
relay = [b for b in reply.blocks if b["type"] == "relay"]
assert len(relay) == 1 and relay[0]["name"] == "Japan Trip" and relay[0]["files"] == ["提纲.md"], reply.blocks
assert len(got) == 1 and got[0][0] == relay[0]["conversation_id"]
tool_txt = [m["content"] for m in seen[3] if m["role"] == "tool"]
assert any("已交给「📁 Japan Trip」项目" in t for t in tool_txt), tool_txt

# --- 对方那一轮：默认 answer（worker 进程没有 ws 钩子）真跑一轮 ---
pr.set_answerer(None)
script.extend(["好的，我去看东京酒店。"])
seen.clear()
async def relay_and_wait():
    async with SessionLocal() as db:
        s = await pr.send(db, "main3", None, trip.id, "五月东京酒店预算每晚 600 元", ["notes/提纲.md"])
    await asyncio.sleep(0.05)
    await live_turns.drain(10)
    return s
run(mkconv("main3"))
s5 = run(relay_and_wait())
user_q = [m for m in seen[0] if m["role"] == "user"][-1]["content"]
q = user_q if isinstance(user_q, str) else json.dumps(user_q, ensure_ascii=False)
assert "不是用户本人在这里说的" in q and "「主聊天」" in q and "五月东京酒店预算" in q, q
assert "received/提纲" in q and "项目文件" in q, q
async def last_reply(cid):
    async with SessionLocal() as db:
        from sqlalchemy import select
        return (await db.scalars(select(Message).where(Message.conversation_id == cid).order_by(Message.created_at.desc()))).first()
r = run(last_reply(s5.conversation_id))
assert r.role == "assistant" and "东京酒店" in json.dumps(r.blocks, ensure_ascii=False)
print("smoke_project_relay ok")
