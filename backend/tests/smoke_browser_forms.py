# 冒烟：v2.53 CORE 39 云浏览器表单控件（选哪项 / 按键名的规则在 browser/forms.py，有自己的单测；后端只管快照的说法
# element_line + browser_select / browser_press 两个工具）——模拟模型，无迁移。
# 1) element_line：下拉框带当前值 + 选项（超过 OPTIONS_SHOW 只列前面 + 共 N 项）、勾选框 ☑/☐、禁用标出、普通元素不变；
# 2) 一轮对话：打开预约页 → browser_select 发 /act select（text = 选项文字）→ 结果是新快照（值已变）；
#    服务回 400（对不上）→ 原因交回模型，模型照列出的项再选；browser_press（按需工具）发 /act press；
#    browser_select / browser_press 不在计划模式只读清单里，都算“通用动作”（claimed_action.GENERIC）。
# 运行：python tests/smoke_browser_forms.py
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

from app.agent import claimed_action, deferred

# ---- 1. element_line ----
L = browser_tool.element_line
assert L({"ref": "1", "tag": "a", "type": "", "name": "首页"}) == "[1] a 首页"
assert L({"ref": "2", "tag": "input", "type": "text", "name": "搜索"}) == "[2] input:text 搜索"
s = L({"ref": "3", "tag": "select", "type": "select-one", "name": "城市", "value": "请选择", "options": ["北京", "上海"], "count": 2})
assert s == "[3] select 城市 = 请选择（下拉框，用 browser_select；可选：北京、上海）", s
big = L({"ref": "4", "tag": "select", "type": "select-one", "name": "", "value": "", "options": [f"{i}点" for i in range(40)], "count": 60})
assert "（未选）" in big and "11点" in big and "12点" not in big and "…共 60 项" in big, big
assert L({"ref": "5", "tag": "input", "type": "checkbox", "name": "同意条款", "checked": True}) == "[5] input:checkbox ☑ 同意条款"
assert L({"ref": "6", "tag": "input", "type": "radio", "name": "", "checked": False}) == "[6] input:radio ☐"
assert L({"ref": "7", "tag": "button", "type": "submit", "name": "已售罄", "disabled": True}).endswith("（灰的，不能操作）")
assert "browser_select" not in plan_mode.READ_TOOLS and "browser_press" not in plan_mode.READ_TOOLS
assert {"browser_select", "browser_press"} <= claimed_action.GENERIC
print("ok: element_line")

# ---- 2. 一轮对话 ----
load_builtin()
from app.agent.tools import REGISTRY
assert not REGISTRY["browser_select"].deferred and REGISTRY["browser_press"].deferred
calls = []
SEL = {"ref": "1", "tag": "select", "type": "select-one", "name": "城市", "value": "请选择", "options": ["北京", "上海", "上海浦东"], "count": 3}
def page(value, text="预约"):
    return {"url": "https://book.test/", "title": "预约", "text": text, "elements": [dict(SEL, value=value)]}
async def fake_snapshot(session, method, path, body=None):
    calls.append((session, path, body))
    if path == "/goto":
        return dict(page("请选择"), restored=False, login={"signed_in": None, "expired": None})
    if body["action"] == "select":
        if body["text"] == "杭州":
            raise RuntimeError("下拉框里没有「杭州」，可选：「北京」、「上海」、「上海浦东」")
        return page(body["text"])
    if body["action"] == "press":
        return page("上海", "弹层已关")
    raise AssertionError(body)
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
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks("帮我在预约页选上海")))
        await db.commit()
        return await runner.run_turn(db, conv)

reply = asyncio.run(turn("c1", [[("browser_open", {"url": "https://book.test/"})], [("browser_select", {"ref": "1", "option": "杭州"})],
                                [("browser_select", {"ref": "1", "option": "上海"})], [("browser_press", {"key": "Escape"})], "选好上海了。"]))
st = [(s["tool"], s["state"]) for s in reply.steps]
assert ("browser_select", "done") in st and ("browser_press", "done") in st, st
contents = [m["content"] for m in tool_msgs]
assert any("没有「杭州」" in c and "「上海浦东」" in c for c in contents), contents
assert any("[1] select 城市 = 上海（下拉框" in c for c in contents), contents
assert ("book-test", "/act", {"action": "select", "ref": "1", "text": "上海"}) in calls, calls
assert ("book-test", "/act", {"action": "press", "text": "Escape", "ref": None}) in calls, calls
print("smoke_browser_forms OK")
