# 冒烟：v0.83 浏览器任务中的登录卡 / 验证码卡（表单卡）。模拟模型 + 假浏览器，无迁移。
# - 保险箱没有该网站登录 → browser_login 在聊天里弹登录卡（form, purpose=login）；用户填完 → 代填、卡片 submitted；
#   勾了“记住” → 存进保险箱，下一次直接代填、不再弹卡。
# - 密码只到浏览器：不进卡片、不进消息、不进给模型的工具结果；模型自己塞的 form 参数被丢掉。
# - 取消 / 无人值守（定时任务）→ cancelled，不登录；停止 → partial() 把 pending 表单卡标 expired。
# - browser_code 验证码卡：填完 → 填进输入框并回车。
# - approvals.wait_form 只收卡片上有的字段、丢非字符串、截断超长值；None = 取消。
# 运行：python tests/smoke_signin_form.py
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
from app import llm, browser_client, conversation_share, vault
from app.agent import runner, approvals
from app.agent.approvals import FormReply
from app.agent.loop import MessageBuilder
from app.agent.tools import REGISTRY, load_builtin
from app.blocks import Block, blocks_to_text, text_to_blocks
from app.config import settings
from app.db import SessionLocal
from app.models import Conversation, Message, Secret

PW = "s3cret-密码"
browser_calls: list = []
async def fake_snapshot(session, method, path, body=None):
    assert session == "example-com", session  # 按网站起的会话名
    browser_calls.append((path, body))
    return {"title": "登录 - 示例商城", "url": "https://shop.example.com/login",
            "elements": [{"ref": "1", "tag": "input", "type": "text", "name": "账号"},
                         {"ref": "2", "tag": "input", "type": "password", "name": "密码"}], "text": "欢迎"}
browser_client.snapshot_call = fake_snapshot

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
assert "browser_code" in REGISTRY and REGISTRY["browser_login"].form and "browser_code" in settings.system_prompt

asked: list[dict] = []
def answer(reply):
    async def ask(fid, form):
        asked.append(form)
        assert form["id"] == fid and form["state"] == "pending"
        return reply
    return ask

async def turn(cid, ask=None):
    async with SessionLocal() as db:
        conv = Conversation(id=cid, title="登录"); db.add(conv); await db.commit()
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks("帮我登录商城看订单")))
        await db.commit()
        kw = {"ask": ask} if ask else {}
        reply = await runner.run_turn(db, conv, **kw)
        return reply.blocks, (await conversation_share.load(db, cid)).messages

OPEN = ("browser_open", {"url": "https://shop.example.com/login"})
LOGIN = ("browser_login", {"user_ref": "1", "pass_ref": "2", "form": {"values": {"username": "evil", "password": "x"}}})
ta = TypeAdapter(Block)

# 1) 保险箱里没有 → 弹登录卡 → 用户填写并勾“记住” → 代填 + 存保险箱
script.extend([OPEN, LOGIN, "登录好了。"])
blocks, msgs = asyncio.run(turn("c1", answer(FormReply({"username": "me@x.com", "password": PW}, remember=True))))
for b in blocks:
    ta.validate_python(b)
assert [b["type"] for b in blocks] == ["browser", "form", "text"], blocks
form = blocks[1]
assert form["purpose"] == "login" and form["site"] == "shop.example.com" and form["state"] == "submitted" and form["remember"], form
assert [f["name"] for f in form["fields"]] == ["username", "password"] and form["fields"][1]["kind"] == "password"
login = [b for p, b in browser_calls if p == "/login"]
assert login == [{"user_ref": "1", "pass_ref": "2", "username": "me@x.com", "password": PW}], login
assert PW not in json.dumps(blocks, ensure_ascii=False) and PW not in json.dumps([m.blocks for m in msgs], ensure_ascii=False)
assert all(PW not in s for s in model_saw), "密码不能给模型看"
assert "登录卡" in model_saw[-1] and "保险箱" in model_saw[-1]
async def secrets():
    async with SessionLocal() as db:
        return (await db.scalars(select(Secret))).all()
saved = asyncio.run(secrets())
assert len(saved) == 1 and saved[0].kind == "login" and saved[0].username == "me@x.com" and saved[0].hosts == ["shop.example.com"]
assert vault.reveal(saved[0]) == PW and saved[0].preview == ""
assert "[表单：登录以继续（shop.example.com）——用户已填写]" in blocks_to_text(blocks)
assert "登录以继续" not in conversation_share.render(NS(title="t"), msgs)  # 分享网页不放表单卡

# 2) 记住了 → 第二次直接代填，不弹卡；模型塞的 form 参数被丢掉
browser_calls.clear(); asked.clear()
script.extend([OPEN, LOGIN, "又登录好了。"])
blocks, _ = asyncio.run(turn("c2", answer(None)))
assert not asked and [b["type"] for b in blocks] == ["browser", "text"], blocks
assert [b for p, b in browser_calls if p == "/login"][0]["password"] == PW and "保险箱「shop.example.com」" in model_saw[-1]

# 3) 用户取消 → cancelled，不登录
async def wipe():
    async with SessionLocal() as db:
        for s in (await db.scalars(select(Secret))).all():
            await db.delete(s)
        await db.commit()
asyncio.run(wipe())
browser_calls.clear()
script.extend([OPEN, LOGIN, "好的。"])
blocks, _ = asyncio.run(turn("c3", answer(None)))
assert blocks[1]["type"] == "form" and blocks[1]["state"] == "cancelled" and not [p for p, _ in browser_calls if p == "/login"]
assert "用户没有填写" in model_saw[-1]

# 4) 无人值守：没人填 → cancelled
script.extend([OPEN, LOGIN, "需要你登录。"])
blocks, _ = asyncio.run(turn("c4"))
assert blocks[1]["state"] == "cancelled"

# 5) 不勾记住 → 登录但不存；填不全 → 不登录
browser_calls.clear()
script.extend([OPEN, LOGIN, ("browser_login", {"user_ref": "1", "pass_ref": "2"}), "ok"])
replies = iter([FormReply({"username": "a", "password": "b"}), FormReply({"username": "a"})])
async def seq(fid, form):
    return next(replies)
asyncio.run(turn("c5", seq))
assert len([p for p, _ in browser_calls if p == "/login"]) == 1 and not asyncio.run(secrets())
assert "没有把账号和密码填完整" in model_saw[-1]

# 6) 验证码卡
browser_calls.clear(); asked.clear()
script.extend([OPEN, ("browser_code", {"ref": "3", "label": "短信验证码（尾号 1234）"}), "进去了。"])
blocks, _ = asyncio.run(turn("c6", answer(FormReply({"code": " 482913 "}))))
code = blocks[1]
assert code["purpose"] == "code" and code["title"] == "短信验证码（尾号 1234）" and code["fields"][0]["kind"] == "code" and code["action"] == "填入"
assert browser_calls[-1] == ("/act", {"action": "type", "ref": "3", "text": "482913", "submit": True}), browser_calls
assert all("482913" not in s for s in model_saw)

# 7) 停止 → pending 表单卡过期
mb = MessageBuilder(); mb.add({**code, "state": "pending"})
assert mb.partial()[0]["state"] == "expired"

# 8) approvals：只收卡上字段、丢非字符串、截断；None = 取消；不存在的 id 不报错
async def hub():
    t = asyncio.create_task(approvals.wait_form("f1", ["code"]))
    await asyncio.sleep(0)
    assert approvals.resolve_form("f1", {"code": "1" * 900, "extra": "x", "n": 5}, remember=1)
    r = await t
    assert r.values == {"code": "1" * approvals.VALUE_MAX} and r.remember is True
    t = asyncio.create_task(approvals.wait_form("f2", ["code"]))
    await asyncio.sleep(0)
    approvals.resolve_form("f2", None)
    assert await t is None
    assert not approvals.resolve_form("nope", {"a": "b"})
asyncio.run(hub())
print("smoke_signin_form OK")
