# 冒烟：批准的方案 → 进度清单（v1.73，plan_mode.plan_steps / seed_items）。模拟模型。
# 一、规则：步骤类小节的编号列表优先（概要里的编号列表让位）、圆点/复选框列表、全文第一组编号列表兜底；
#    加粗短语、链接、行内代码清理；太长截断；子项和续行不打断；代码块里的不算；重复 / 只有 1 步 / 超过上限 → 不种。
# 二、整轮：交带步骤的方案 → 批准 → 回复里有方案卡 + 计划清单卡（第 1 步进行中、说明“按批准的方案”）、
#    模型收到 LIFTED_SEEDED 和整张清单；模型接着 update_plan 打勾 → 同一张卡原地换、收尾定格；
#    没有步骤的方案 → 不种卡、提示里是 LIFTED_FREE；没批准 → 不种。
# 运行：python tests/smoke_plan_steps.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', AUTO_TITLE="false",
  NEXT_SPEAKER_CHECK="off", MODEL_ROUTER="off")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import llm, plan as C, plan_mode as P
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.db import SessionLocal
from app.models import Conversation, Message

# —— 一、规则 ——
T = """# 迁移
## 概要
1. 不是步骤
2. 也不是
## 实施步骤
1. **改 runner**：读 plan_path
   - 子项不算
   续行也不打断
2. 写 `smoke`
3. [文档](http://x) 更新。
## 验证
- 跑测试
"""
assert P.plan_steps(T) == ["改 runner", "写 smoke", "文档 更新"], P.plan_steps(T)
assert P.plan_steps("# a\n## Steps\n- [ ] 一\n- [x] 二\n") == ["一", "二"]
assert P.plan_steps("# a\n## 概要\n1) 甲\n2) 乙\n") == ["甲", "乙"]                     # 兜底：全文第一组编号列表
assert P.plan_steps("# a\n## 步骤\n1. 甲\n\n2. 乙\n") == ["甲", "乙"]                    # 空行不打断
assert P.plan_steps("# a\n- x\n- y") == []                                               # 非步骤小节的圆点列表不算
assert P.plan_steps("# a\n```\n1. a\n2. b\n```\n") == []                                 # 代码块里的不算
assert P.plan_steps("# a\n## 步骤\n1. 同\n2. 同\n") == []                                # 重复
assert P.plan_steps("# a\n## 步骤\n1. 只有一步\n") == []
assert P.plan_steps("# a\n## 步骤\n" + "".join(f"{i}. 第{i}步\n" for i in range(1, C.ITEMS_MAX + 2))) == []
assert P.plan_steps("# a\n## 步骤\n1. 甲\n说明一句\n2. 乙\n") == []                      # 顶格正文结束一组 → 各 1 步
long = P.plan_steps("# a\n## 步骤\n1. " + "长" * 200 + "\n2. 短\n")
assert len(long[0]) == C.CONTENT_MAX and long[0].endswith("…") and long[1] == "短"
items = P.seed_items(["甲", "乙", "丙"])
assert [i["status"] for i in items] == ["in_progress", "pending", "pending"]
assert P.LIFTED_SEEDED.startswith("方案里的步骤") and "update_plan" in P.LIFTED_FREE
print("ok: rules")

# —— 二、整轮 ——
script: list = []
requests: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    requests.append([dict(m) for m in messages])
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
load_builtin()

async def seed():
    async with SessionLocal() as db:
        conv = Conversation(title="计划", mode="plan", mode_seen="plan"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=[{"type": "text", "text": "规划一下"}]))
        await db.commit()
        return conv.id
events: list = []
async def turn(cid, approve=True):
    async def emit(ev):
        events.append(ev)
    async def appr(_id, _t, _d):
        return approve
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=emit, approve=appr)
def tools_of(req):
    return [m["content"] for m in req if m["role"] == "tool"]

PLAN = "# 搬家\n\n## 概要\n周末搬完\n\n## 步骤\n1. 打包书\n2. 打包衣服\n3. 叫车\n\n## 验证\n- 数箱子"
cid = asyncio.run(seed())
script.extend([[(P.TOOL, {"plan": PLAN})],
               [("update_plan", {"todos": [{"content": "打包书", "status": "completed"},
                                           {"content": "打包衣服", "status": "in_progress"},
                                           {"content": "叫车", "status": "pending"}]})],
               "书打包好了，接着打包衣服。"])
reply = asyncio.run(turn(cid))
types = [b["type"] for b in reply.blocks]
assert types.count("plan") == 1 and types.index("plan_review") < types.index("plan"), types
card = next(b for b in reply.blocks if b["type"] == "plan")
assert [i["status"] for i in card["items"]] == ["completed", "in_progress", "pending"] and card.get("settled"), card
res = tools_of(requests[1])[-1]
assert res.startswith(P.LIFTED + P.LIFTED_SEEDED) and "1. [in_progress] 打包书" in res and "3. [pending] 叫车" in res, res
# 种下时的那一版：第 1 步进行中、带说明
seeded = [e for e in events if isinstance(e, dict) and e.get("type") in ("block.start", "block.update")
          and (e.get("block") or {}).get("type") == "plan"]
first = seeded[0]["block"]
assert first["explanation"] == "按批准的方案" and [i["status"] for i in first["items"]] == ["in_progress", "pending", "pending"], first
print("ok: seeded + ticked")

# 方案里没有步骤 → 不种
cid2 = asyncio.run(seed())
script.extend([[(P.TOOL, {"plan": "# 小改\n\n改一下标题就好。"})], "好。"])
reply = asyncio.run(turn(cid2))
assert not any(b["type"] == "plan" for b in reply.blocks)
res = tools_of(requests[-1])[-1]
assert res.startswith(P.LIFTED + P.LIFTED_FREE), res
# 没批准 → 不种
cid3 = asyncio.run(seed())
script.extend([[(P.TOOL, {"plan": PLAN})], "要改哪里？"])
reply = asyncio.run(turn(cid3, approve=False))
assert not any(b["type"] == "plan" for b in reply.blocks)
print("ok: no steps / rejected")
print("all ok")
