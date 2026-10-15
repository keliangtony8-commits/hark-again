# 冒烟：v2.09 大脑 (at) 翻以前的对话——app/chat_search.py + search_history 工具 + 面板搜索改用同一规则。模拟模型，无迁移。
# - 拆词：空格 AND、引号整词、去重、上限、% _ 字面量；摘录取最早出现的词、两头“…”；
# - 搜索：词可分散在标题和不同消息里；最佳命中 = 含词最多再最新；标题全中不给摘录；范围（全部 / 主聊天 / 项目）；
#   时间窗口（日期按用户时区、before 含当天、窗口外的消息不算、开始晚于结束报错、写法错报错）；
# - 读原文：命中消息前后几条、标“← 命中”、长消息中间截、总量上限、更早/更晚的接续编号、对话或消息不存在报错；
# - 一轮对话：模型调 search_history（跳过用户这一轮刚问的那句）→ 结果含项目名、对话编号、看原文提示；再读原文；
#   时间线 detail “词 · N 段”；计划模式、子助手可用；系统提示有规则；
# - 面板 GET /api/conversations?q= 多词 AND。
# 运行：python tests/smoke_search_history.py
import os, sys, asyncio, subprocess, tempfile, json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from app import chat_search as cs, llm, plan_mode
from app.agent import runner, subagent
from app.agent.tools import REGISTRY, load_builtin
from app.blocks import text_to_blocks
from app.config import settings
from app.db import SessionLocal
from app.models import Conversation, Message, Project

# --- 拆词 / 摘录 ---
assert cs.terms('  咖啡  推荐 咖啡 ') == ["咖啡", "推荐"]
assert cs.terms('"手冲 咖啡" 店') == ["手冲 咖啡", "店"]
assert cs.terms("“北京 南站”「周五」 x") == ["北京 南站", "周五", "x"]
assert cs.terms("Coffee coffee") == ["Coffee"]
assert len(cs.terms(" ".join(f"w{i}" for i in range(20)))) == cs.TERMS_MAX
assert cs.terms("   ") == []
assert cs._like("100%_ok") == "%100\\%\\_ok%"
long = "开头" + "很长的话。" * 30 + "咖啡在这里" + "后面" * 40
s = cs.snippet_of(long, ["这里", "咖啡"], 10)
assert s.startswith("…") and s.endswith("…") and "咖啡在这里" in s and len(s) <= 10 * 2 + 2 + 2, s
assert cs.snippet_of("短短一句", ["没有"]) == "短短一句"
assert cs.snippet_of("x" * 100, "无", 10) == "x" * 20 + "…"

# --- 时间 ---
a = cs.parse_when("2026-10-12")
assert a == datetime(2026, 10, 11, 16, tzinfo=timezone.utc), a
assert cs.parse_when("2026-10-12", end=True) == datetime(2026, 10, 12, 16, tzinfo=timezone.utc)
assert cs.parse_when("2026-10-12T14:00") == datetime(2026, 10, 12, 6, tzinfo=timezone.utc)
assert cs.parse_when("2026-10-12T14:00+00:00") == datetime(2026, 10, 12, 14, tzinfo=timezone.utc)
assert cs.parse_when("") is None
for bad, why in (("昨天", "认不出"), ("2026-13-01", "认不出")):
    try:
        cs.parse_when(bad); raise AssertionError(bad)
    except cs.SearchError as e:
        assert why in str(e), e
try:
    cs.window("2026-10-12", "2026-10-11"); raise AssertionError
except cs.SearchError as e:
    assert "早于" in str(e)
assert cs.window("2026-10-12", "2026-10-12")[0] < cs.window("2026-10-12", "2026-10-12")[1]

NOW = datetime.now(timezone.utc).replace(tzinfo=None)
async def seed():
    async with SessionLocal() as db:
        p = Project(id="p1", name="搬家"); db.add(p)
        c1 = Conversation(id="c1", title="周末去哪", updated_at=NOW - timedelta(days=3))
        c2 = Conversation(id="c2", title="咖啡店推荐", updated_at=NOW - timedelta(days=1))
        c3 = Conversation(id="c3", title="新家附近", project_id="p1", updated_at=NOW - timedelta(days=2))
        c4 = Conversation(id="c4", title="很长的对话", updated_at=NOW - timedelta(days=10))
        db.add_all([c1, c2, c3, c4]); await db.flush()
        def m(cid, role, text, days, mid=None):
            db.add(Message(id=mid, conversation_id=cid, role=role, blocks=text_to_blocks(text),
                           created_at=NOW - timedelta(days=days)))
        m("c1", "user", "周末想喝咖啡", 3.2, "m11")
        m("c1", "assistant", "推荐去 Seesaw，手冲很好", 3.1, "m12")
        m("c2", "user", "公司附近有什么店", 1.2, "m21")
        m("c2", "assistant", "Manner 和 Seesaw 都在 3 号线旁边", 1.1, "m22")
        m("c3", "user", "新家附近的 Seesaw 几点开门", 2.1, "m31")
        for i in range(30):
            m("c4", "user" if i % 2 == 0 else "assistant", f"第{i}条" + ("Seesaw 菜单" if i == 15 else "闲聊") + ("长" * (3000 if i == 16 else 10)), 10 - i * 0.01, f"m4{i:02d}")
        await db.commit()
asyncio.run(seed())

async def S(q, **kw):
    async with SessionLocal() as db:
        return await cs.search(db, q, **kw)
run = asyncio.run

# 词分散：c1 标题“周末”+ 消息“咖啡” → 命中
r = run(S("周末 咖啡"))
assert [h.conversation.id for h in r] == ["c1"] and r[0].message_id == "m11" and not r[0].title_hit, r
# 最佳命中消息：含词最多、再最新
r = run(S("Seesaw 手冲"))
assert [h.conversation.id for h in r] == ["c1"] and r[0].message_id == "m12" and r[0].matched == 2
r = run(S("Seesaw", order="best"))
ids = [h.conversation.id for h in r]
assert set(ids) == {"c1", "c2", "c3", "c4"} and ids[0] == "c2", ids  # 都只含 1 个词 → 最近命中优先
# 标题全中：不给摘录（面板）
r = run(S("咖啡店"))
assert [h.conversation.id for h in r] == ["c2"] and r[0].title_hit
# 范围
assert [h.conversation.id for h in run(S("Seesaw", scope=None))] and "c3" not in [h.conversation.id for h in run(S("Seesaw", scope=None))]
assert [h.conversation.id for h in run(S("Seesaw", scope="p1"))] == ["c3"]
# 时间窗口：只算窗口里的消息
lo = datetime.now(timezone.utc) - timedelta(days=1.5)
r = run(S("Seesaw", after=lo))
assert [h.conversation.id for h in r] == ["c2"], [h.conversation.id for h in r]
r = run(S("Seesaw", before=datetime.now(timezone.utc) - timedelta(days=5)))
assert [h.conversation.id for h in r] == ["c4"] and r[0].message_id == "m415"
assert run(S("周末", after=datetime.now(timezone.utc) - timedelta(days=1))) == []  # 标题中了但窗口内没有消息
# skip：跳过这一轮刚问的那句
assert [h.conversation.id for h in run(S("几点开门", skip={"m31"}))] == []
assert run(S("100%")) == [] and run(S("")) == []

# --- 读原文 ---
async def R(cid, mid=None):
    async with SessionLocal() as db:
        return await cs.read(db, cid, mid)
t = run(R("c4", "m415"))
assert "共 30 条消息" in t and "[16] 助手" in t and "← 命中" in t, t[:300]
assert "第 13–" in t and "中间省略" in t, t[:200]  # 第 17 条 3000 字被中间截
assert "更早的：message=\"m4" in t and "更晚的：message=\"m4" in t
t2 = run(R("c4"))
assert "这里是第 21–30 条" in t2 and "更早的" in t2 and "更晚的" not in t2, t2[:200]
t3 = run(R("c3"))
assert "项目「搬家」" in t3 and "第 1–1 条" in t3
for bad in (("nope", None), ("c4", "zz")):
    try:
        run(R(*bad)); raise AssertionError(bad)
    except cs.SearchError as e:
        assert "没有" in str(e)

# --- 面板接口 ---
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routes import conversations as rc
from app.auth import require_user
api = FastAPI(); api.include_router(rc.router)
api.dependency_overrides[require_user] = lambda: "u"
c = TestClient(api)
x = c.get("/api/conversations", params={"q": "Manner 3号线"}).json()
assert x == [], x  # “3号线” 不在原文（原文是“3 号线”）
x = c.get("/api/conversations", params={"q": "Manner 号线"}).json()
assert [y["id"] for y in x] == ["c2"] and x[0]["message_id"] == "m22" and "Manner" in x[0]["snippet"], x
x = c.get("/api/conversations", params={"q": "Seesaw", "project_id": "p1"}).json()
assert [y["id"] for y in x] == ["c3"]
# v3.2.1：面板搜全部——项目那段对话也能搜到，带 project_id / project_name（客户端跳进项目）；主聊天的不带
x = c.get("/api/conversations", params={"q": "几点开门"}).json()
assert [y["id"] for y in x] == ["c3"] and x[0]["project_id"] == "p1" and x[0]["project_name"] == "搬家" and x[0]["message_id"] == "m31", x
x = c.get("/api/conversations", params={"q": "Seesaw"}).json()
assert {y["id"] for y in x} == {"c1", "c2", "c3", "c4"} and all("project_id" not in y for y in x if y["id"] != "c3"), x

# --- 一轮对话 ---
load_builtin()
t = REGISTRY["search_history"]
assert t.parallel and not t.deferred and "search_history" in plan_mode.READ_TOOLS and "search_history" in subagent.CHILD_TOOLS
assert "search_history" in settings.system_prompt

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
    script.extend([[("search_history", {"query": "Seesaw 开门"}), ("search_history", {"query": "x", "after": "昨天"})],
                   [("search_history", {"conversation": "c3", "message": "m31"})],
                   "上次说的是新家附近那家 Seesaw。"])
    async with SessionLocal() as db:
        conv = Conversation(id="c9", title="t"); db.add(conv); await db.commit()
        db.add(Message(conversation_id="c9", role="user", blocks=text_to_blocks("上次说的 Seesaw 几点开门来着？")))
        await db.commit()
        return await runner.run_turn(db, conv)
reply = run(turn())
steps = [s for s in reply.steps if s["tool"] == "search_history"]
assert steps[0]["state"] == "done" and steps[0]["detail"] == "Seesaw 开门 · 1 段", steps[0]
assert steps[0]["title"] == "翻以前的对话"
assert steps[1]["state"] == "error" and "认不出" in steps[1]["note"], steps[1]
assert steps[2]["state"] == "done" and steps[2]["detail"] == "读原文", steps[2]
first = tool_msgs[0]["content"]
assert "「新家附近」" in first and "项目「搬家」" in first and 'conversation="c3" message="m31"' in first, first
assert "c9" not in first  # 用户这一轮刚问的那句不算命中
assert "← 命中" in tool_msgs[2]["content"]
print("smoke_search_history OK")
