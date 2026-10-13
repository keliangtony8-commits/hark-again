# 冒烟：v2.56 CORE 40 网页原生弹框（browser/dialogs.py 规则；后端只管说法 dialog_note + click/press 的 confirm）——模拟模型，无迁移。
# 1) dialog_note：提示框 / 离开提示 / 已确定 / 默认取消 / 说好取消 / 连环 / more / 坏数据；2) confirm → dialog=accept，
#    付款删除类按钮（已过审批）自动 accept，普通按钮不带；3) 一轮对话：点“移除地址”→ 确认框被默认取消 → 结果最前面说
#    “没有生效 … confirm=true” → 模型带 confirm 再点 → 请求带 dialog=accept → 提示框原话交给模型。
# 运行：python tests/smoke_browser_dialogs.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from app import llm, plan_mode, web_guard
from app.agent import runner
from app.agent.builtin import browser as browser_tool
from app.agent.tools import load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message

# ---- 1. dialog_note ----
N = browser_tool.dialog_note
assert N({}) == "" and N({"dialogs": "x"}) == "" and N({"dialogs": ["x", {"kind": "weird", "message": "?"}]}).count("⤷") == 1
a = N({"dialogs": [{"kind": "alert", "message": "手机号格式不对", "accepted": True, "auto": True}]})
assert "提示框" in a and "「手机号格式不对」" in a and "成没成功" in a, a
assert "离开" in N({"dialogs": [{"kind": "beforeunload", "message": "", "accepted": True, "auto": True}]})
c = N({"dialogs": [{"kind": "confirm", "message": "确定移除？", "accepted": False, "auto": True}]})
assert "没有生效" in c and "confirm=true" in c and "先问用户" in c, c
ok = N({"dialogs": [{"kind": "prompt", "message": "备注", "accepted": True, "auto": False, "text": "放门口"}]})
assert "点了确定" in ok and "「放门口」" in ok, ok
assert "点了取消" in N({"dialogs": [{"kind": "confirm", "message": "x", "accepted": False, "auto": False}]})
f = N({"dialogs": [{"kind": "confirm", "message": "x", "accepted": False, "auto": True, "flood": True}]})
assert "连着弹框" in f and "confirm=true" not in f, f
assert "3 个框" in N({"dialogs": [{"kind": "more", "more": 3}]})
print("ok: note")

# ---- 2. confirm → dialog 字段 ----
from app import browser_sessions
sent = []
real_act = browser_tool._act
async def cap(ctx, method, path, json=None):
    sent.append(json)
    return "ok"
browser_tool._act = cap
ctx0 = NS(conversation_id="cx", task_id=None)
t = browser_sessions.tab("cx", None)
t.names.update({"1": "移除地址", "2": "立即支付"})
asyncio.run(browser_tool.browser_click(ctx0, "1"))
asyncio.run(browser_tool.browser_click(ctx0, "1", confirm=True, prompt_text="放门口"))
asyncio.run(browser_tool.browser_click(ctx0, "2"))
asyncio.run(browser_tool.browser_press(ctx0, "Enter", confirm=True))
assert sent[0] == {"action": "click", "ref": "1"}, sent
assert sent[1] == {"action": "click", "ref": "1", "dialog": "accept", "dialog_text": "放门口"}, sent
assert sent[2]["dialog"] == "accept", sent  # 付款按钮已过审批卡：跟着的“确定支付？”直接确定
assert sent[3] == {"action": "press", "text": "Enter", "ref": None, "dialog": "accept"}, sent
browser_tool._act = real_act
print("ok: arm")

# ---- 3. 一轮对话 ----
load_builtin()
calls = []
ADDR = {"url": "https://shop.test/addr", "title": "地址", "text": "上海市 …", "elements": [{"ref": "1", "tag": "button", "type": "", "name": "移除地址"}]}
SNAPS = {
    "/goto": {**ADDR, "restored": False, "login": {"signed_in": None, "expired": None}},
    "click": {**ADDR, "dialogs": [{"kind": "confirm", "message": "确定移除这个地址吗？", "accepted": False, "auto": True}]},
    "click2": {**ADDR, "text": "暂无地址", "elements": [],
               "dialogs": [{"kind": "confirm", "message": "确定移除这个地址吗？", "accepted": True, "auto": False},
                           {"kind": "alert", "message": "已移除", "accepted": True, "auto": True}]},
}
async def fake_snapshot(session, method, path, body=None):
    calls.append((session, path, body))
    if path == "/act":
        return dict(SNAPS["click2" if body.get("dialog") == "accept" else "click"])
    return dict(SNAPS[path])
browser_tool.browser_client.snapshot_call = fake_snapshot
async def no_files(ws, session):
    return NS(note="", files=[])
browser_tool.browser_files.collect = no_files
async def public(host):
    return ["93.184.216.34"]
web_guard.resolve = public

script: list = []
tool_msgs: list[dict] = []
n = [0]
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    messages = [dict(m) for m in messages]
    tool_msgs.extend(m for m in messages if m["role"] == "tool" and m not in tool_msgs)
    step = script.pop(0)
    async def gen():
        if isinstance(step, list):
            calls_ = []
            for i, (nm, a) in enumerate(step):
                n[0] += 1
                calls_.append(NS(index=i, id=f"c{n[0]}", function=NS(name=nm, arguments=json.dumps(a, ensure_ascii=False))))
            yield chunk(tool=calls_)
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create

async def turn(cid, steps):
    script.extend(steps)
    async with SessionLocal() as db:
        conv = Conversation(id=cid, title="t"); db.add(conv); await db.commit()
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks("把这个地址删了")))
        await db.commit()
        return await runner.run_turn(db, conv)

reply = asyncio.run(turn("c1", [[("browser_open", {"url": "https://shop.test/addr"})], [("browser_click", {"ref": "1"})],
                                [("browser_click", {"ref": "1", "confirm": True})], "地址已移除。"]))
by = [s for s in reply.steps if s["tool"] == "browser_click"]
assert len(by) == 2 and all(s["state"] == "done" for s in by), reply.steps
contents = [m["content"] for m in tool_msgs]
first = next(c for c in contents if "没有生效" in c)
assert first.startswith("⤷ 网页弹出确认框：「确定移除这个地址吗？」") and first.index("⤷") < first.index("页面：地址"), first
second = next(c for c in contents if "暂无地址" in c)
assert "已按你说的点了确定" in second and "「已移除」" in second, second
acts = [b for s, p, b in calls if p == "/act"]
assert acts == [{"action": "click", "ref": "1"}, {"action": "click", "ref": "1", "dialog": "accept"}], acts
print("smoke_browser_dialogs OK")
