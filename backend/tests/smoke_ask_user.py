# 冒烟：v0.87 ask_user——任务中缺信息时弹 info 表单卡问用户。模拟模型，无迁移（表单卡是 JSON 块）。
# - 弹卡：字段名由服务器编（q1..），去空 label、password/code 降成 text、候选 ≤6、按钮 ≤8 字；模型塞的 form 参数被丢掉。
# - 提交：模型拿到答案（含“没填”），卡片 answers 回显并落库、进历史（下一轮记得）；勾“记住” → 存进长期记忆 + 记忆卡。
# - 取消 → cancelled；无人值守 → 不弹卡；参数不对 → 不弹卡；停止 → expired。
# 运行：python tests/smoke_ask_user.py
import os, sys, asyncio, subprocess, tempfile, json, base64
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY=base64.urlsafe_b64encode(os.urandom(32)).decode(),
  DATA_DIR=tmp, PUBLIC_URL="https://me.example", TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from pydantic import TypeAdapter
from sqlalchemy import select
from app import llm, conversation_share
from app.agent import runner, approvals
from app.agent.approvals import FormReply
from app.agent.loop import MessageBuilder
from app.agent.tools import REGISTRY, load_builtin
from app.blocks import Block, blocks_to_text, text_to_blocks
from app.config import settings
from app.db import SessionLocal
from app.models import Conversation, Message, Memory

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
assert REGISTRY["ask_user"].form and "ask_user" in settings.system_prompt

asked: list[dict] = []
def answer(reply):
    async def ask(fid, form):
        asked.append(form)
        assert form["id"] == fid and form["state"] == "pending"
        return reply
    return ask

async def turn(cid, ask=None, text="帮我订明晚的位子"):
    async with SessionLocal() as db:
        conv = Conversation(id=cid, title="订位"); db.add(conv); await db.commit()
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks(text)))
        await db.commit()
        kw = {"ask": ask} if ask else {}
        reply = await runner.run_turn(db, conv, **kw)
        return reply.blocks, (await conversation_share.load(db, cid)).messages

ASK = ("ask_user", {"question": "订几位、送到哪？", "note": "订座要人数和联系电话",
       "fields": [{"label": "人数", "options": ["2 位", "4 位", "2 位", " ", "6 位", "8 位", "10 位", "12 位", "x"]},
                  {"label": "电话", "kind": "phone"},
                  {"label": "备注", "kind": "multiline", "optional": True},
                  {"label": "", "kind": "text"},
                  {"label": "密码", "kind": "password"}],
       "remember": True, "action": "就这样订吧这个按钮太长",
       "form": {"values": {"q1": "evil"}}})
ta = TypeAdapter(Block)

# 1) 弹 info 卡 → 用户填写并勾“记住” → 模型拿到答案、卡片回显 answers、存进记忆
script.extend([ASK, "好的，4 位，已记下电话。"])
blocks, msgs = asyncio.run(turn("a1", answer(FormReply({"q1": " 4 位 ", "q2": "13800001111", "q3": "", "q4": "x"}, remember=True))))
for b in blocks:
    ta.validate_python(b)
assert [b["type"] for b in blocks] == ["form", "memory", "text"], blocks
card = blocks[0]
assert card["purpose"] == "info" and card["state"] == "submitted" and card["remember"] and card["note"] == "订座要人数和联系电话"
assert card["action"] == "就这样订吧这个按" and len(card["action"]) == 8
f = card["fields"]
assert [x["name"] for x in f] == ["q1", "q2", "q3", "q4"] and [x["label"] for x in f] == ["人数", "电话", "备注", "密码"], f
assert f[0]["options"] == ["2 位", "4 位", "2 位", "6 位", "8 位", "10 位"] and f[1]["kind"] == "phone"
assert f[2]["kind"] == "multiline" and f[2]["optional"] and f[3]["kind"] == "text", "不收 password，降成 text"
assert card["answers"] == [{"label": "人数", "value": "4 位"}, {"label": "电话", "value": "13800001111"}, {"label": "密码", "value": "x"}]
assert "evil" not in json.dumps(blocks, ensure_ascii=False), "模型塞的 form 参数被丢掉"
assert "人数：4 位" in model_saw[-1] and "电话：13800001111" in model_saw[-1] and "没填：备注" in model_saw[-1]
mem = blocks[1]
assert mem["action"] == "saved" and [i["content"] for i in mem["items"]] == ["人数：4 位", "电话：13800001111", "密码：x"]
async def memories():
    async with SessionLocal() as db:
        return sorted(m.content for m in (await db.scalars(select(Memory))).all())
assert asyncio.run(memories()) == ["人数：4 位", "密码：x", "电话：13800001111"]
assert msgs[-1].blocks[0]["answers"] == card["answers"], "answers 落库"
assert "[表单：订几位、送到哪？——用户已填写]\n人数：4 位\n电话：13800001111" in blocks_to_text(blocks)

# 2) 下一轮：历史里带着答案（模型记得）
script.extend(["你订的是 4 位。"])
async def follow():
    async with SessionLocal() as db:
        conv = await db.get(Conversation, "a1")
        db.add(Message(conversation_id="a1", role="user", blocks=text_to_blocks("我刚才说几位？")))
        await db.commit()
        return await runner.run_turn(db, conv)
asyncio.run(follow())
assert "人数：4 位" in model_saw[-1]

# 3) 不勾记住 → 不存记忆，也没有记忆卡
script.extend([ASK, "好。"])
blocks, _ = asyncio.run(turn("a2", answer(FormReply({"q1": "2 位", "q2": "1"}, remember=False))))
assert [b["type"] for b in blocks] == ["form", "text"] and len(asyncio.run(memories())) == 3

# 4) 取消 → cancelled、没有 answers，模型被告知
script.extend([ASK, "好的，那先不订。"])
blocks, _ = asyncio.run(turn("a3", answer(None)))
assert blocks[0]["state"] == "cancelled" and "answers" not in blocks[0] and "用户没有填写" in model_saw[-1]

# 5) 无人值守：不弹卡，告诉模型没人能答
asked.clear()
script.extend([ASK, "缺人数，先不订。"])
blocks, _ = asyncio.run(turn("a4"))
assert [b["type"] for b in blocks] == ["text"] and "后台运行" in model_saw[-1]

# 6) 参数不对：不弹卡，报参数错误
script.extend([("ask_user", {"question": "问啥", "fields": [{"label": " "}]}), "ok"])
blocks, _ = asyncio.run(turn("a5", answer(FormReply({}))))
assert not asked and [b["type"] for b in blocks] == ["text"] and "参数有误" in model_saw[-1]

# 7) 停止 → pending info 卡过期
mb = MessageBuilder(); mb.add({**card, "state": "pending"})
assert mb.partial()[0]["state"] == "expired"

# 8) login 卡永远不带 answers（form_answers 只用于 info）
from app.agent.loop import form_answers
assert form_answers({"fields": [{"name": "a", "label": "A"}, {"name": "b", "label": "B"}]}, {"a": " 1 ", "b": " "}) == [{"label": "A", "value": "1"}]
print("smoke_ask_user OK")
