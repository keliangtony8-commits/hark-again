# 冒烟：v0.81 商品宫格 show_products + 订单卡 confirm_order / show_receipt。模拟模型（不打真接口），无迁移。
# - 商品：图打不开 → image 置空但商品保留；非 http 的 image/url 丢掉；没名字的项丢掉；最多 12 项。
# - 确认订单：审批卡就是订单卡本身（Tool.card）：用户批准 → 卡片 state=approved、工具结果让模型去付款 → show_receipt 出 placed 回执；
#   用户拒绝 → rejected、不出回执；参数不全 → 不出卡、不打扰用户、错误交回模型；无人值守（deny_all）→ rejected；
#   被停止 → partial() 把 pending 订单卡标 expired。
# - blocks_to_text / 分享网页都认识两种卡，且转义。
# 运行：python tests/smoke_commerce_cards.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, PUBLIC_URL="https://me.example",
  TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from pydantic import TypeAdapter
from app import llm, conversation_share
from app.agent import runner
from app.agent.loop import MessageBuilder
from app.agent.builtin import display
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.blocks import Block, blocks_to_text, text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message
from app.config import settings

BAD = "https://img.example/broken.jpg"
async def fake_probe(client, url):
    return url != BAD
display.probe_image = fake_probe

script: list = []
seen_tool_results: list[str] = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)

async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    if messages and messages[-1]["role"] == "tool":
        seen_tool_results.append(messages[-1]["content"])
    step = script.pop(0)
    async def gen():
        if isinstance(step, tuple):
            name, args = step
            yield chunk(tool=[NS(index=0, id=f"c{len(script)}", function=NS(name=name, arguments=json.dumps(args, ensure_ascii=False)))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()
for n in ("show_products", "confirm_order", "show_receipt"):
    assert n in REGISTRY, n
assert "show_products" in settings.system_prompt and "confirm_order" in settings.system_prompt

ORDER = {"merchant": "瑞幸咖啡 · 五道口店", "total": "¥32.00", "payment": "招行信用卡 9258", "destination": "6 号楼门口",
         "items": [{"name": "生椰拿铁<b>", "price": "¥29.00", "qty": 1, "note": "少冰"}, {"name": "可颂", "price": "¥9.00", "qty": 1}],
         "breakdown": [{"label": "配送费", "amount": "¥4.00"}, {"label": "优惠", "amount": "-¥10.00"}],
         "action": "确认下单并付款这句超过了十二个字"}
PRODUCTS = {"title": "三款耳机", "pick": "选 A：降噪最好",
            "items": [{"name": "A 耳机", "price": "¥899", "image": "https://img.example/a.jpg", "url": "https://shop.example/a", "meta": "4.8 分"},
                      {"name": "B 耳机", "price": "¥499", "image": BAD, "url": "javascript:alert(1)"},
                      {"name": "C 耳机", "image": "ftp://x/c.png"}, {"name": "  "}]}

async def turn(cid, approve):
    async with SessionLocal() as db:
        conv = Conversation(id=cid, title="买东西"); db.add(conv); await db.commit()
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks("帮我挑耳机，再点杯咖啡")))
        await db.commit()
        reply = await runner.run_turn(db, conv, approve=approve)
        msgs = (await conversation_share.load(db, cid)).messages
        return reply.blocks, msgs

asked = []
async def yes(aid, title, detail):
    asked.append((aid, title)); return True
async def no(aid, title, detail):
    asked.append((aid, title)); return False

# 1) 批准：宫格 → 参数不全的订单（不打扰用户）→ 正确订单 → 回执
script.extend([("show_products", PRODUCTS), ("confirm_order", {"merchant": "x", "items": []}), ("confirm_order", ORDER),
               ("show_receipt", {**ORDER, "order_number": "LK20261011"}), "下单了，大约 30 分钟送到。"])
blocks, msgs = asyncio.run(turn("c1", yes))
ta = TypeAdapter(Block)
for b in blocks:
    ta.validate_python(b)
types = [b["type"] for b in blocks]
assert types == ["products", "order", "order", "text"], types
pr = blocks[0]
assert [i["name"] for i in pr["items"]] == ["A 耳机", "B 耳机", "C 耳机"], pr
assert pr["items"][0]["image"] == "https://img.example/a.jpg" and pr["items"][1]["image"] is None and pr["items"][2]["image"] is None
assert pr["items"][1]["url"] is None and pr["pick"] == "选 A：降噪最好"
assert len(asked) == 1, asked  # 不全的那次没弹卡
assert "参数有误" in seen_tool_results[1], seen_tool_results
conf, rec = blocks[1], blocks[2]
assert conf["state"] == "approved" and conf["id"] == asked[0][0] and conf["action"] == "确认下单并付款这句超过了"[:12], conf
assert conf["total"] == "¥32.00" and conf["items"][0]["note"] == "少冰" and conf["breakdown"][1]["amount"] == "-¥10.00"
assert "用户已在订单卡上确认" in seen_tool_results[2], seen_tool_results
assert rec["state"] == "placed" and rec["order_number"] == "LK20261011" and rec["id"] != conf["id"]

text = blocks_to_text(blocks)
assert "[商品「三款耳机」" in text and "A 耳机 ¥899 4.8 分 https://shop.example/a" in text and "推荐：选 A" in text, text
assert "合计 ¥32.00——用户已确认" in text and "订单号 LK20261011" in text, text

page = conversation_share.render(NS(title="买东西"), msgs)
assert 'class="products"' in page and 'src="https://img.example/a.jpg"' in page and BAD not in page and "javascript:" not in page
assert "瑞幸咖啡 · 五道口店 · 已下单 · 订单号 LK20261011" in page and "&lt;b&gt;" in page and "生椰拿铁<b>" not in page

# 2) 拒绝：卡片 rejected、模型被告知别绕过
script.extend([("confirm_order", ORDER), "好的，不买了。"])
blocks, _ = asyncio.run(turn("c2", no))
assert [b["type"] for b in blocks] == ["order", "text"] and blocks[0]["state"] == "rejected", blocks
assert "没有批准" in seen_tool_results[-1], seen_tool_results[-1]

# 3) 无人值守（定时任务）默认 deny_all
script.extend([("confirm_order", ORDER), "需要你确认。"])
async def unattended():
    async with SessionLocal() as db:
        conv = Conversation(id="c3", title="t"); db.add(conv); await db.commit()
        db.add(Message(conversation_id="c3", role="user", blocks=text_to_blocks("买")))
        await db.commit()
        return (await runner.run_turn(db, conv)).blocks
assert asyncio.run(unattended())[0]["state"] == "rejected"

# 4) 停止时 pending 订单卡过期
mb = MessageBuilder(); mb.add({**REGISTRY["confirm_order"].card(ORDER), "id": "z", "state": "pending"})
assert mb.partial()[0]["state"] == "expired"

# 5) 回执没订单号 / 宫格全空
async def call(name, **kw):
    async with SessionLocal() as db:
        return await REGISTRY[name].run(ToolContext(db=db, conversation_id="c1"), **kw)
r = asyncio.run(call("show_receipt", **{**ORDER, "order_number": " "}))
assert not r.blocks and "订单号" in r.content
r = asyncio.run(call("show_products", items=[{"name": ""}]))
assert not r.blocks
r = asyncio.run(call("show_products", items=[{"name": f"n{i}"} for i in range(20)]))
assert len(r.blocks[0]["items"]) == 12
print("ok: commerce cards (products / order confirm / receipt)")
