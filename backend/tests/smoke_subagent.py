# 冒烟：子助手 delegate（agent/subagent.py，移植自 Gemini CLI local-executor / generalist-agent，嫁接 deepseek-harness tool-subagent、Codex multi_agents）。
# 一、参数校验；二、历史文字 / 块校验；三、模拟模型整轮：两个子助手并行、各自独立上下文与工具白名单（无 delegate / 浏览器 / 问用户）、
#     子助手写的文件主助手能看到、结论交回主助手、聊天里一张实时卡片原地更新、时间线一步带标题；
# 四、步数预算 → partial（最后一步无工具 + 收尾提示）；五、一个出错不连累另一个，全错 → 这一步记 error；
# 六、硬超时 → failed；七、这一轮被停 → 卡片 stopped；八、需要批准的命令在子助手里直接拒绝。
import os, sys, asyncio, subprocess, tempfile, json, time
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import llm
from app.config import settings
from app.blocks import blocks_to_text, DelegateBlock
from app.agent import loop, subagent
from app.agent.tools import ToolContext, load_builtin, REGISTRY
from app.db import SessionLocal
from app.models import Conversation
from app.storage import project_dir
from app.workspaces import of as workspace_of

# —— 一、校验 ——
def bad(tasks, why):
    try:
        subagent.normalize(tasks)
    except subagent.DelegateError as e:
        assert why in str(e), (why, str(e)); return
    raise AssertionError(f"应当拒绝：{tasks}")

T = lambda *xs: [{"title": a, "prompt": b} for a, b in xs]
assert [t.title for t in subagent.normalize(T((" 查 \n价格 ", "查三家的价格")))] == ["查 价格"]
bad(None, "非空数组"); bad([], "非空数组"); bad("x", "非空数组")
bad(["查价格"], "对象")
bad([{"prompt": "x"}], "title"); bad(T(("查", "  ")), "没有 prompt")
bad(T(("a", "x"), ("a", "y")), "重复")
bad(T(*[(f"t{i}", "x") for i in range(settings.subagent_max_tasks + 1)]), "最多")
bad(T(("a", "长" * (subagent.PROMPT_MAX + 1))), "太长")
assert len(subagent.normalize(T(("标" * 40, "x")))[0].title) == subagent.TITLE_MAX
old = settings.subagent_max_tasks; settings.subagent_max_tasks = 0
bad(T(("a", "x")), "关闭"); settings.subagent_max_tasks = old
print("ok: validation")

# —— 二、块 / 历史 ——
b = {"type": "delegate", "tasks": [{"title": "查价格", "state": "done", "steps": 3, "seconds": 12, "result": "便宜"},
                                   {"title": "看评论", "state": "partial", "steps": 20}]}
DelegateBlock(**b)
assert blocks_to_text([b]) == "[子任务：查价格（完成）；看评论（交了半截）]"
assert blocks_to_text([{"type": "delegate", "tasks": []}]) == ""
print("ok: block / history")

# —— 三… 整轮 ——
load_builtin()
assert "delegate" in REGISTRY and "delegate" not in subagent.CHILD_TOOLS
assert subagent.CHILD_TOOLS <= set(REGISTRY), subagent.CHILD_TOOLS - set(REGISTRY)  # 名单里每个都是真工具

scripts: dict[str, list] = {}   # "parent" / 子任务标题 → 每次调用的回复
calls: dict[str, list] = {}     # 同上 → 每次收到的 (messages, tools)
active, peak = 0, 0
boom: set[str] = set()
slow: dict[str, float] = {}

def chunk(text=None, tools=None, u=None):
    if text is None and tools is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tools))], usage=u)

def who(messages):
    if subagent.ROLE in messages[0]["content"]:
        first = messages[1]["content"]
        return first.split("\n", 1)[0].removeprefix("任务：")
    return "parent"

async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    global active, peak
    k = who(messages)
    calls.setdefault(k, []).append((json.loads(json.dumps(messages, ensure_ascii=False)), [t["function"]["name"] for t in tools or []]))
    if k in boom:
        raise RuntimeError("模型网关 502")
    if k != "parent":
        active += 1; peak = max(peak, active)
        try:
            await asyncio.sleep(slow.get(k, 0.15))
        finally:
            active -= 1
    seq = scripts.get(k) or []
    step = seq.pop(0) if seq else f"{k} 的结论"
    async def gen():
        if isinstance(step, list):
            yield chunk(tools=[NS(index=i, id=f"{k}{len(calls[k])}_{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                               for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=100, completion_tokens=10))
    return gen()
llm.client.chat.completions.create = fake_create
n = 0

async def turn(*parent, builder=None, stop_after=None):
    global n
    n += 1
    scripts["parent"] = list(parent); calls.clear()
    cid = f"c{n}"
    async with SessionLocal() as db:
        db.add(Conversation(id=cid, title="t")); await db.commit()
        evs = []
        agen = loop.run("sys", [{"role": "user", "content": "帮我调研"}], ToolContext(db=db, conversation_id=cid), builder)
        async for e in agen:
            evs.append(e)
            if stop_after and stop_after(e):
                await agen.aclose()
                break
    return evs

def deleg(*xs):
    return [("delegate", {"tasks": T(*xs)})]

def tool_msg(k="parent"):
    return [m for m in calls[k][-1][0] if m["role"] == "tool"]

async def main():
    global peak
    ws = project_dir(workspace_of(None))
    # 三、并行两个
    scripts["写报告"] = [[("write_file", {"path": "notes/a.md", "content": "# 结论 A"})], "A：已写 notes/a.md"]
    scripts["查价格"] = [[("delegate", {"tasks": T(("再派", "x"))})], "B：最低 99 元"]
    peak = 0
    evs = await turn(deleg(("写报告", "写一份报告到 notes/a.md"), ("查价格", "查三家价格")), "两件事都做完了")
    assert peak == 2, peak  # 真的并行
    blocks = evs[-1].blocks
    d = [x for x in blocks if x["type"] == "delegate"]
    assert len(d) == 1 and "live" not in d[0], d
    by = {t["title"]: t for t in d[0]["tasks"]}
    assert by["写报告"]["state"] == "done" and by["写报告"]["steps"] == 1 and by["写报告"]["result"] == "A：已写 notes/a.md"
    assert by["查价格"]["state"] == "done" and by["查价格"]["result"] == "B：最低 99 元" and "seconds" in by["查价格"]
    assert (ws / "notes/a.md").read_text() == "# 结论 A"  # 同一个工作区
    # 子助手：独立上下文 + 白名单
    msgs, tools = calls["写报告"][0]
    assert msgs[1]["content"].startswith("任务：写报告\n\n写一份报告") and len(msgs) == 2
    assert "帮我调研" not in json.dumps(msgs, ensure_ascii=False)  # 看不到主对话
    assert set(tools) - {"deferred_tool"} <= subagent.CHILD_TOOLS and "write_file" in tools  # v2.05：按需工具的目录
    assert not {"delegate", "browser_open", "ask_user", "update_plan", "show_table", "remember"} & set(tools)
    assert "没有可用的工具 delegate" in tool_msg("查价格")[0]["content"]  # 深度 1
    # 交回主助手
    back = tool_msg()[0]["content"]
    assert back.startswith("2 个子任务已结束（完成 2 个）") and "## 1. 写报告（编号 sa_" in back and "— 完成（1 步" in back and "B：最低 99 元" in back
    # 实时卡片：插一次，之后原地换
    starts = [e for e in evs if isinstance(e, loop.BlockStart) and e.block["type"] == "delegate"]
    ups = [e for e in evs if isinstance(e, loop.BlockUpdate) and e.block["type"] == "delegate"]
    assert len(starts) == 1 and starts[0].block.get("live") and len(ups) >= 3
    assert any(t.get("now") == "正在写文件" for e in ups for t in e.block["tasks"])
    st = [e for e in evs if isinstance(e, loop.ToolStatus) and e.name == "delegate"]
    assert [s.state for s in st] == ["running", "done"] and st[0].step["detail"] == "写报告、查价格"
    assert [e for e in evs if isinstance(e, loop.ToolStatus) and e.name == "write_file"] == []  # 子助手的步骤不进主时间线
    print("ok: two children in parallel, isolated, results back, one live card")

    # 四、步数预算
    old = settings.subagent_max_steps; settings.subagent_max_steps = 2
    scripts["没完"] = [[("list_files", {})], "进度：找了一半"]
    evs = await turn(deleg(("没完", "一直找")), "好")
    t = [x for x in evs[-1].blocks if x["type"] == "delegate"][0]["tasks"][0]
    assert t["state"] == "partial" and "预算" in t["note"] and t["result"] == "进度：找了一半", t
    last_msgs, last_tools = calls["没完"][-1]
    assert last_tools == [] and last_msgs[-1]["content"] == subagent.WRAP_UP
    settings.subagent_max_steps = old
    print("ok: budget → partial with wrap-up")

    # 五、一个出错
    boom.add("坏的")
    evs = await turn(deleg(("坏的", "x"), ("好的", "y")), "好")
    by = {t["title"]: t for t in [x for x in evs[-1].blocks if x["type"] == "delegate"][0]["tasks"]}
    assert by["坏的"]["state"] == "failed" and "502" in by["坏的"]["note"] and by["好的"]["state"] == "done"
    st = [e for e in evs if isinstance(e, loop.ToolStatus) and e.name == "delegate"]
    assert st[-1].state == "done"
    evs = await turn(deleg(("坏的", "x")), "好")
    st = [e for e in evs if isinstance(e, loop.ToolStatus) and e.name == "delegate"]
    assert st[-1].state == "error" and st[-1].step["note"] == "子任务都没交回结论"
    boom.clear()
    print("ok: one failure isolated; all failed → error step")

    # 六、硬超时
    oldm, oldg = settings.subagent_minutes, subagent.GRACE_SECONDS
    settings.subagent_minutes, subagent.GRACE_SECONDS = 0.004, 0.2  # 0.24 s 截止 + 0.2 s 宽限
    slow["慢的"] = 3
    t0 = time.monotonic()
    evs = await turn(deleg(("慢的", "x")), "好")
    assert time.monotonic() - t0 < 2.5
    t = [x for x in evs[-1].blocks if x["type"] == "delegate"][0]["tasks"][0]
    assert t["state"] == "failed" and "分钟还没交结果" in t["note"], t
    settings.subagent_minutes, subagent.GRACE_SECONDS = oldm, oldg
    slow.clear()
    print("ok: hard timeout")

    # 七、这一轮被停
    slow["久"] = 5
    builder = loop.MessageBuilder()
    seen = []
    def stop(e):
        if isinstance(e, loop.BlockStart) and e.block["type"] == "delegate":
            seen.append(e)
        return bool(seen)
    await turn(deleg(("久", "x")), builder=builder, stop_after=stop)
    part = builder.partial()
    t = [x for x in part if x["type"] == "delegate"][0]
    assert "live" not in t and t["tasks"][0]["state"] == "stopped" and "now" not in t["tasks"][0]
    await asyncio.sleep(0.1)
    slow.clear()
    print("ok: stopped turn → stopped card")

    # 八、需要批准的命令：子助手里直接拒绝
    scripts["删库"] = [[("run_command", {"command": "rm -rf build"})], "没能执行，需要主助手请用户批准"]
    evs = await turn(deleg(("删库", "x")), "好")
    tm = tool_msg("删库")
    assert tm and "用户没有批准" in tm[0]["content"], tm
    assert not [x for x in evs[-1].blocks if x["type"] == "approval"]  # 不往主回复里插审批卡
    print("ok: risky command refused inside child")

asyncio.run(main())
print("smoke_subagent: all ok")
