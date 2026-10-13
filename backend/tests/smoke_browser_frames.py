# 冒烟：v2.59 CORE 41 云浏览器内嵌框（收哪些框 / 编号 / 文字规则在 browser/frames.py，有自己的单测和真 Chromium 测试；
# 后端只管快照的说法和“密码框属于哪个网站”）——模拟模型，无迁移。
# 1) element_line：框里的元素标“（内嵌框 域名）”，同站框也标；frames_more → 列表末尾一句；
# 2) _render 记下跨站框里的 ref → Tab.frames；Tab.login_url / login_host：密码框在别家框里 → 那家，否则主页面；
# 3) 一轮对话：结账页（shop.test）里嵌了 accounts.pay.test 的登录框，保险箱两家都有：
#    browser_login 用框里的编号 → /login 填的是 accounts.pay.test 那条（绝不是 shop.test 的密码）；
#    _login_form 对框里的密码框写 accounts.pay.test，对主页面的密码框写 shop.test；
#    自动代填（_view）同样按密码框所属网站找保险箱：登录页只有别家框、保险箱没这家 → 不自动代填主站密码。
# 运行：python tests/smoke_browser_frames.py
import os, sys, asyncio, subprocess, tempfile, json, base64
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY=base64.urlsafe_b64encode(os.urandom(32)).decode(),
  DATA_DIR=tmp, TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from app import llm, vault, web_guard
from app.agent import runner
from app.agent.builtin import browser as browser_tool
from app.agent.tools import load_builtin
from app.blocks import text_to_blocks
from app.browser_sessions import Tab
from app.db import SessionLocal
from app.models import Conversation, Message

# ---- 1. element_line / frames_note ----
L = browser_tool.element_line
assert L({"ref": "4", "tag": "input", "type": "text", "name": "卡号", "frame": "js.stripe.com"}) == "[4] input:text 卡号（内嵌框 js.stripe.com）"
assert L({"ref": "2", "tag": "button", "type": "submit", "name": "使用", "frame": "同站"}).endswith("（内嵌框 同站）")
assert L({"ref": "1", "tag": "a", "type": "", "name": "首页"}) == "[1] a 首页"
assert browser_tool.frames_note({}) == "" and browser_tool.frames_note({"frames_more": 0}) == ""
assert "还有 3 个内嵌框没展开" in browser_tool.frames_note({"frames_more": 3})
print("ok: element_line / frames_note")

# ---- 2. Tab.frames / login_url ----
PAGE = {"url": "https://shop.test/checkout", "title": "结账", "text": "订单\n\n【内嵌框 · accounts.pay.test】\n登录付款账户",
        "elements": [{"ref": "1", "tag": "input", "type": "text", "name": "收货人"},
                     {"ref": "2", "tag": "input", "type": "password", "name": "会员密码"},
                     {"ref": "3", "tag": "input", "type": "text", "name": "优惠码", "frame": "同站"},
                     {"ref": "4", "tag": "input", "type": "email", "name": "付款账号", "frame": "accounts.pay.test"},
                     {"ref": "5", "tag": "input", "type": "password", "name": "付款密码", "frame": "accounts.pay.test"}],
        "frames_more": 1}
tab = Tab(session="shop-test")
text = browser_tool._render(PAGE, tab)
assert tab.frames == {"4": "accounts.pay.test", "5": "accounts.pay.test"}, tab.frames
assert "[5] input:password 付款密码（内嵌框 accounts.pay.test）" in text and "还有 1 个内嵌框没展开" in text
assert text.index("还有 1 个内嵌框") < text.index("页面文字：")
assert tab.login_url("5") == "https://accounts.pay.test/" and tab.login_host("5") == "accounts.pay.test"
assert tab.login_url("2") == tab.url and tab.login_host("2") == "shop.test" and tab.login_host(None) == "shop.test"
assert tab.login_host("3") == "shop.test"  # 同站框 = 主站
browser_tool._render({"url": "https://shop.test/", "elements": []}, tab)
assert tab.frames == {}  # 新快照清掉旧的
print("ok: Tab.frames / login_url")

# ---- 3. 一轮对话 ----
load_builtin()
calls = []
async def fake_snapshot(session, method, path, body=None):
    calls.append((session, path, body))
    if path == "/goto":
        return dict(PAGE, restored=False, login={"signed_in": None, "expired": None})
    if path == "/login":
        return dict(PAGE, text="订单\n\n【内嵌框 · accounts.pay.test】\n已登录付款账户", elements=PAGE["elements"][:1])
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

async def setup_vault():
    async with SessionLocal() as db:
        db.add(vault.create("shop", "SHOP-PW", ["shop.test"], kind="login", username="shopper"))
        db.add(vault.create("pay", "PAY-PW", ["accounts.pay.test"], kind="login", username="payer@x.cn"))
        await db.commit()
asyncio.run(setup_vault())

async def turn(cid, steps):
    script.extend(steps)
    async with SessionLocal() as db:
        conv = Conversation(id=cid, title="t"); db.add(conv); await db.commit()
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks("用付款账户登录后结账")))
        await db.commit()
        return await runner.run_turn(db, conv)

reply = asyncio.run(turn("c1", [[("browser_open", {"url": "https://shop.test/checkout"})],
                                [("browser_login", {"user_ref": "4", "pass_ref": "5"})], "付款账户已登录。"]))
st = [(s["tool"], s["state"]) for s in reply.steps]
assert ("browser_login", "done") in st, st
logins = [b for (_, p, b) in calls if p == "/login"]
assert logins == [{"user_ref": "4", "pass_ref": "5", "username": "payer@x.cn", "password": "PAY-PW"}], logins
assert not any("SHOP-PW" in m["content"] or "PAY-PW" in m["content"] for m in tool_msgs)
assert any("保险箱「pay」" in m["content"] for m in tool_msgs), [m["content"] for m in tool_msgs]
print("ok: browser_login 按框的域名取保险箱")

# _login_form：框里的密码框写那家，主页面的写主站（保险箱两家都有 → 不弹卡）；清掉 pay 那条 → 框里的弹卡写 accounts.pay.test
async def forms():
    from app.agent.builtin.browser import _login_form, _tab
    async with SessionLocal() as db:
        ctx = NS(db=db, conversation_id="c2", task_id=None)
        t = _tab(ctx)
        t.session = "shop-test"
        browser_tool._render(PAGE, t)
        assert await _login_form(ctx, {"user_ref": "4", "pass_ref": "5"}) is None
        assert await _login_form(ctx, {"user_ref": "1", "pass_ref": "2"}) is None
        from sqlalchemy import delete
        from app.models import Secret
        await db.execute(delete(Secret).where(Secret.name == "pay")); await db.commit()
        card = await _login_form(ctx, {"user_ref": "4", "pass_ref": "5"})
        assert card and card["site"] == "accounts.pay.test", card
        assert await _login_form(ctx, {"user_ref": "1", "pass_ref": "2"}) is None  # 主站那条还在
asyncio.run(forms())
print("ok: _login_form 站点按密码框所属网站")
print("smoke_browser_frames OK")
