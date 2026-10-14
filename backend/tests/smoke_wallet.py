# 冒烟：v2.74 钱包（app/wallet.py）+ browser_pay_card。模拟模型 + 假浏览器，不打真接口。
# 1) 规则：卡号清洗 / 卡组织 / Luhn（银联放宽）/ 有效期（两位年、过期、太远）/ 安全码位数（运通 4 位）/ find（id、名字、尾号、唯一卡组织）
#    / may_fill（没订单、订单超时、付款方式不是这张卡、卡过期）/ frame_block（同站、支付机构放行，别家框拦）
#    / fields（合并有效期按占位 YYYY、月年下拉框多种写法、缺持卡人报错、没卡号报错）/ scrub（带空格的整串卡号抹成尾号）
#    / order_covers_click（付款类按钮 + 刚批准的单才放行，删除/发送不放行）。
# 2) 接口：加卡（坏卡号 400、重复 409）、列表只有尾号、改名、删除；库里只有密文。
# 3) 一轮（经 deferred_tool call）：没订单就代填 → 被拒；confirm_order 批准 → 代填（卡号进浏览器请求，不进模型上下文、
#    回复块、步骤、库里消息）→ 点“提交订单”不再弹第二张审批卡 → show_receipt；系统提示里有卡的描述、没有卡号。
# 4) 定时任务（无人值守）：confirm_order 被拒 → 代填被拒，浏览器从没收到卡号。
# 运行：python tests/smoke_wallet.py
import os, sys, asyncio, subprocess, tempfile, json, base64, time
from datetime import date
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY=base64.urlsafe_b64encode(os.urandom(32)).decode(),
  DATA_DIR=tmp, TIMEZONE="Asia/Shanghai", CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from types import SimpleNamespace as NS
import httpx
from sqlalchemy import select
from app import llm, browser_client, browser_sessions as bs, wallet as W
from app.agent import runner
from app.agent.tools import load_builtin, REGISTRY
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message, PaymentCard

VISA = "4111 1111 1111 1111"
NUM = "4111111111111111"
TODAY = date(2026, 10, 14)

# ---- 1. 规则 ----
assert W.check_number(VISA) == (NUM, "visa")
assert W.check_number("5500-0000-0000-0004")[1] == "mastercard" and W.check_number("2221000000000009")[1] == "mastercard"
assert W.check_number("378282246310005")[1] == "amex" and W.check_number("6011111111111117")[1] == "discover"
assert W.check_number("3530111333300000")[1] == "jcb"
assert W.check_number("6212345678901234")[1] == "unionpay"           # 银联不过 Luhn 也收
for bad in ("4111 1111 1111 1112", "4111", "4111x11111111111", ""):
    try:
        W.check_number(bad); raise AssertionError(bad)
    except W.CardError:
        pass
assert W.check_expiry(9, 28, TODAY) == (9, 2028) and W.check_expiry("10", "2026", TODAY) == (10, 2026)
for m, y in ((9, 2026), (13, 2028), (1, 2050), ("a", 28)):
    try:
        W.check_expiry(m, y, TODAY); raise AssertionError((m, y))
    except W.CardError:
        pass
assert W.check_cvc("123", "visa") == "123" and W.check_cvc("1234", "amex") == "1234" and W.check_cvc("1234", "card")
for c, b in (("1234", "visa"), ("123", "amex"), ("12a", "visa")):
    try:
        W.check_cvc(c, b); raise AssertionError((c, b))
    except W.CardError:
        pass

def card(**kw):
    d = dict(id="k1", label="招行信用卡", brand="visa", last4="1111", exp_month=9, exp_year=2028, holder="ZHANG SAN", postal_code="100080")
    d.update(kw)
    return PaymentCard(**d)
a, b = card(), card(id="k2", label="工资卡", brand="unionpay", last4="1234")
assert W.find([a, b], "k2") is b and W.find([a, b], "工资卡") is b and W.find([a, b], "尾号 1111 那张") is a
assert W.find([a, b], "银联") is b and W.find([a, b], "建行") is None and W.find([a], "") is a and W.find([], "x") is None
assert W.describe(a) == "招行信用卡（Visa 尾号 1111，有效期到 2028 年 9 月，没过期）"
assert "已过期" in W.describe(card(exp_year=2020))
assert W.prompt_line([]) == "" and "browser_pay_card" in W.prompt_line([a]) and NUM not in W.prompt_line([a])

tab = bs.Tab(session="s", url="https://shop.example.com/checkout")
assert "confirm_order" in W.may_fill(tab, a)
W.remember_order(tab, "招行信用卡 尾号 1111", "¥32.00")
assert W.may_fill(tab, a) is None
assert "不是" in W.may_fill(tab, b)                                         # 订单卡写的不是这张
assert "过期" in W.may_fill(tab, card(exp_year=2020))
W.remember_order(tab, "Visa 1111", "¥32.00", now=time.time() - W.ORDER_TTL_S - 1)
assert "confirm_order" in W.may_fill(tab, a)                                 # 批准太久了
W.remember_order(tab, "Visa 1111", "¥32.00")
assert W.order_covers_click(tab, "提交订单") and W.order_covers_click(tab, "Pay ¥32.00")
assert not W.order_covers_click(tab, "删除地址") and not W.order_covers_click(tab, "继续") and not W.order_covers_click(tab, "")
W.forget_order(tab)
assert not W.order_covers_click(tab, "提交订单")

tab.frames = {"7": "js.stripe.com", "8": "evil.example.net", "9": "pay.example.com"}
assert W.frame_block(tab, ["3", "7", "9"]) is None and W.frame_block(tab, ["3", "8"]) == "evil.example.net"

sec = {"number": NUM, "cvc": "123"}
f = W.fields(a, sec, {"number": "3", "exp": "4", "cvc": "5"}, {"4": "MM/YY"})
assert [(x["ref"], x["value"], x["secret"]) for x in f] == [("3", NUM, True), ("4", "09/28", False), ("5", "123", True)]
assert W.fields(a, sec, {"number": "3", "exp": "4"}, {"4": "有效期 MM / YYYY"})[1]["value"] == "09/2028"
f = W.fields(a, sec, {"number": "3", "exp_month": "4", "exp_year": "5", "holder": "6", "postal": "7"}, {})
assert f[1]["options"][:3] == ["09", "9", "9月"] and "Sep" in f[1]["options"] and f[2]["options"][:2] == ["2028", "28"]
assert f[3]["value"] == "ZHANG SAN" and f[4]["value"] == "100080"
for refs, c in (({"number": "3", "holder": "6"}, card(holder="")), ({"cvc": "5"}, a)):
    try:
        W.fields(c, sec, refs, {}); raise AssertionError(refs)
    except W.CardError:
        pass
names = {"3": "卡号", "4": "MM/YY", "5": "安全码", "6": "持卡人姓名", "7": "提交订单", "8": "邮编"}
assert W.guess_refs({"number": "3"}, names, a) == ({"number": "3", "exp": "4", "cvc": "5", "holder": "6", "postal": "8"}, ["exp", "cvc", "holder", "postal"])
assert W.guess_refs({"number": "3", "exp_month": "9"}, names, card(holder="", postal_code=""))[1] == ["cvc"]
assert W.guess_refs({"number": "3"}, {**names, "9": "CVV"}, a)[0].get("cvc") is None      # 两个框都像安全码：判不准不补
assert W.typing_block("卡号", "4111") and W.typing_block("CVV", "123") and W.typing_block("备注", "4111 1111 1111 1111")
assert W.typing_block("手机号", "13800001111") is None and W.typing_block("收货人", "张三") is None
assert W.typing_block("订单号", "2026101412345678") is None                         # 不过 Luhn 的长数字不拦
assert "browser_pay_card" in W.order_hint([a], "招行信用卡 尾号 1111") and W.order_hint([a], "支付宝") == ""
assert W.scrub("卡号 4111 1111 1111 1111 已填，订单 2026101412345678", NUM, "1111") == "卡号 •••• 1111 已填，订单 2026101412345678"

# ---- 2. 接口 ----
from app.main import app
from app.auth import issue_token

async def routes():
    h = {"Authorization": f"Bearer {issue_token()}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/wallet", json={"number": "4111 1111 1111 1112", "exp_month": 9, "exp_year": 30, "cvc": "123"}, headers=h)
        assert r.status_code == 400 and "校验" in r.json()["detail"], r.text
        r = await c.post("/api/wallet", json={"number": VISA, "exp_month": 9, "exp_year": 30, "cvc": "123", "label": " 招行  信用卡 ",
                                              "holder": "ZHANG SAN", "postal_code": "100 080"}, headers=h)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["label"] == "招行 信用卡" and j["last4"] == "1111" and j["exp"] == "09/30" and j["brand_name"] == "Visa"
        assert j["postal_code"] == "100080" and not j["expired"] and NUM not in r.text and "123" not in json.dumps({k: v for k, v in j.items() if k not in ("id", "created_at")})
        r = await c.post("/api/wallet", json={"number": VISA, "exp_month": 9, "exp_year": 2030, "cvc": "123"}, headers=h)
        assert r.status_code == 409, r.text
        r = await c.patch(f"/api/wallet/{j['id']}", json={"label": "招行信用卡"}, headers=h)
        assert r.status_code == 200 and r.json()["label"] == "招行信用卡"
        r = await c.post("/api/wallet", json={"number": "6212345678901234", "exp_month": 1, "exp_year": 2029, "cvc": "456", "label": "工资卡"}, headers=h)
        lst = (await c.get("/api/wallet", headers=h)).json()
        assert [x["label"] for x in lst] == ["招行信用卡", "工资卡"] and NUM not in json.dumps(lst)
        r = await c.delete(f"/api/wallet/{r.json()['id']}", headers=h)
        assert r.status_code == 200 and len((await c.get("/api/wallet", headers=h)).json()) == 1
        assert (await c.get("/api/wallet")).status_code == 401
        return j["id"]
CARD_ID = asyncio.run(routes())

async def raw():
    async with SessionLocal() as db:
        c = (await db.scalars(select(PaymentCard))).one()
        assert NUM not in c.ciphertext and W.reveal(c) == {"number": NUM, "cvc": "123"}
asyncio.run(raw())

# ---- 3. 一轮 ----
calls: list = []
CHECKOUT = {"url": "https://shop.example.com/checkout", "title": "结算", "text": "应付 ¥32.00",
            "elements": [{"ref": "3", "tag": "input", "type": "text", "name": "卡号"},
                         {"ref": "4", "tag": "input", "type": "text", "name": "MM/YY"},
                         {"ref": "5", "tag": "input", "type": "text", "name": "安全码"},
                         {"ref": "6", "tag": "button", "type": "submit", "name": "提交订单"}]}
async def fake_snap(session, method, path, body=None):
    calls.append((path, body))
    if path == "/goto":
        return {**CHECKOUT, "login": {}}
    if path == "/card":
        return {**CHECKOUT, "text": "应付 ¥32.00 卡号 4111 1111 1111 1111"}  # 网站回显整串卡号也不能给模型
    if path == "/act":
        return {**CHECKOUT, "url": "https://shop.example.com/done", "text": "下单成功 订单号 SO123", "elements": []}
    return CHECKOUT
browser_client.snapshot_call = fake_snap
async def no_files(ws, session):
    return NS(note="", files=[])
from app import browser_files
browser_files.collect = no_files

seen: list = []
script: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
n_ids = [0]
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append({"messages": [dict(m) for m in messages], "tools": [t["function"]["name"] for t in tools or []]})
    step = script.pop(0)
    async def gen():
        if isinstance(step, tuple):
            n_ids[0] += 1
            yield chunk(tool=[NS(index=0, id=f"w{n_ids[0]}", function=NS(name=step[0], arguments=json.dumps(step[1], ensure_ascii=False)))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()
assert REGISTRY["browser_pay_card"].deferred

ORDER = {"merchant": "瑞幸咖啡", "items": [{"name": "生椰拿铁", "price": "¥32.00"}], "total": "¥32.00", "payment": "招行信用卡 尾号 1111"}
pay = lambda **a: ("deferred_tool", {"action": "call", "tool": "browser_pay_card", "arguments": a})
PAY = dict(card="招行信用卡", number="3")  # 只给卡号框：有效期 / 安全码按框名补（B43）
asked: list = []
async def yes(aid, title, detail):
    asked.append(title); return True

async def seed(cid, text, task=False):
    async with SessionLocal() as db:
        conv = Conversation(id=cid, title="买咖啡"); db.add(conv); await db.commit()
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks(text)))
        await db.commit()

script.extend([("browser_open", {"url": "https://shop.example.com/checkout"}), pay(**PAY), ("confirm_order", ORDER), pay(**PAY),
               ("browser_click", {"ref": "6"}), ("show_receipt", {**ORDER, "order_number": "SO123"}), "付好了，订单号 SO123。"])
asyncio.run(seed("w1", "用我的招行卡把购物车结了"))
async def turn(cid, approve=None):
    async with SessionLocal() as db:
        kw = {"approve": approve} if approve else {}
        return await runner.run_turn(db, await db.get(Conversation, cid), **kw)
reply = asyncio.run(turn("w1", yes))
assert asked == ["确认下单"], asked                                  # 只问了一次：订单卡；付款按钮不再问
tool_texts = [m["content"] for m in seen[-1]["messages"] if m.get("role") == "tool"]
assert any("还没有用户刚批准的订单" in x for x in tool_texts), tool_texts
assert any("付款方式是钱包里的 招行信用卡" in x for x in tool_texts), tool_texts
assert any("已用 招行信用卡（Visa 尾号 1111" in x and "•••• 1111" in x for x in tool_texts), tool_texts
cards_sent = [b for p, b in calls if p == "/card"]
assert len(cards_sent) == 1 and cards_sent[0]["fields"][0] == {"ref": "3", "value": NUM, "options": [NUM], "secret": True}
assert cards_sent[0]["fields"][1]["value"] == "09/30" and cards_sent[0]["fields"][2]["value"] == "123"
assert any(p == "/act" for p, _ in calls)
sys_prompt = seen[0]["messages"][0]["content"]
assert "招行信用卡（Visa 尾号 1111，有效期到 2030 年 9 月，没过期）" in sys_prompt and NUM not in sys_prompt
dump = json.dumps(reply.blocks, ensure_ascii=False) + json.dumps(reply.steps, ensure_ascii=False) + json.dumps(seen, ensure_ascii=False)
assert NUM not in dump and "4111 1111 1111 1111" not in dump, "卡号绝不能进模型上下文、回复或步骤"
assert [b["state"] for b in reply.blocks if b["type"] == "order"] == ["approved", "placed"]
async def after():
    async with SessionLocal() as db:
        msgs = (await db.scalars(select(Message).where(Message.conversation_id == "w1"))).all()
        assert all(NUM not in json.dumps(m.blocks, ensure_ascii=False) for m in msgs)
        c = await db.get(PaymentCard, CARD_ID)
        assert c.last_used_at is not None
asyncio.run(after())
assert bs.tab("w1", None).order is None                               # 回执后这一单不再放行

# ---- 4. 无人值守：订单卡被拒 → 代填被拒，浏览器没收到卡号 ----
calls.clear(); seen.clear()
script.extend([("browser_open", {"url": "https://shop.example.com/checkout"}), ("confirm_order", ORDER), pay(**PAY), "需要你确认订单。"])
asyncio.run(seed("w2", "结账"))
reply = asyncio.run(turn("w2"))
assert not [1 for p, _ in calls if p == "/card"]
tool_texts = [m["content"] for m in seen[-1]["messages"] if m.get("role") == "tool"]
assert any("还没有用户刚批准的订单" in x for x in tool_texts), tool_texts
print("ok: wallet (rules / routes / pay-card turn / unattended)")
