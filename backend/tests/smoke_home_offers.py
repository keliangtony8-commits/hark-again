# 冒烟：v0.85 智能体提议的 Home 建议卡 offer_on_home（app/home_offers.py）。模拟模型，迁移 0020。
# - 模型在一轮对话里调 offer_on_home → home_cards 多一张 action 卡：origin=agent、未读、正文=理由、按钮字、点按钮的指令；
# - 同标题再提 → 原地更新（不叠卡、重新未读、稍后提醒被清掉）；
# - 最多 MAX_LIVE 张：第 6 张挤掉最旧的智能体建议，系统提醒（origin 空）不动；
# - 参数不合格（没指令、按钮字太长、没标题）→ 不建卡，中文原因交回模型；按钮写“去做”= 存空；
# - 接口 /api/cards 带 action_label / origin；manage_home list 标出“你提议的”和按钮；无人值守（定时任务）也能放。
# 运行：python tests/smoke_home_offers.py
import os, sys, asyncio, subprocess, tempfile, json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from app import llm, home_offers
from app.agent import runner
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.auth import require_user
from app.blocks import text_to_blocks
from app.config import settings
from app.db import SessionLocal
from app.models import Conversation, HomeCard, Message
from app.routes.resources import routers

script: list = []
tool_results: list[str] = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)

async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    if messages and messages[-1]["role"] == "tool":
        tool_results.append(messages[-1]["content"])
    if tools is not None:
        assert any(t["function"]["name"] == "offer_on_home" or "- offer_on_home：" in t["function"]["description"]
                   for t in tools)  # v2.05 起是按需工具：在 deferred_tool 的目录里
    step = script.pop(0)
    async def gen():
        if isinstance(step, tuple):
            yield chunk(tool=[NS(index=0, id=f"c{len(script)}", function=NS(name=step[0], arguments=json.dumps(step[1], ensure_ascii=False)))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()
assert "offer_on_home" in REGISTRY and "offer_on_home" in settings.system_prompt

app = FastAPI()
for r in routers:
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)

OFFER = {"title": "续费校园网", "reason": "周五到期，今天续还有 9 折。", "label": "帮我续费",
         "prompt": "打开 net.school.edu 用保险箱里的账号续费校园网一个月，价格超过 30 元先问我。"}

async def turn(cid, steps):
    script.extend(steps)
    async with SessionLocal() as db:
        conv = Conversation(id=cid, title="t"); db.add(conv); await db.commit()
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks("校园网快到期了，回头提醒我")))
        await db.commit()
        return await runner.run_turn(db, conv)

async def call(name, **kw):
    async with SessionLocal() as db:
        return (await REGISTRY[name].run(ToolContext(db=db), **kw)).content

cards = lambda: [x for x in c.get("/api/cards").json() if x["kind"] == "action" and not x["dismissed"]]

# 1) 对话里提议（无人值守 = 默认 approve，offer 本身不需要批准）
reply = asyncio.run(turn("c1", [("offer_on_home", OFFER), "放到主页了，点“帮我续费”我就去办。"]))
assert "已放到 Home：「续费校园网」" in tool_results[-1] and "按钮“帮我续费”" in tool_results[-1], tool_results
live = cards()
assert len(live) == 1, live
card = live[0]
assert card["origin"] == "agent" and card["unread"] is True and card["action_label"] == "帮我续费", card
assert card["action_prompt"] == OFFER["prompt"] and card["blocks"][0]["text"] == OFFER["reason"], card
assert [b["type"] for b in reply.blocks] == ["text"], reply.blocks  # 不在聊天里出卡

# 2) 稍后提醒后同标题再提 → 原地更新、叫回来
assert c.patch(f"/api/cards/{card['id']}", json={"snoozed_until": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(),
                                                  "unread": False}).status_code == 200
out = asyncio.run(call("offer_on_home", **{**OFFER, "reason": "明天就到期了。", "label": "去做"}))
assert out.startswith("已更新 Home"), out
live = cards()
assert len(live) == 1 and live[0]["id"] == card["id"], live
assert live[0]["snoozed_until"] is None and live[0]["unread"] is True and live[0]["action_label"] is None, live[0]
assert live[0]["blocks"][0]["text"] == "明天就到期了。"

# 3) 不合格
assert "prompt" in asyncio.run(call("offer_on_home", title="x", prompt="  "))
assert "太长" in asyncio.run(call("offer_on_home", title="x", prompt="y", label="这是一个超过十二个字的按钮文字"))
assert "标题" in asyncio.run(call("offer_on_home", title=" ", prompt="y"))
assert len(cards()) == 1

# 4) 上限：系统提醒不算也不动；第 6 张智能体建议挤掉最旧的
async def seed_alert():
    async with SessionLocal() as db:
        db.add(HomeCard(kind="action", title="本月花费已到 80%", blocks=[], target="usage", unread=True)); await db.commit()
asyncio.run(seed_alert())
for i in range(home_offers.MAX_LIVE - 1):
    asyncio.run(call("offer_on_home", title=f"建议{i}", prompt=f"做第 {i} 件事"))
assert len([x for x in cards() if x["origin"] == "agent"]) == home_offers.MAX_LIVE
out = asyncio.run(call("offer_on_home", title="新建议", prompt="做新的事"))
assert "收起了较旧的：「续费校园网」" in out, out
mine = [x for x in cards() if x["origin"] == "agent"]
assert len(mine) == home_offers.MAX_LIVE and "续费校园网" not in [x["title"] for x in mine], mine
assert any(x["title"] == "本月花费已到 80%" for x in cards())

# 5) manage_home list
listing = asyncio.run(call("manage_home", action="list"))
assert "「新建议」 · 你提议的 · 按钮“去做” · 未读" in listing, listing
assert "「本月花费已到 80%」 · 未读" in listing, listing

# 6) 接口新建也能带按钮字
r = c.post("/api/cards", json={"kind": "action", "title": "接口卡", "action_prompt": "x", "action_label": "看看"})
assert r.status_code == 200 and r.json()["action_label"] == "看看" and r.json()["origin"] is None, r.json()
print("ok")
