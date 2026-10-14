# 冒烟：继续追问子助手（v1.97，agent/subagent_threads.py 移植自 Codex resume_agent 的冷恢复，嫁接 deepseek-harness 续聊子助手）。
# 一、tidy 规则（去系统提示、剪没收尾的工具调用、截短工具结果、超长丢最早的输出）；二、校验（编号格式、同一个续两次、没 prompt）；
# 三、WS 整轮：派一个子助手（做一步工具再交结论）→ 卡片带编号、上下文存库、交回主助手的文字带编号；
#     主助手 continue 续问 → 子助手收到原来的全部上下文 + 新问题、系统提示带“续问”、卡片 round 2、标题沿用、库里 rounds 2；
#     别的对话的编号 / 不存在的编号 → 找不到；
# 四、用户在卡片点“追问”（user.message 带 follow）→ agent 块带 target/title、当前一问给 FOLLOW 提示、主助手照提示续问、下一轮只剩记录；
#     上下文不在了 → gone 块 + GONE 提示；编辑这条消息追问块保留；回答途中补充带 follow 不插队；开关关了当普通消息；
# 五、被停下的子助手：存下的上下文剪掉没收尾的调用；六、每段对话最多 KEEP 个；七、迁移 down / up。
# 运行：python tests/smoke_subagent_resume.py
import os, sys, asyncio, subprocess, tempfile, json
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, MODEL_ROUTER="off",
  AUTO_TITLE="false", NEXT_SPEAKER_CHECK="off",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from app import agent_mentions as am, llm, steering
from app.agent import loop, subagent, subagent_threads as th, tools
tools.load_builtin()
from app.auth import issue_token, require_user
from app.blocks import blocks_to_text, AgentBlock, DelegateBlock
from app.config import settings
from app.db import SessionLocal
from app.models import Conversation, Message, SubagentThread
from app.routes import conversations as rc, ws as rws

# —— 一、tidy ——
call = lambda i: {"id": i, "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "任务：a\n\nx"},
        {"role": "assistant", "content": None, "tool_calls": [call("1")]}, {"role": "tool", "tool_call_id": "1", "content": "y" * 5000},
        {"role": "assistant", "content": "中间话", "tool_calls": [call("2"), call("3")]}, {"role": "tool", "tool_call_id": "2", "content": "z"}]
t = th.tidy(msgs)
assert [m["role"] for m in t] == ["user", "assistant", "tool"], t           # 2 有结果、3 没有 → 整步剪掉
assert t[2]["content"].endswith(th.CLIPPED) and len(t[2]["content"]) == th.TOOL_KEEP + len(th.CLIPPED)
assert msgs[3]["content"] == "y" * 5000                                     # 不改原列表
full = th.tidy([*msgs[:4], {"role": "assistant", "content": "结论"}])
assert full[-1] == {"role": "assistant", "content": "结论"}
assert th.tidy([{"role": "user", "content": "a"}, {"role": "assistant", "content": ""}]) == [{"role": "user", "content": "a"}]
big = [{"role": "user", "content": "q"}]
for i in range(60):
    big += [{"role": "assistant", "content": None, "tool_calls": [call(str(i))]}, {"role": "tool", "tool_call_id": str(i), "content": "w" * 1400}]
big.append({"role": "assistant", "content": "完"})
tb = th.tidy(big)
assert sum(len(th._text(m)) for m in tb) <= th.HISTORY_MAX and tb[2]["content"] == th.DROPPED and tb[-2]["content"] == "w" * 1400
assert th.valid_id(th.new_id()) and not th.valid_id("sa_xyz123") and not th.valid_id("sa_12") and not th.valid_id(None)
print("ok: tidy")

# —— 二、校验 ——
def bad(tasks, why):
    try:
        subagent.normalize(tasks)
    except subagent.DelegateError as e:
        assert why in str(e), (why, str(e)); return
    raise AssertionError(tasks)
bad([{"continue": "abc", "prompt": "x"}], "sa_1a2b3c")
bad([{"continue": "sa_aaaaaa", "prompt": "x"}, {"continue": "sa_aaaaaa", "prompt": "y"}], "一次只能续问一次")
bad([{"continue": "sa_aaaaaa", "prompt": " "}], "没有 prompt")
r = subagent.normalize([{"continue": "sa_aaaaaa", "prompt": "再查"}, {"title": "新", "prompt": "x"}])
assert r[0].resume and r[0].id == "sa_aaaaaa" and r[0].title == "" and not r[1].resume and th.valid_id(r[1].id)
print("ok: validation")

# —— 三、WS ——
seen: list[tuple[str, list[dict], str]] = []
plan: list = []   # 主助手每次调用的动作（按顺序弹出）；空了 = 回一句“好”
CHILD_TOOL_ONCE = True

async def fake_stream_turn(messages, tools=None, model=None, effort=None):
    msgs = json.loads(json.dumps(messages, ensure_ascii=False))
    system = msgs[0]["content"] if msgs and msgs[0]["role"] == "system" else ""
    if subagent.ROLE in system:
        seen.append(("child", msgs, system))
        last = msgs[-1]
        if last["role"] == "user" and last["content"].startswith("任务："):   # 刚派出去：先读个文件
            yield llm.Turn(tool_calls=[llm.ToolCall(f"r{len(seen)}", "list_files", "{}")])
            return
        n = sum(1 for m in msgs if m["role"] == "user")
        yield f"子结论第{n}次"
        yield llm.Turn(text=f"子结论第{n}次")
        return
    seen.append(("main", msgs, system))
    step = plan.pop(0) if plan else None
    if callable(step):
        step = step(msgs)
    if step is not None:
        yield llm.Turn(tool_calls=[llm.ToolCall(f"m{len(seen)}", "delegate", json.dumps({"tasks": step}, ensure_ascii=False))])
        return
    yield "好"
    yield llm.Turn(text="好")
loop.stream_turn = fake_stream_turn
async def fake_complete(messages, model=None, kind="summary", **kw):
    return "摘要"
llm.complete = fake_complete

app = FastAPI()
for r_ in (rws.router, rc.router):
    app.include_router(r_)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
token = issue_token()

def turn(ws, event):
    ws.send_json(event)
    first = None
    while True:
        e = ws.receive_json()
        first = first or e
        if e["type"] in ("message.done", "error"):
            assert e["type"] == "message.done", e
            return first, e

def card(done):
    d = [x for x in done["message"]["blocks"] if x["type"] == "delegate"]
    assert len(d) == 1, done["message"]["blocks"]
    DelegateBlock(**d[0])
    return d[0]["tasks"]

def last_tool(kind="main"):
    msgs = [m for k, m, _ in seen if k == kind][-1]
    return [m["content"] for m in msgs if m["role"] == "tool"][-1]

async def threads(cid=None):
    async with SessionLocal() as db:
        q = select(SubagentThread)
        if cid:
            q = q.where(SubagentThread.conversation_id == cid)
        return (await db.scalars(q.order_by(SubagentThread.updated_at))).all()

async def user_rows(cid):
    async with SessionLocal() as db:
        return [m.blocks for m in (await db.scalars(select(Message).where(Message.conversation_id == cid, Message.role == "user")
                                                     .order_by(Message.created_at))).all()]

def main_users(i=-1):
    msgs = [m for k, m, _ in seen if k == "main"][i]
    return [m["content"] for m in msgs if m["role"] == "user" and isinstance(m["content"], str)]

with c.websocket_connect(f"/ws?token={token}") as ws:
    plan[:] = [[{"title": "查价格", "prompt": "查三家价格"}]]
    first, done = turn(ws, {"type": "user.message", "text": "帮我查价格"})
    cid = first["conversation_id"]
    t1 = card(done)[0]
    sid = t1["id"]
    assert th.valid_id(sid) and t1["state"] == "done" and t1["result"] == "子结论第1次" and "round" not in t1, t1
    back = last_tool()
    assert f"编号 {sid}" in back and "continue" in back, back
    rows = asyncio.run(threads(cid))
    assert len(rows) == 1 and rows[0].id == sid and rows[0].rounds == 1 and rows[0].title == "查价格" and rows[0].model == "fast"
    hist = th.history_of(rows[0])
    assert [m["role"] for m in hist] == ["user", "assistant", "tool", "assistant"] and hist[-1]["content"] == "子结论第1次", hist
    print("ok: first delegate stored")

    # 主助手续问
    plan[:] = [[{"continue": sid, "prompt": "再查第四家"}]]
    seen.clear()
    _, done = turn(ws, {"type": "user.message", "conversation_id": cid, "text": "再看看第四家"})
    t2 = card(done)[0]
    assert t2["id"] == sid and t2["round"] == 2 and t2["title"] == "查价格" and t2["result"] == "子结论第2次", t2
    child_msgs, child_sys = [(m, s) for k, m, s in seen if k == "child"][0]
    assert child_msgs[1]["content"] == "任务：查价格\n\n查三家价格" and child_msgs[-1]["content"].endswith("再查第四家")
    assert "子结论第1次" in json.dumps(child_msgs, ensure_ascii=False) and subagent.RESUMED in child_sys
    assert "帮我查价格" not in json.dumps(child_msgs, ensure_ascii=False)   # 仍看不到主对话
    assert "第 2 轮" in last_tool()
    rows = asyncio.run(threads(cid))
    assert len(rows) == 1 and rows[0].rounds == 2 and th.history_of(rows[0])[-1]["content"] == "子结论第2次"
    print("ok: resume by model")

    # 别的对话的编号 / 不存在
    plan[:] = [[{"continue": sid, "prompt": "x"}]]
    first, done = turn(ws, {"type": "user.message", "text": "另一段"})
    assert "找不到子助手" in last_tool() and not [x for x in done["message"]["blocks"] if x["type"] == "delegate"]
    other = first["conversation_id"]
    plan[:] = [[{"continue": "sa_000000", "prompt": "x"}]]
    turn(ws, {"type": "user.message", "conversation_id": cid, "text": "瞎续"})
    assert "找不到子助手" in last_tool()
    print("ok: foreign / unknown refused")

    # —— 四、用户点“追问” ——
    def follow_step(msgs):
        last = msgs[-1]["content"]
        assert "<system_note>" in last and f'continue: "{sid}"' in last, last
        return [{"continue": sid, "prompt": "第四家的运费呢"}]
    plan[:] = [follow_step]
    _, done = turn(ws, {"type": "user.message", "conversation_id": cid, "text": "运费呢", "follow": sid, "follow_title": "乱写的"})
    b = asyncio.run(user_rows(cid))[-1]
    ag = [x for x in b if x["type"] == "agent"]
    assert ag == [{**am.BLOCK, "target": sid, "title": "查价格"}], b   # 标题以库里的为准
    AgentBlock(**ag[0])
    assert blocks_to_text(b) == "运费呢\n\n[追问子助手「查价格」]"
    assert card(done)[0]["round"] == 3
    turn(ws, {"type": "user.message", "conversation_id": cid, "text": "谢谢"})
    hist = main_users()
    assert any(am.FOLLOW_RECORD.format(title="查价格", target=sid) in h for h in hist) and not any("<system_note>" in h for h in hist)

    # 编辑那条追问：块保留（先回到它是最后一条用户消息的状态：新对话里再来一次）
    plan[:] = [[{"title": "看评论", "prompt": "看评论"}]]
    first, done = turn(ws, {"type": "user.message", "text": "看评论"})
    cid2, sid2 = first["conversation_id"], card(done)[0]["id"]
    plan[:] = [[{"continue": sid2, "prompt": "差评呢"}]]
    turn(ws, {"type": "user.message", "conversation_id": cid2, "text": "差评呢", "follow": sid2})
    plan[:] = [[{"continue": sid2, "prompt": "只看差评"}]]
    turn(ws, {"type": "message.regenerate", "conversation_id": cid2, "text": "只看差评"})
    b = asyncio.run(user_rows(cid2))[-1]
    assert b[0]["text"] == "只看差评" and [x["target"] for x in b if x["type"] == "agent"] == [sid2], b

    # 上下文不在了（别的对话的编号）→ gone
    plan[:] = []
    turn(ws, {"type": "user.message", "conversation_id": other, "text": "运费呢", "follow": sid, "follow_title": "查价格"})
    ag = [x for x in asyncio.run(user_rows(other))[-1] if x["type"] == "agent"]
    assert ag == [{**am.BLOCK, "target": sid, "title": "查价格", "gone": True}], ag
    assert main_users()[-1].endswith(am.GONE.format(title="查价格", target=sid))
    # 编号格式不对 / 开关关了 → 普通消息
    turn(ws, {"type": "user.message", "conversation_id": other, "text": "嗯", "follow": "xx"})
    assert not [x for x in asyncio.run(user_rows(other))[-1] if x["type"] == "agent"]
    settings.subagent_max_tasks = 0
    turn(ws, {"type": "user.message", "conversation_id": cid, "text": "运费", "follow": sid})
    assert not [x for x in asyncio.run(user_rows(cid))[-1] if x["type"] == "agent"]
    settings.subagent_max_tasks = 4
    print("ok: user follow-up")

# 回答途中补充带 follow：不插队
inbox = steering.open_inbox(cid)
inbox.start()
assert asyncio.run(rws._intake({"conversation_id": cid, "text": "运费", "follow": sid})) is False
assert asyncio.run(rws._intake({"conversation_id": cid, "text": "运费"})) is True
steering.close(inbox)
print("ok: steer refuses follow")

# —— 五、被停下：剪掉没收尾的调用 ——
async def stopped_case():
    async with SessionLocal() as db:
        db.add(Conversation(id="cs", title="t")); await db.commit()
        ok = await th.save(db, "cs", "sa_abcdef", "停", "fast", "stopped",
                           [{"role": "system", "content": "s"}, {"role": "user", "content": "任务：停\n\nx"},
                            {"role": "assistant", "content": "先看看", "tool_calls": [call("9")]}], False)
        assert not ok   # 只有一个没结果的调用 → 没东西可续
        ok = await th.save(db, "cs", "sa_abcdef", "停", "fast", "stopped",
                           [{"role": "user", "content": "任务：停\n\nx"},
                            {"role": "assistant", "content": None, "tool_calls": [call("1")]}, {"role": "tool", "tool_call_id": "1", "content": "r"},
                            {"role": "assistant", "content": None, "tool_calls": [call("2")]}], False)
        await db.commit()
        assert ok
        row = await th.load(db, "cs", "sa_abcdef")
        assert row.state == "stopped" and [m["role"] for m in th.history_of(row)] == ["user", "assistant", "tool"]
        assert await th.load(db, "other", "sa_abcdef") is None
        # —— 六、最多 KEEP 个 ——
        for i in range(th.KEEP + 3):
            await th.save(db, "cs", f"sa_{i:06x}", f"t{i}", "fast", "done",
                          [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}], False)
            await db.commit()
        left = (await db.scalars(select(SubagentThread.id).where(SubagentThread.conversation_id == "cs"))).all()
        assert len(left) == th.KEEP and "sa_abcdef" not in left and "sa_000000" not in left and f"sa_{th.KEEP + 2:06x}" in left
asyncio.run(stopped_case())
print("ok: stopped + keep")

# —— 七、迁移 ——
r = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0045"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr
print("ok: migration")
print("ALL OK")
