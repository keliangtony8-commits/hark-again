# 冒烟：消息里的 `@子助手`（app/agent_mentions.py，移植自 Gemini CLI atCommandProcessor 的 agentParts + agentNudge）。
# 规则（三个名字、大小写、中文紧跟、邮箱 / a@agent / @agent.md / @agents / 代码里不认、blank 等长）→ 文件 @ 让位（代理优先）→
# WS：存 agent 引用块、当前这一问带 <system_note> 提示、模型照提示调 delegate 真的派出子助手、下一轮只剩一句记录；
# 编辑按新文字重认；!命令 不认；回答途中补充带 @子助手 不插队；SUBAGENT_MAX_TASKS=0 时不认。
# 运行：python tests/smoke_agent_mentions.py
import os, sys, asyncio, subprocess, tempfile, json
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, MODEL_ROUTER="off",
  AUTO_TITLE="false", NEXT_SPEAKER_CHECK="off", USER_SHELL="true",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from app import agent_mentions as am, file_mentions, llm, steering
from app.agent import loop, subagent, tools
tools.load_builtin()
from app.auth import issue_token, require_user
from app.blocks import blocks_to_text
from app.config import settings
from app.db import SessionLocal
from app.models import Message
from app.routes import conversations as rc, ws as rws

# —— 规则 ——
F = am.found
assert F("@子助手 查一下") and F("请@子助手帮我查") and F("@agent go") and F("@Agent") and F("@SUBAGENT 查")
assert F("@agent。") and F("@agent.") and F("(@agent)") and F("@子助手们")
assert not F("me@agent.com") and not F("a@agent") and not F("@agent.md") and not F("@agents") and not F("@agent/x")
assert not F("@agent_x") and not F("@agent-x") and not F("`@agent`") and not F("```\n@agent\n```") and not F("") and not F(None)
s = "看 @子助手 和 @a.md"
assert am.blank(s) == "看 " + " " * 4 + " 和 @a.md" and len(am.blank(s)) == len(s) and am.blank("无") == "无"
assert am.blocks("@agent 查") == [am.BLOCK] and am.blocks("查") == []
assert am.blocks("@agent 查", [{"type": "agent"}]) == []                           # 已有不重复
assert am.render(True) == am.NUDGE and "delegate" in am.NUDGE and am.render(False) == am.RECORD

# —— 文件 @ 让位：@agent 是子助手，@agent.md 才是文件 ——
assert file_mentions.parse("@agent 和 @agent.md 和 @子助手") == ["agent.md"]

# —— WS ——
sent: list[tuple[str, list[dict]]] = []
async def fake_stream_turn(messages, tools=None, model=None, effort=None):
    msgs = [dict(m) for m in messages]
    system = msgs[0]["content"] if msgs and msgs[0]["role"] == "system" else ""
    if subagent.ROLE in system:                                                   # 子助手：直接交结论
        sent.append(("child", msgs))
        yield "子结论：查到 3 条"
        yield llm.Turn(text="子结论：查到 3 条")
        return
    sent.append(("main", msgs))
    last = msgs[-1]
    if last["role"] == "user" and isinstance(last["content"], str) and "<system_note>" in last["content"]:
        args = json.dumps({"tasks": [{"title": "查资料", "prompt": "查一下三家的价格，交回表格"}]})
        yield llm.Turn(tool_calls=[llm.ToolCall("c1", "delegate", args)])
        return
    yield "好"
    yield llm.Turn(text="好")
loop.stream_turn = fake_stream_turn
async def fake_complete(messages, model=None, kind="summary", **kw):
    return "摘要"
llm.complete = fake_complete

app = FastAPI()
for r in (rws.router, rc.router):
    app.include_router(r)
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

async def rows(cid, role="user"):
    async with SessionLocal() as db:
        return [m.blocks for m in (await db.scalars(select(Message).where(Message.conversation_id == cid, Message.role == role)
                                                     .order_by(Message.created_at))).all()]

def agents(blocks):
    return [b for b in blocks if b["type"] == "agent"]

def main_users(i=-1):
    msgs = [m for k, m in sent if k == "main"][i]
    return [m["content"] for m in msgs if m["role"] == "user" and isinstance(m["content"], str)]

with c.websocket_connect(f"/ws?token={token}") as ws:
    # 1) 点名 → 引用块 + 提示 → 模型调 delegate → 子助手真的跑了 → 回复里有子任务卡
    first, done = turn(ws, {"type": "user.message", "text": "@子助手 查三家的价格"})
    cid = first["conversation_id"]
    b = asyncio.run(rows(cid))[0]
    assert b[0]["text"] == "@子助手 查三家的价格" and agents(b) == [am.BLOCK], b
    assert blocks_to_text(b) == "@子助手 查三家的价格\n\n[交给子助手]"
    assert main_users(0)[-1].endswith(am.NUDGE), main_users(0)[-1]
    assert any(k == "child" for k, _ in sent), "子助手没跑"
    dl = [x for x in done["message"]["blocks"] if x["type"] == "delegate"]
    assert dl and dl[0]["tasks"][0]["state"] == "done" and "子结论" in dl[0]["tasks"][0]["result"], done["message"]["blocks"]

    # 2) 下一轮：上一问只剩一句记录，不再提示
    turn(ws, {"type": "user.message", "conversation_id": cid, "text": "继续"})
    hist = main_users()
    assert any(am.RECORD in h for h in hist) and not any("<system_note>" in h for h in hist), hist

    # 3) 编辑：按新文字重认 / 去掉
    turn(ws, {"type": "message.regenerate", "conversation_id": cid, "text": "这次 @agent 去查"})
    assert agents(asyncio.run(rows(cid))[-1]) == [am.BLOCK]
    turn(ws, {"type": "message.regenerate", "conversation_id": cid, "text": "我自己来"})
    assert agents(asyncio.run(rows(cid))[-1]) == []

    # 4) !命令 不认
    assert rws._agents("!echo @agent") == [] and rws._agents("") == []

    # 5) 关掉子助手：不认，只留文字
    settings.subagent_max_tasks = 0
    turn(ws, {"type": "user.message", "conversation_id": cid, "text": "@子助手 再查"})
    assert agents(asyncio.run(rows(cid))[-1]) == [] and "<system_note>" not in main_users()[-1]
    settings.subagent_max_tasks = 3

# 6) 回答途中补充：带 @子助手 不插进去（照常排队成新一轮）
inbox = steering.open_inbox(cid)
inbox.start()
assert asyncio.run(rws._intake({"conversation_id": cid, "text": "@子助手 顺便查一下"})) is False
assert asyncio.run(rws._intake({"conversation_id": cid, "text": "顺便查一下"})) is True
steering.close(inbox)
print("smoke_agent_mentions OK")
