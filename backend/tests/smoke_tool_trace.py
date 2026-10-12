# 冒烟：跨轮工具轨迹（app/agent/tool_trace.py，移植 Codex normalize 配对 + 记录时截断）。
# 一、规则：配对清洗（缺结果补 ABORTED、孤儿结果丢、轮内 user 消息丢）、结果中间截断带原长、参数长串截短、私密参数打码、
#     密钥行打码、页面快照占位、超额从最早批次丢、valid/replay/digest；
# 二、整轮（假模型，真 runner.run_turn）：第一轮调工具 → 回复存了 trace（不上协议）；第二轮模型看到的历史里有
#     上一轮的 assistant tool_calls + tool 结果 + 回复文字，且配对合法；history_trace_turns=1 时只放最近一条，
#     更早的回复只有一行工具摘要；被停下的一轮也留下轨迹（缺结果的补 ABORTED）；关掉（0）只剩摘要；老消息没 trace 不出错；
#     迁移 down/up。
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", LLM_MAX_RETRIES="0")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import llm
from app.config import settings
from app.agent import tool_trace as tt, runner, supersede
from app.agent.tools import ToolResult, tool, load_builtin
from app.db import SessionLocal
from app.models import Conversation, Message

def call(cid, name, args):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}

# —— 一、规则 ——
msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"},
        {"role": "assistant", "content": "我先看看", "tool_calls": [call("a", "run_command", {"command": "ls"}), call("b", "read_file", {"path": "x"})]},
        {"role": "tool", "tool_call_id": "b", "content": "B 的结果"},
        {"role": "tool", "tool_call_id": "zz", "content": "孤儿"},
        {"role": "user", "content": "（轮内提醒）"},
        {"role": "tool", "tool_call_id": "a", "content": "A 的结果"},
        {"role": "assistant", "content": None, "tool_calls": [call("c", "browser_type", {"ref": "3", "text": "我的密码"}),
                                                              call("d", "write_file", {"path": "big.txt", "content": "x" * 5000})]},
        {"role": "tool", "tool_call_id": "c", "content": "页面：登录\nhttps://a.com\n\n可操作元素：\n[1] 按钮"},
        {"role": "assistant", "content": None, "tool_calls": [call("e", "run_command", {"command": "cat .env"})]},
        {"role": "tool", "tool_call_id": "e", "content": "API_KEY=sk-123456\nok\n" + "y" * 4000}]
tr = tt.record(msgs, 2, limit=100000)
assert tt.valid(tr), tr
roles = [m["role"] for m in tr]
assert roles == ["assistant", "tool", "tool", "assistant", "tool", "tool", "assistant", "tool"], roles
assert tr[0]["content"] is None                                   # 轮内叙述不重复存
assert [t["tool_call_id"] for t in tr[1:3]] == ["a", "b"]          # 顺序跟调用一致
assert tr[1]["content"] == "A 的结果" and "孤儿" not in json.dumps(tr, ensure_ascii=False)
assert "轮内提醒" not in json.dumps(tr, ensure_ascii=False)
assert tr[5]["tool_call_id"] == "d" and tr[5]["content"] == tt.ABORTED  # 缺结果补
a3 = json.loads(tr[3]["tool_calls"][0]["function"]["arguments"])
assert a3 == {"ref": "3", "text": tt.MASK}                         # 私密输入打码
a4 = json.loads(tr[3]["tool_calls"][1]["function"]["arguments"])
assert len(a4["content"]) < 400 and "5000" in a4["content"] and a4["path"] == "big.txt"
assert supersede.PLACEHOLDER in tr[4]["content"] and "[1] 按钮" not in tr[4]["content"]
out = tr[7]["content"]
assert "sk-123456" not in out and "API_KEY=" in out and out.startswith("[原结果 ") and "省略" in out and len(out) < tt.OUTPUT_MAX + 200
# 超额：从最早批次丢，至少留最新一批
small = tt.record(msgs, 2, limit=10)
assert [m["role"] for m in small] == ["assistant", "tool"] and small[0]["tool_calls"][0]["id"] == "e"
assert tt.record(msgs, 2, limit=0) == []
assert tt.record(msgs, len(msgs)) == []
# 解析不了的参数存 {}
bad = tt.record([{"role": "assistant", "tool_calls": [{"id": "q", "function": {"name": "x", "arguments": "{oops"}}]}], 0)
assert bad[0]["tool_calls"][0]["function"]["arguments"] == "{}" and bad[1]["content"] == tt.ABORTED
# valid
assert not tt.valid([]) and not tt.valid(None) and not tt.valid([{"role": "tool", "tool_call_id": "a", "content": ""}])
assert not tt.valid(tr[:2])                                        # 缺 b
assert not tt.valid([{"role": "user", "content": "x"}])
rp = tt.replay(tr, "完成了")
assert rp[-1] == {"role": "assistant", "content": "完成了"} and rp[0] is not tr[0]
# digest
d = tt.digest([{"tool": "run_command", "title": "运行命令", "detail": "ls", "state": "done"},
               {"tool": "compact_context", "title": "整理上文", "state": "done"},
               {"tool": "read_file", "title": "读文件", "detail": "a.py", "state": "error"},
               {"tool": "x", "title": "删东西", "state": "denied"}, {"tool": "y", "title": "装包", "state": "stopped"}])
assert d == "\n\n[这一轮用过的工具：运行命令 ls；读文件 a.py（失败）；删东西（没批准）；装包（没做完）]", d
assert tt.digest([]) == "" and tt.digest(None) == ""
long = tt.digest([{"title": "运行命令", "detail": "x" * 100, "state": "done"}] * 20)
assert "共 20 步" in long and len(long) < tt.DIGEST_MAX + 40
print("ok: rules")

# —— 二、整轮 ——
@tool("fake_ls", "正在列文件", "测试用", {"type": "object", "properties": {"path": {"type": "string"}}})
async def fake_ls(ctx, path: str = ".") -> ToolResult:
    return ToolResult(f"{path} 里有 report-{path}.pdf")

@tool("fake_card", "正在出卡片", "测试用", {"type": "object", "properties": {"path": {"type": "string"}}})
async def fake_card(ctx, path: str = ".") -> ToolResult:
    return ToolResult(f"{path} 里有 report-{path}.pdf", blocks=[{"type": "code", "language": "", "source": path}])

@tool("fake_slow", "正在慢慢做", "测试用", {"type": "object", "properties": {}})
async def fake_slow(ctx) -> ToolResult:
    await asyncio.sleep(30)
    return ToolResult("不会到这")

script, saw = [], []
def chunk(text=None, tools=None, u=None):
    if text is None and tools is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tools))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    saw.append(json.loads(json.dumps(messages, ensure_ascii=False)))
    step = script.pop(0) if script else "好了"
    async def gen():
        if isinstance(step, list):
            yield chunk(tools=[NS(index=i, id=f"k{len(saw)}_{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                               for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=100, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()

def pairs_ok(messages):
    """OpenAI 规则：每个 tool 紧跟在有它 id 的 assistant tool_calls 之后，且每个调用都有结果。"""
    pending = set()
    for m in messages:
        if m["role"] == "tool":
            assert m["tool_call_id"] in pending, m
            pending.discard(m["tool_call_id"])
        else:
            assert not pending, (pending, m)
            if m["role"] == "assistant" and m.get("tool_calls"):
                pending = {c["id"] for c in m["tool_calls"]}
    assert not pending

async def turn(cid, text, *steps):
    script[:] = list(steps); saw.clear()
    async with SessionLocal() as db:
        if not await db.get(Conversation, cid):
            db.add(Conversation(id=cid, title="t"))
        db.add(Message(conversation_id=cid, role="user", blocks=[{"type": "text", "text": text}]))
        await db.commit()
        conv = await db.get(Conversation, cid)
        return await runner.run_turn(db, conv)

async def main():
    m1 = await turn("c1", "看看 docs 里有什么", [("fake_ls", {"path": "docs"})], "docs 里有一份报告")
    assert m1 and m1.trace and tt.valid(m1.trace) and "trace" not in m1.to_wire()
    assert m1.trace[1]["content"] == "docs 里有 report-docs.pdf"
    await turn("c1", "刚才那个文件叫什么？", "叫 report-docs.pdf")
    hist = saw[0]
    pairs_ok(hist)
    names = [c["function"]["name"] for m in hist if m.get("tool_calls") for c in m["tool_calls"]]
    assert names == ["fake_ls"], names
    i = next(k for k, m in enumerate(hist) if m.get("tool_calls"))
    assert hist[i - 1]["content"] == "看看 docs 里有什么" and hist[i + 1]["role"] == "tool"
    assert hist[i + 2] == {"role": "assistant", "content": "docs 里有一份报告"}  # 重放的回复不带摘要行（轨迹已经说明了）
    print("ok: trace replayed next turn")

    # 第三轮：两条带轨迹的回复都在（默认 2）；改成 1 → 只放最近一条，更早的回复变成一行摘要
    await turn("c1", "再看 src", [("fake_ls", {"path": "src"})], "src 里也有")
    await turn("c1", "汇总", "两个目录各一份")
    assert sum(1 for m in saw[0] if m.get("tool_calls")) == 2
    pairs_ok(saw[0])
    settings.history_trace_turns = 1
    await turn("c1", "再汇总", "同上")
    h = saw[0]
    pairs_ok(h)
    calls = [c for m in h if m.get("tool_calls") for c in m["tool_calls"]]
    assert len(calls) == 1 and json.loads(calls[0]["function"]["arguments"]) == {"path": "src"}
    old = next(m for m in h if m["role"] == "assistant" and m.get("content", "").startswith("docs 里有一份报告"))
    assert "[这一轮用过的工具：列文件 docs]" in old["content"], old
    print("ok: only newest N replayed, older get digest")

    # 被停下：已完成的调用留结果，没完成的补 ABORTED
    script[:] = [[("fake_card", {"path": "a"})], [("fake_slow", {})]]; saw.clear()
    async with SessionLocal() as db:
        db.add(Conversation(id="c2", title="t"))
        db.add(Message(conversation_id="c2", role="user", blocks=[{"type": "text", "text": "干活"}]))
        await db.commit()
        conv = await db.get(Conversation, "c2")
        stop = asyncio.Event()
        task = asyncio.create_task(runner.run_turn(db, conv, stop=stop))
        while len(saw) < 2:
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.2)
        stop.set(); task.cancel()
        m2 = await task
    assert m2 is None or m2.status == "stopped"
    async with SessionLocal() as db:
        from sqlalchemy import select
        rows = (await db.scalars(select(Message).where(Message.conversation_id == "c2", Message.role == "assistant"))).all()
    assert rows and rows[-1].status == "stopped"
    t = rows[-1].trace
    assert tt.valid(t) and t[-1]["content"] == tt.ABORTED and t[1]["content"] == "a 里有 report-a.pdf", t
    print("ok: stopped turn keeps trace with ABORTED")

    # 关掉：不存、不放，只剩摘要
    settings.history_trace_turns, settings.history_trace_chars = 2, 0
    m3 = await turn("c3", "看 x", [("fake_ls", {"path": "x"})], "x 里有")
    assert m3.trace == []
    await turn("c3", "然后？", "没了")
    assert not any(m.get("tool_calls") for m in saw[0])
    assert any("[这一轮用过的工具：列文件 x]" in (m.get("content") or "") for m in saw[0])
    settings.history_trace_chars = 6000
    # 老消息（迁移前，trace = []）+ 坏数据：退回摘要，不出错
    async with SessionLocal() as db:
        db.add(Conversation(id="c4", title="t"))
        db.add(Message(conversation_id="c4", role="user", blocks=[{"type": "text", "text": "旧问"}]))
        await db.commit()
        db.add(Message(conversation_id="c4", role="assistant", blocks=[{"type": "text", "text": "旧答"}],
                       trace=[{"role": "tool", "tool_call_id": "x", "content": "坏"}],
                       steps=[{"tool": "fake_ls", "title": "列文件", "detail": "old", "state": "done"}]))
        await db.commit()
    await turn("c4", "新问", "新答")
    pairs_ok(saw[0])
    assert not any(m["role"] == "tool" for m in saw[0])
    assert any("旧答" in (m.get("content") or "") and "列文件 old" in m["content"] for m in saw[0])
    print("ok: off / legacy / bad trace")

asyncio.run(main())

r = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0032"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr
print("ok: migration down/up")
print("ALL OK")
