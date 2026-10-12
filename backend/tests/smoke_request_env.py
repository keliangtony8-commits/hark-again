# 冒烟：v1.88 request_env——聊天里要命令环境变量的卡（对标 Hark request_secret；值从不经过模型）。模拟模型，无迁移：
# 1) 弹 env 卡：标题 / 一个 password 字段 + min_length / 按钮“存进保险箱” / note=理由；模型塞的 form 参数被丢掉；
# 2) 用户填 → 存进保险箱（kind env）、打码缓存刷新；模型只拿到“已存”，值不在任何模型输入、卡片、落库消息、时间线里；
# 3) 已有同名 → 标题“换个值”、覆盖旧值；值太短 / 有换行 → 没存成（理由不带值）；名字不合格 / 系统变量 → 不弹卡、参数有误；
# 4) 取消 → cancelled，保险箱没变；无人值守 → 不弹卡，告诉模型去保险箱页；
# 5) 表单通道：超长值整个丢掉（不截断）；历史文本只有标题和状态；保险箱接口仍走 command_env.save（覆盖 / 上限）。
# 运行：python tests/smoke_request_env.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
from cryptography.fernet import Fernet
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY=Fernet.generate_key().decode(), DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', MODEL_ROUTER="off",
  AUTO_TITLE="false", NEXT_SPEAKER_CHECK="off")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from sqlalchemy import select
from app import command_env as E, llm, conversation_share
from app.agent import runner, approvals
from app.agent.approvals import FormReply
from app.agent.builtin.env import request_card
from app.agent.tools import REGISTRY, load_builtin
from app.auth import require_user
from app.blocks import Block, blocks_to_text, text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message, Secret
from app.routes import vault as rv

TOKEN = "tg-123456:ABCdefGHIjklMNOpqr"
NEW = "tg-999999:ZZZnewTOKENvalue77"

script: list = []
model_saw: list[str] = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    model_saw.append(json.dumps(messages, ensure_ascii=False))
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
assert REGISTRY["request_env"].form

asked: list[dict] = []
def answer(reply):
    async def ask(fid, form):
        asked.append(form)
        assert form["id"] == fid and form["state"] == "pending"
        return reply
    return ask

n = 0
async def turn(ask=None, text="帮我做个 Telegram 机器人"):
    global n
    n += 1
    cid = f"c{n}"
    async with SessionLocal() as db:
        conv = Conversation(id=cid, title="机器人"); db.add(conv); await db.commit()
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks(text)))
        await db.commit()
        reply = await runner.run_turn(db, conv, **({"ask": ask} if ask else {}))
        return reply, (await conversation_share.load(db, cid)).messages

async def secrets():
    async with SessionLocal() as db:
        return [(s.name, s.kind) for s in (await db.scalars(select(Secret))).all()]

ta = TypeAdapter(Block)
ASK = ("request_env", {"name": "telegram_bot_token", "reason": "在 @BotFather 创建机器人后给的 Token",
                       "form": {"values": {"value": "evil-model-value"}}})

# 0) 卡片规则
c0 = request_card("X_TOKEN", " 理由 " + "很" * 200, False)
ta.validate_python({**c0, "id": "f", "state": "pending"})
assert c0["purpose"] == "env" and c0["title"] == "需要X_TOKEN" and c0["action"] == "存进保险箱"
assert c0["fields"] == [{"name": "value", "label": "X_TOKEN 的值", "kind": "password", "min_length": E.VALUE_MIN}]
assert len(c0["note"]) == 120 and request_card("X_TOKEN", "", True)["title"] == "换个值：X_TOKEN" and "note" not in request_card("X_TOKEN", " ", True)
assert "request_env" in E.prompt(["A_B"]) and "聊天里" in E.prompt(["A_B"])

# 1) 用户填 → 存进保险箱，模型只拿到“已存”
script.extend([ASK, "存好了，接着写机器人。"])
reply, msgs = asyncio.run(turn(answer(FormReply({"value": TOKEN}))))
blocks = reply.blocks
for b in blocks:
    ta.validate_python(b)
card = blocks[0]
assert card["type"] == "form" and card["purpose"] == "env" and card["state"] == "submitted" and card["title"] == "需要TELEGRAM_BOT_TOKEN", card
assert card["note"] == "在 @BotFather 创建机器人后给的 Token" and "answers" not in card
assert asyncio.run(secrets()) == [("TELEGRAM_BOT_TOKEN", "env")] and E._values == {"TELEGRAM_BOT_TOKEN": TOKEN}
assert "$TELEGRAM_BOT_TOKEN 存进保险箱" in model_saw[-1]
everything = json.dumps([model_saw, blocks, [m.blocks for m in msgs], reply.steps], ensure_ascii=False, default=str)
assert TOKEN not in everything, "用户填的值不进模型、卡片、落库、时间线"
assert "evil-model-value" not in json.dumps([blocks, reply.steps], ensure_ascii=False), "模型塞的 form 参数被丢掉（只在它自己的调用记录里）"
assert reply.steps[0]["detail"].upper() == "TELEGRAM_BOT_TOKEN" and reply.steps[0]["state"] == "done", reply.steps
assert blocks_to_text(blocks).startswith("[表单：需要TELEGRAM_BOT_TOKEN——用户已填写]")

# 2) 下一轮：系统提示里有这个名字（只有名字）
script.extend(["好。"])
asyncio.run(turn(text="现在有哪些变量？"))
assert "$TELEGRAM_BOT_TOKEN" in model_saw[-1] and TOKEN not in model_saw[-1]

# 3) 已有同名 → “换个值”、覆盖
script.extend([ASK, "换好了。"])
reply, _ = asyncio.run(turn(answer(FormReply({"value": NEW}))))
assert asked[-1]["title"] == "换个值：TELEGRAM_BOT_TOKEN" and "换成新值" in model_saw[-1]
assert asyncio.run(secrets()) == [("TELEGRAM_BOT_TOKEN", "env")] and E._values == {"TELEGRAM_BOT_TOKEN": NEW}

# 4) 值太短 / 有换行 → 没存成，理由不带值，保险箱不变
for bad in ["abc12", "abcdef\nghijk"]:
    script.extend([ASK, "没存成。"])
    reply, _ = asyncio.run(turn(answer(FormReply({"value": bad}))))
    assert "没存成" in model_saw[-1] and bad not in model_saw[-1] and reply.steps[0]["state"] == "error"
    assert E._values == {"TELEGRAM_BOT_TOKEN": NEW}

# 5) 名字不合格 / 系统变量 → 不弹卡、参数有误
for bad in ["PATH", "1abc"]:
    asked.clear()
    script.extend([("request_env", {"name": bad, "reason": "x"}), "ok"])
    asyncio.run(turn(answer(FormReply({"value": TOKEN}))))
    assert not asked and "参数有误" in model_saw[-1], bad

# 6) 取消 → cancelled、保险箱没变
script.extend([("request_env", {"name": "OPENAI_API_KEY", "reason": "调 OpenAI"}), "那先不做。"])
reply, _ = asyncio.run(turn(answer(None)))
assert reply.blocks[0]["state"] == "cancelled" and "用户没有填写" in model_saw[-1] and reply.steps[0]["state"] == "denied"
assert asyncio.run(secrets()) == [("TELEGRAM_BOT_TOKEN", "env")]

# 7) 无人值守 → 不弹卡，指去保险箱页
script.extend([("request_env", {"name": "OPENAI_API_KEY", "reason": "调 OpenAI"}), "缺变量。"])
reply, _ = asyncio.run(turn())
assert [b["type"] for b in reply.blocks] == ["text"] and "保险箱 → 环境变量" in model_saw[-1] and "OPENAI_API_KEY" in model_saw[-1]

# 8) 表单通道：超长值整个丢掉（不截断成错值），正常长度的长 Token 原样
async def chan():
    t1 = asyncio.create_task(approvals.wait_form("f1", ["value"]))
    await asyncio.sleep(0)
    approvals.resolve_form("f1", {"value": "x" * (approvals.VALUE_MAX + 1)})
    t2 = asyncio.create_task(approvals.wait_form("f2", ["value"]))
    await asyncio.sleep(0)
    approvals.resolve_form("f2", {"value": "y" * 4000})
    return await t1, await t2
r1, r2 = asyncio.run(chan())
assert r1.values.get("value", "") == "" and r2.values["value"] == "y" * 4000
assert approvals.VALUE_MAX == E.VALUE_MAX

# 9) 保险箱接口走同一个 save：覆盖、坏名字 400
app = FastAPI(); app.include_router(rv.router)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
rr = c.post("/api/vault", json={"kind": "env", "name": "telegram_bot_token", "value": TOKEN})
assert rr.status_code == 200 and rr.json()["name"] == "TELEGRAM_BOT_TOKEN" and E._values == {"TELEGRAM_BOT_TOKEN": TOKEN}
assert c.post("/api/vault", json={"kind": "env", "name": "PATH", "value": "abcdefgh"}).status_code == 400
assert len(c.get("/api/vault").json()) == 1
print("smoke_request_env OK")
