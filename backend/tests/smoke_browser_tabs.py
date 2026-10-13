# 冒烟：v2.47 CORE 38 云浏览器标签页（browser/tabs.py 规则；后端只管说法 tab_note + browser_back 工具）——模拟模型，无迁移。
# 1) tab_note：五种变化各一句、没变化 / 坏数据 → 空；2) 一轮对话：打开 → 点链接（服务回 tab.opened）→ 工具结果最前面说
#    “新标签页、已切过去、browser_back”，画面卡网站跟着新页；browser_back 发 /act back；崩溃重开的说明交回模型；
#    计划模式把 browser_back 当只读。
# 运行：python tests/smoke_browser_tabs.py
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

# ---- 1. tab_note ----
N = browser_tool.tab_note
assert N({}) == "" and N({"tab": "x"}) == "" and N({"tab": {"kind": "weird"}}) == ""
o = N({"tab": {"kind": "opened", "url": "https://shop.test/item", "from": "https://shop.test/", "tabs": 2}})
assert "新标签页" in o and "https://shop.test/item" in o and "开着 2 个" in o and "browser_back" in o, o
assert "回到原来的 https://shop.test/" in N({"tab": {"kind": "returned", "url": "https://shop.test/", "tabs": 1}})
c = N({"tab": {"kind": "closed", "url": "https://shop.test/", "tabs": 1}})
assert "被网站关掉" in c and "开着" not in c, c
assert "browser_open" in N({"tab": {"kind": "closed", "url": "about:blank", "tabs": 1}})
k = N({"tab": {"kind": "crashed", "url": "https://heavy.test/"}})
assert k.startswith("⚠") and "内存" in k and "重新打开 https://heavy.test/" in k, k
l = N({"tab": {"kind": "crash_loop", "url": "https://heavy.test/"}})
assert "别再反复打开" in l and "web_fetch" in l, l
assert "browser_back" in plan_mode.READ_TOOLS
print("ok: note")

# ---- 2. 一轮对话 ----
load_builtin()
calls = []
SNAPS = {
    "/goto": {"url": "https://shop.test/", "title": "列表", "text": "商品", "elements": [{"ref": "1", "tag": "a", "type": "", "name": "商品一"}],
              "restored": False, "login": {"signed_in": None, "expired": None}},
    "click": {"url": "https://item.shop2.test/1", "title": "商品一", "text": "价格 99 元", "elements": [],
              "tab": {"kind": "opened", "url": "https://item.shop2.test/1", "from": "https://shop.test/", "tabs": 2}},
    "back": {"url": "https://shop.test/", "title": "列表", "text": "商品", "elements": [{"ref": "1", "tag": "a", "type": "", "name": "商品一"}],
             "tab": {"kind": "returned", "url": "https://shop.test/", "tabs": 1}},
    "/snapshot": {"url": "https://shop.test/", "title": "列表", "text": "商品", "elements": [],
                  "tab": {"kind": "crashed", "url": "https://shop.test/"}},
}
async def fake_snapshot(session, method, path, body=None):
    calls.append((session, path, body))
    return dict(SNAPS[body["action"] if path == "/act" else path])
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
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks("看看商品一多少钱")))
        await db.commit()
        return await runner.run_turn(db, conv)

reply = asyncio.run(turn("c1", [[("browser_open", {"url": "https://shop.test/"})], [("browser_click", {"ref": "1"})],
                                [("browser_back", {})], [("browser_read", {})], "商品一 99 元。"]))
by = {s["tool"]: s for s in reply.steps}
assert all(by[t]["state"] == "done" for t in ("browser_open", "browser_click", "browser_back", "browser_read")), reply.steps
contents = [m["content"] for m in tool_msgs]
click = next(c for c in contents if "价格 99 元" in c)
assert click.startswith("⤷ 网站在新标签页里打开了 https://item.shop2.test/1") and click.index("⤷") < click.index("页面：商品一"), click
assert any(c.startswith("⤷ 这个标签页没有上一页") for c in contents), contents
assert any(c.startswith("⚠ 页面崩溃了") for c in contents), contents
assert ("shop-test", "/act", {"action": "back"}) in calls, calls
cards = [b for b in reply.blocks if b.get("type") == "browser"]
assert cards and cards[0]["session"] == "shop-test", cards
print("smoke_browser_tabs OK")
