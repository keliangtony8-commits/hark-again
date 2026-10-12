# 冒烟：计划清单 update_plan（app/plan.py，移植自 deepseek-harness tool-todo，嫁接 Gemini write-todos / Codex update_plan）。
# 一、校验规则（deepseek toTodoList + Gemini validateToolParamValues 用例翻译）；二、回给模型的文字；三、历史一行；
# 四、模拟模型整轮：开工写计划 → 做事 → 勾选 → 收尾：一条回复只有一张计划卡、停在第一次的位置、最后 settled、
#     update_plan 不进时间线；不合规 → 回错误让模型改、卡片不变；被停 → partial 定格；存库 + 历史文字。
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import llm, plan
from app.blocks import blocks_to_text, PlanBlock
from app.agent import loop
from app.agent.tools import ToolContext, ToolResult, tool, load_builtin, REGISTRY
from app.db import SessionLocal
from app.models import Conversation

P = lambda *xs: [{"content": c, "status": s} for c, s in xs]

# —— 一、校验 ——
def bad(todos, *, why):
    try:
        plan.normalize(todos)
    except plan.PlanError as e:
        assert why in str(e), (why, str(e))
        return
    raise AssertionError(f"应当拒绝：{todos}")

assert plan.normalize(P(("装依赖", "in_progress"), ("跑测试", "pending")))[0][0] == {"content": "装依赖", "status": "in_progress"}
assert plan.normalize([]) == ([], "")  # Gemini：空清单 = 清掉
bad("x", why="数组"); bad({"todos": []}, why="数组")
bad(["装依赖"], why="对象"); bad([None], why="对象")
bad(P(("  ", "pending")), why="不能为空"); bad([{"status": "pending"}], why="不能为空")
bad(P(("a", "done")), why="status"); bad([{"content": "a"}], why="status")
bad(P(("a", "in_progress"), ("b", "in_progress")), why="只能有一步")
bad(P(("装依赖", "pending"), (" 装依赖 ", "completed")), why="重复")  # deepseek：去空白后重复
bad(P(*[(f"第{i}步", "pending") for i in range(plan.ITEMS_MAX + 1)]), why="太多")
bad(P(("长" * (plan.CONTENT_MAX + 1), "pending")), why="太长")
items, note = plan.normalize(P(("  装\n依赖 ", "completed")), "  先装 \n 再跑 ")
assert items == [{"content": "装 依赖", "status": "completed"}] and note == "先装 再跑"
assert plan.normalize(P(("a", "pending")), 123)[1] == ""
print("ok: validation")

# —— 二、三 ——
t = plan.for_model(P(("装依赖", "completed"), ("跑测试", "in_progress"), ("交付", "pending")))
assert t.startswith("计划已更新：完成 1 / 共 3，进行中 1。") and "2. [in_progress] 跑测试" in t and "立刻标 completed" in t
assert "全部完成" in plan.for_model(P(("a", "completed"))) and plan.for_model([]) == "计划已清空。"
b = plan.block(P(("装依赖", "completed"), ("跑测试", "pending")), "换成 uv")
PlanBlock(**b)
assert blocks_to_text([b]) == "[计划 1/2：装依赖（完成）；跑测试（待做）]"
assert blocks_to_text([plan.block([])]) == ""
assert plan.settle(b)["settled"] is True and plan.settle({"type": "text", "text": "x"}) == {"type": "text", "text": "x"}
assert REGISTRY == {} or True
print("ok: model text / history / settle")

# —— 四、整轮 ——
@tool("fake_work", "正在干活", "测试用", {"type": "object", "properties": {"n": {"type": "integer"}}})
async def fake_work(ctx, n: int = 0) -> ToolResult:
    return ToolResult(f"第 {n} 步做好了", blocks=[{"type": "code", "language": "", "source": f"step {n}"}])

script, saw = [], []
def chunk(text=None, tools=None, u=None):
    if text is None and tools is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tools))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    saw.append(json.loads(json.dumps(messages, ensure_ascii=False)))
    step = script.pop(0) if script else "做完了"
    async def gen():
        if isinstance(step, list):
            yield chunk(tools=[NS(index=i, id=f"c{len(saw)}_{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                               for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=100, completion_tokens=0))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()
assert REGISTRY["update_plan"].quiet
n = 0

def up(*xs, why=""):
    a = {"todos": P(*xs)}
    if why:
        a["explanation"] = why
    return ("update_plan", a)

async def run(*steps, builder=None):
    global n
    n += 1
    script[:] = list(steps); saw.clear()
    async with SessionLocal() as db:
        db.add(Conversation(id=f"c{n}", title="t")); await db.commit()
        evs = [e async for e in loop.run("sys", [{"role": "user", "content": "搭个网站"}], ToolContext(db=db, conversation_id=f"c{n}"), builder)]
    return evs

async def main():
    A, B, C = "装依赖", "写页面", "跑起来"
    evs = await run([up((A, "in_progress"), (B, "pending"), (C, "pending"))],
                    [("fake_work", {"n": 1})],
                    [up((A, "completed"), (B, "in_progress"), (C, "pending")), ("fake_work", {"n": 2})],
                    [up((A, "completed"), (B, "completed"), (C, "in_progress"), why="改用 vite")],
                    [("fake_work", {"n": 3})],
                    [up((A, "completed"), (B, "completed"), (C, "completed"))],
                    "网站跑起来了")
    done = evs[-1]; blocks = done.blocks
    plans = [b for b in blocks if b["type"] == "plan"]
    assert len(plans) == 1 and blocks[0]["type"] == "plan", [b["type"] for b in blocks]  # 单例，停在第一次的位置
    assert plans[0]["settled"] is True and all(i["status"] == "completed" for i in plans[0]["items"])
    assert "explanation" not in plans[0]  # 只显示最近一次更新的原因；最后一次没给 → 不带
    statuses = [e for e in evs if isinstance(e, loop.ToolStatus)]
    assert statuses and all(s.name != "update_plan" for s in statuses)  # 不进时间线
    starts = [e for e in evs if isinstance(e, loop.BlockStart) and e.block["type"] == "plan"]
    assert len(starts) == 1
    ups = [e for e in evs if isinstance(e, loop.BlockUpdate) and e.block["type"] == "plan"]
    assert ups[1].block["explanation"] == "改用 vite"
    assert len(ups) == 4 and ups[-1].block["settled"] and not ups[-2].block.get("settled")
    tool_msgs = [m for m in saw[-1] if m["role"] == "tool"]
    assert tool_msgs[0]["content"].startswith("计划已更新：完成 0 / 共 3")
    assert any("全部完成" in m["content"] for m in tool_msgs)
    print("ok: full turn, one card, settled, quiet")

    evs = await run([up((A, "in_progress"))], [up((A, "in_progress"), (B, "in_progress"))], "好")
    pl = [b for b in evs[-1].blocks if b["type"] == "plan"]
    assert len(pl) == 1 and pl[0]["items"] == P((A, "in_progress")) and pl[0]["settled"]
    assert "计划没有更新：同一时间只能有一步" in [m for m in saw[-1] if m["role"] == "tool"][-1]["content"]
    print("ok: invalid update → error to model, card unchanged")

    # 被停：partial 定格
    builder = loop.MessageBuilder()
    script[:] = [[up((A, "in_progress"), (B, "pending"))]]
    async with SessionLocal() as db:
        db.add(Conversation(id="cs", title="t")); await db.commit()
        agen = loop.run("sys", [{"role": "user", "content": "x"}], ToolContext(db=db, conversation_id="cs"), builder)
        async for e in agen:
            if isinstance(e, loop.BlockStart) and e.block["type"] == "plan":
                break
        await agen.aclose()
    part = builder.partial()
    assert part[0]["type"] == "plan" and part[0]["settled"] and part[0]["items"][0]["status"] == "in_progress"
    assert not builder.blocks[0].get("settled")  # partial 不改原块
    print("ok: stopped turn settles the card")

    # 空清单 = 清掉（卡片 items 为空，客户端不画）
    evs = await run([up((A, "pending"))], [("update_plan", {"todos": []})], "算了，一步就好")
    pl = [b for b in evs[-1].blocks if b["type"] == "plan"]
    assert pl[0]["items"] == [] and blocks_to_text(pl) == ""
    print("ok: cleared plan")

asyncio.run(main())
print("smoke_plan: all ok")
