# 冒烟：v0.95 系统提醒统一走 app/system_alerts.py + 连接失效提醒。模拟模型（不打真接口），无迁移（仍 0022）。
# - 模型调 api_request 读 GitHub，token 快过期、refresh 被服务商 400 拒绝 → 工具结果说“连接已失效…已经在主页放了提醒”，
#   Home 出现一张系统卡：target=connectors、没有 action_prompt（只能本人重连）、未读、origin 为空；
# - 同一份 token 再失效 → 不重复发卡；网络错误（连不上服务商）→ 原样报错、不发卡；
# - 重新连上（oauth.complete）→ 卡自动收起；新 token 被对方 401（撤销）→ 新卡；断开连接 → 收起；
# - 智能体提议的同去处卡（origin=agent）不被系统提醒收起；
# - 预算卡 / 任务失败卡也经 system_alerts（target usage / tasks+task_id），system_alerts.post 去处不认识 → ValueError。
# 运行：python tests/smoke_system_alerts.py
import os, sys, asyncio, subprocess, tempfile, json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from cryptography.fernet import Fernet
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY=Fernet.generate_key().decode(), DATA_DIR=tmp,
  TIMEZONE="Asia/Shanghai", GITHUB_CLIENT_ID="id", GITHUB_CLIENT_SECRET="sec")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from app import llm, system_alerts, vault
from app.agent import runner
from app.agent.tools import load_builtin
from app.auth import require_user
from app.blocks import text_to_blocks
from app.connectors import oauth
from app.connectors.providers import PROVIDERS
from app.db import SessionLocal
from app.models import Connection, Conversation, HomeCard, Message
from app.routes import connectors as rconn
from app.routes.resources import routers

# ---- 模拟模型：dict = 调 api_request，str = 文字 ----
script: list = []
tool_results: list = []

def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)

async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    tool_results.extend(m["content"] for m in messages if isinstance(m, dict) and m.get("role") == "tool")
    step = script.pop(0)
    async def gen():
        if isinstance(step, dict):
            yield chunk(tool=[NS(index=0, id=f"c{len(script)}", function=NS(name="api_request", arguments=json.dumps(step)))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()

app = FastAPI()
for r in [*routers, rconn.router]:
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)

# ---- 假的服务商：token 接口 + GitHub API ----
token_reply = {"mode": "refused"}
async def fake_token_request(p, data):
    m = token_reply["mode"]
    if m == "refused":
        raise httpx.HTTPStatusError("bad", request=httpx.Request("POST", p.token_url), response=httpx.Response(400))
    if m == "network":
        raise httpx.ConnectError("down")
    return {"access_token": f"tok-{m}", "refresh_token": "r2", "expires_in": 3600}
oauth._token_request = fake_token_request

api_status = {"code": 200}
real_client = httpx.AsyncClient
# 同一个 httpx 模块：api_request 和 oauth.complete 的 userinfo 都走它
# （web_guard.client 会带自己的 transport，这里整个换成假的）
httpx.AsyncClient = lambda **kw: real_client(**{**kw, "transport": httpx.MockTransport(
    lambda req: httpx.Response(api_status["code"], json={"login": "keliang"}))})

async def seed_connection(expired=True):
    async with SessionLocal() as db:
        conn = await db.scalar(select(Connection).where(Connection.provider == "github")) or Connection(provider="github")
        conn.account = "keliang"
        conn.ciphertext = vault.encrypt(json.dumps({"access_token": "old", "refresh_token": "r1", "n": os.urandom(4).hex()}))
        conn.expires_at = datetime.now(timezone.utc) + (timedelta(minutes=-5) if expired else timedelta(hours=1))
        db.add(conn); await db.commit()

async def turn(text, *steps):
    script.extend(steps)
    async with SessionLocal() as db:
        conv = Conversation(title="看仓库"); db.add(conv); await db.commit()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks(text))); await db.commit()
        reply = await runner.run_turn(db, conv)
        return reply.blocks

def live(target=None):
    return [x for x in c.get("/api/cards").json()
            if x["kind"] == "action" and not x["dismissed"] and (target is None or x["target"] == target)]

GET = {"url": "https://api.github.com/user"}

# 1) refresh 被拒 → 系统卡（只有去处）+ 工具结果告诉模型
asyncio.run(seed_connection())
asyncio.run(turn("看看我的 GitHub", GET, "你的 GitHub 连接失效了，去连接器页重连一下。"))
assert "GitHub 连接已失效" in tool_results[-1] and "已经在主页放了提醒" in tool_results[-1], tool_results
cards = live("connectors")
assert len(cards) == 1, cards
k = cards[0]
assert k["title"] == "GitHub 连接已失效" and k["action_prompt"] is None and k["unread"] and k["origin"] is None, k
assert "keliang" in k["blocks"][0]["text"] and "400" in k["blocks"][0]["text"], k

# 2) 同一份 token 再失效 → 不重复
asyncio.run(turn("再试一次", GET, "还是不行。"))
assert "已失效" in tool_results[-1] and len(live("connectors")) == 1

# 3) 网络错误 → 不算失效
token_reply["mode"] = "network"
try:
    asyncio.run(turn("再试", GET, "网络不通。"))
except Exception:
    pass
assert len(live("connectors")) == 1  # 没新卡

# 4) 智能体提议的同去处卡不被收起；重新连上 → 系统卡收起
async def agent_card():
    async with SessionLocal() as db:
        db.add(HomeCard(kind="action", origin="agent", title="连上 Google 日历", target="connectors", blocks=[]))
        await db.commit()
asyncio.run(agent_card())
token_reply["mode"] = "fresh"
async def reconnect():
    async with SessionLocal() as db:
        await oauth.complete(db, PROVIDERS["github"], "code")  # userinfo 也走上面的假 httpx（200 + login）
asyncio.run(reconnect())
left = live("connectors")
assert [x["title"] for x in left] == ["连上 Google 日历"], left

# 5) 新 token 被对方 401（撤销）→ 新卡；工具结果说明
api_status["code"] = 401
asyncio.run(turn("看看 issue", GET, "授权被撤销了。"))
assert "不再接受这个授权" in tool_results[-1], tool_results[-1]
sys_cards = [x for x in live("connectors") if x["origin"] is None]
assert len(sys_cards) == 1 and "撤销" in sys_cards[0]["blocks"][0]["text"], sys_cards

# 6) 断开连接 → 收起
assert c.delete("/api/connectors/github").json()["ok"]
assert [x["title"] for x in live("connectors")] == ["连上 Google 日历"]

# 7) 正常调用：200 不发卡
api_status["code"] = 200
asyncio.run(seed_connection(expired=False))
asyncio.run(turn("我是谁", GET, "你是 keliang。"))
assert "HTTP 200" in tool_results[-1] and "keliang" in tool_results[-1]
assert [x["origin"] for x in live("connectors")] == ["agent"]

# 8) 去处校验 + task 去处
async def bad():
    async with SessionLocal() as db:
        try:
            await system_alerts.post(db, subject="x", once="1", title="t", text="t", open="nowhere")
        except ValueError:
            return True
        return False
assert asyncio.run(bad())
async def task_alert():
    from app.models import ScheduledTask
    async with SessionLocal() as db:
        t = ScheduledTask(name="早报", prompt="新闻", cron="0 8 * * *"); db.add(t); await db.commit()
        a = await system_alerts.post(db, subject=f"task:{t.id}", once="k1", title="早报失败", text="x", open=f"task:{t.id}", prompt="看看")
        b = await system_alerts.post(db, subject=f"task:{t.id}", once="k1", title="早报失败", text="x", open=f"task:{t.id}")
        await db.commit()
        n = await system_alerts.clear(db, f"task:{t.id}"); await db.commit()
        return a.target, a.task_id == t.id, b, n
assert asyncio.run(task_alert()) == ("tasks", True, None, 1)
print("smoke_system_alerts ok")
