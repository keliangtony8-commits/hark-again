# 冒烟：v2.46 BRAIN (bd) 技能目录预算 + skill_search / edit_skill / delete_skill。
# 1) 规则 app/skill_catalog.py：放得下全放；放不下先轮流截描述（短的放全、长的截 + …）；名字都放不下 → 省略 + skill_search 提示；
#    目录逐字稳定；搜索拆词（中文两字一组）、打分（名称 > 描述 > 正文）、停用的搜不到、空 query 列全部；
# 2) skills_store.edit_skill：唯一一处替换、找不到 / 多处 / 空 find / 删掉首行 拒绝；内置先复制成自定义版；
# 3) 工具：deferred、skill_search 计划模式可用且并行；delete_skill 用户技能删、自定义版恢复、内置拒绝；
# 4) 一轮（模拟模型，经 deferred_tool call）：搜到 → edit_skill 改好 → “改好了”不被 claimed_action 拦；系统提示含目录。
# 运行：python tests/smoke_skill_catalog.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp)
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import plan_mode, skill_catalog as C, skills_store
from app.agent.tools import REGISTRY, load_builtin

S = lambda i, n, d, b="", builtin=False: NS(id=i, name=n, description=d, body=b, builtin=builtin, customized=False)

# ---- 1) 目录预算 ----
few = [S("a", "甲", "短描述"), S("b", "乙", "另一个描述")]
out = C.prompt_section(few)
assert out == C.HEAD + "- a：甲——短描述\n- b：乙——另一个描述", out
assert C.prompt_section([]) == ""
assert C.prompt_section(few) == out, "逐字稳定"
# 描述轮流截：短的放全、长的被截
many = [S("s1", "短", "小"), S("s2", "长", "很" * 200)]
budget = len(C.HEAD) + len("- s1：短——小\n") + len("- s2：长\n") + 2 + 20
mid = C.prompt_section(many, budget)
assert "- s1：短——小" in mid and "- s2：长——" + "很" * 20 + "…" in mid, mid
assert "skill_search" not in mid
assert len(mid) <= budget + 1, (len(mid), budget)
# 名字都放不下 → 省略 + 提示
lots = [S(f"skill-{i:02d}", f"技能{i}", "描述" * 10) for i in range(40)]
tight = C.prompt_section(lots, 300)
listed = [l for l in tight.splitlines() if l.startswith("- ")]
assert 0 < len(listed) < 40 and all("——" not in l for l in listed), tight
assert f"另外 {40 - len(listed)} 个技能没列出" in tight and "skill_search" in tight
assert listed[0] == "- skill-00：技能0", "按目录顺序"
# 每轮点名被省略的相关技能
hid = lots + [S("trip", "出差报销做法", "整理发票、报销出差费用时用", "金额汇总写进 baoxiao.csv")]
assert [s.id for s in C.omitted(hid, 300)][-1] == "trip"
assert C.relevant_section(few, "出差报销") == "", "没省略 → 不点名"
rel = C.relevant_section([S(f"m{i}", f"日常{i}", "随便" * 40) for i in range(200)] + hid, "按我自己的出差报销做法，整理这三张发票")
assert "- trip：出差报销做法" in rel and rel.count("\n- ") == 1, rel
assert C.relevant_section([S(f"m{i}", f"日常{i}", "随便" * 40) for i in range(200)] + hid, "今天天气怎么样") == ""
# 默认预算下：40 个技能描述被截、但都在
long = [S(f"skill-{i:02d}", f"技能{i}", "描述" * 50) for i in range(40)]
full = C.prompt_section(long)
assert len(full) <= C.CATALOG_CHARS + 40 and full.count("\n- ") == 40 and full.count("…") == 40, len(full)
assert "skill_search" not in full
# 描述压一行 + 上限
one = C.prompt_section([S("x", "X", "第一行\n第二行 " + "长" * 300)])
assert "第一行 第二行" in one and "…" in one and len(one) < C.DESC_MAX + 60

# ---- 搜索 ----
assert C.terms("周报模板 Excel") == ["周报", "报模", "模板", "excel"]
assert C.terms("  ") == []
lib = [S("weekly", "周报", "每周五写周报", "用模板 report.docx"), S("trip", "出差报销", "报销流程", "发票拍照，周报里不写"),
       S("excel", "表格整理", "整理 Excel", "透视表")]
hits = C.search(lib, "周报")
assert [h["id"] for h in hits] == ["weekly", "trip"], hits   # 名称命中 > 正文命中
assert "snippet" in hits[1] and "周报" in hits[1]["snippet"]
assert [h["id"] for h in C.search(lib, "EXCEL")] == ["excel"]
assert C.search(lib, "天气") == []
assert [h["id"] for h in C.search(lib, "")] == ["weekly", "trip", "excel"]
assert len(C.search(lots, "", 100)) == C.LIST_MAX and len(C.search(lots, "技能")) == C.SEARCH_MAX
txt = C.render(C.search(lib, "周报"), "周报", 3)
assert txt.startswith("找到 2 个技能（关键词：周报）") and "use_skill" in txt
assert "没有和「天气」相关的技能（共 3 个" in C.render([], "天气", 3)

# ---- 2) edit_skill（真技能库） ----
mine = skills_store.save_skill("周报", "每周五写周报", "1. 打开模板\n2. 填本周进展\n3. 发给老板")
e = skills_store.edit_skill(mine.id, "发给老板", "发给老板和组长")
assert e.body.endswith("发给老板和组长") and e.name == "周报"
for bad, why in [("", "不能为空"), ("不存在的话", "没有这段原文"), ("。", None)]:
    try:
        skills_store.edit_skill(mine.id, bad, "x")
        assert why is None and False, bad
    except ValueError as err:
        assert why is None or why in str(err), err
skills_store.save_skill("周报", "每周五写周报", "a\na", sid=mine.id)
try:
    skills_store.edit_skill(mine.id, "a", "b"); assert False
except ValueError as err:
    assert "出现了 2 次" in str(err)
try:
    skills_store.edit_skill(mine.id, "# 周报", ""); assert False
except ValueError as err:
    assert "首行" in str(err)
try:
    skills_store.edit_skill("nope", "a", "b"); assert False
except KeyError:
    pass
# 内置：自动复制成自定义版
w = skills_store.get_skill("writing")
first = w.body.splitlines()[0]
ew = skills_store.edit_skill("writing", first, first + "（我的口味）")
assert ew.customized and not ew.builtin and "（我的口味）" in ew.body
skills_store.reset("writing")

# ---- 3) 工具 ----
load_builtin()
for n in ("edit_skill", "delete_skill"):
    assert REGISTRY[n].deferred, n
assert not REGISTRY["skill_search"].deferred, "真机 s1：直接给，不按需"
assert "skill_search" in plan_mode.READ_TOOLS and REGISTRY["skill_search"].parallel
assert "edit_skill" not in plan_mode.READ_TOOLS
from app.agent.builtin import skills as T
async def tools():
    r1 = await T.skill_search(None, "周报")
    assert "周报" in r1.content and mine.id in r1.content, r1.content
    skills_store.set_enabled(mine.id, False)
    assert f"- {mine.id}：" not in (await T.skill_search(None, "周报")).content, "停用的搜不到"
    skills_store.set_enabled(mine.id, True)
    assert "没有改" in (await T.edit_skill(None, mine.id, "zzz", "y")).content
    assert "没有 id" in (await T.edit_skill(None, "nope", "a", "b")).content
    r = await T.edit_skill(None, "writing", skills_store.get_skill("writing").body.splitlines()[0], "改")
    assert "自定义版" in r.content, r.content
    assert "恢复成内置原样" in (await T.delete_skill(None, "writing")).content
    assert not skills_store.get_skill("writing").customized
    assert "不能删除" in (await T.delete_skill(None, "writing")).content
    tmpk = skills_store.save_skill("临时", "临时的", "x")
    assert "已删除" in (await T.delete_skill(None, tmpk.id)).content and skills_store.get_skill(tmpk.id) is None
    assert "没有 id" in (await T.delete_skill(None, tmpk.id)).content
asyncio.run(tools())
skills_store.save_skill("周报", "每周五写周报", "1. 打开模板\n2. 填本周进展\n3. 发给老板", sid=mine.id)

# ---- 4) 一轮（模拟模型） ----
from app import llm
from app.agent.runner import run_turn
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message
seen, script = [], []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append({"messages": [dict(m) for m in messages], "tools": [x["function"]["name"] for x in tools or []]})
    step = script.pop(0)
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"k{len(script)}-{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
async def seed():
    async with SessionLocal() as db:
        c = Conversation(title="t"); db.add(c); await db.flush()
        db.add(Message(conversation_id=c.id, role="user", blocks=text_to_blocks("我的周报技能里，以后也抄送组长")))
        await db.commit()
        return c.id
cid = asyncio.run(seed())
async def _ask(_id, _form):
    return None
async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0), ask=_ask)
script.extend([
    [("deferred_tool", {"action": "call", "tool": "skill_search", "arguments": {"query": "周报"}})],
    [("deferred_tool", {"action": "call", "tool": "edit_skill",
                        "arguments": {"id": mine.id, "find": "发给老板", "replace": "发给老板，抄送组长"}})],
    "改好了，以后周报会抄送组长。",
])
reply = asyncio.run(turn())
sysmsg = seen[0]["messages"][0]["content"]
assert C.HEAD.strip() in str(sysmsg) and f"- {mine.id}：周报——每周五写周报" in str(sysmsg)
assert "skill_search" in seen[0]["tools"] and "edit_skill" not in seen[0]["tools"]
assert [(x["tool"], x["state"]) for x in reply.steps] == [("skill_search", "done"), ("edit_skill", "done")], reply.steps
assert len(seen) == 3, "改好了没被 claimed_action 拦（edit_skill 算写）"
assert "抄送组长" in skills_store.get_skill(mine.id).body
print("smoke_skill_catalog ok")
