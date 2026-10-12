# 冒烟：消息里的 `$技能`（app/skill_mentions.py，移植自 Codex skills mentions/selection）。模拟模型，只看发给模型的消息：
# 规则（find：最长前缀、英文名字字符边界、中文紧跟可以、US$5 / $$ / 代码段 / 环境变量不认、去重、最多 3 个）→
# WS：“$writing 帮我润色”存成 skill 引用块、正文进模型（<skill> 片段）；停用的不认；!命令 不认；
# 编辑消息按新文字重认（删掉的 $ 不再带）；不带文字的重新生成保留；技能删掉 / 停用后历史里给说明不给正文。
# 运行：python tests/smoke_skill_mentions.py
import os, sys, asyncio, subprocess, tempfile, json
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, MODEL_ROUTER="off",
  AUTO_TITLE="false", NEXT_SPEAKER_CHECK="off", USER_SHELL="true",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from app import llm, skill_mentions as sm, skills_store
from app.agent import loop
from app.auth import issue_token, require_user
from app.blocks import blocks_to_text
from app.db import SessionLocal
from app.models import Message
from app.routes import conversations as rc, ws as rws

# —— 规则：find（纯函数）——
K = ["web-research", "web-research-pro", "writing", "写作", "PATH", "a"]
F = lambda t: sm.find(t, K)
assert F("$web-research 查一下") == ["web-research"]
assert F("$web-research-pro 查") == ["web-research-pro"]               # 最长的先认
assert F("$web-research帮我查") == ["web-research"]                     # 中文紧跟可以
assert F("$web-researcher") == [] and F("$writing_x") == []            # 后面紧跟英文名字字符不算
assert F("用$写作润色") == ["写作"] and F("$写作。") == ["写作"]
assert F("花了 US$5，$$writing") == [] and F("a$writing") == []          # $ 前是字母 / $ 不算
assert F("`$writing` 和\n```\necho $writing\n```\n") == []              # 代码里是 shell 变量
assert F("$PATH 和 $a") == ["a"]                                         # 环境变量名永不当技能
assert F("$writing $writing $写作") == ["writing", "写作"]                # 去重、按出现顺序
assert F("$a $writing $写作 $web-research") == ["a", "writing", "写作"]   # 最多 3 个
assert F("没有符号") == [] and sm.find("$x", []) == [] and F("$") == [] and F("$ writing") == []

# —— 技能库 ——
mine = skills_store.save_skill("周报格式", "写周报时用", "1. 先列完成\n2. 再列风险")
assert mine.id == "周报格式"
builtin = skills_store.list_skills()[0]
assert sm.ids(f"按 ${mine.id} 写，参考 ${builtin.id}") == [mine.id, builtin.id]
skills_store.set_enabled(builtin.id, False)
assert sm.ids(f"参考 ${builtin.id}") == []                                 # 停用的不认（和 use_skill 同一开关）
skills_store.set_enabled(builtin.id, True)

# —— WS ——
sent: list[list[dict]] = []
async def fake_stream_turn(messages, tools=None, model=None, effort=None):
    sent.append([dict(m) for m in messages])
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
            return first

def last_user(msgs):
    return [m for m in msgs if m["role"] == "user"][-1]["content"]

async def user_blocks(cid):
    async with SessionLocal() as db:
        rows = (await db.scalars(select(Message).where(Message.conversation_id == cid, Message.role == "user")
                                 .order_by(Message.created_at))).all()
        return [m.blocks for m in rows]

def skills(blocks):
    return [b["id"] for b in blocks if b["type"] == "skill"]

with c.websocket_connect(f"/ws?token={token}") as ws:
    # 1) 点名 → 引用块（id + 名字）+ 正文进模型；文字原样
    e = turn(ws, {"type": "user.message", "text": f"${mine.id}帮我写这周的"})
    cid = e["conversation_id"]
    b = asyncio.run(user_blocks(cid))[0]
    assert b[0]["text"] == f"${mine.id}帮我写这周的" and b[1] == {"type": "skill", "id": mine.id, "name": "周报格式"}, b
    text = last_user(sent[-1])
    assert "<skill>\n<name>周报格式</name>" in text and "1. 先列完成\n2. 再列风险" in text and "不用再 use_skill" in text, text
    assert blocks_to_text(b) == f"${mine.id}帮我写这周的\n\n[技能：周报格式]", blocks_to_text(b)

    # 2) 没这个技能只留文字
    turn(ws, {"type": "user.message", "conversation_id": cid, "text": "$nothing-here 随便"})
    assert skills(asyncio.run(user_blocks(cid))[-1]) == []

    # 3) !命令 里的 $ 是 shell 变量
    assert rws._skills(f"!echo ${mine.id}") == [] and rws._skills("") == []

    # 4) 编辑：按新文字重认；不带文字的重新生成保留
    turn(ws, {"type": "user.message", "conversation_id": cid, "text": "写个总结"})
    turn(ws, {"type": "message.regenerate", "conversation_id": cid, "text": f"写个总结，按 ${mine.id}"})
    assert skills(asyncio.run(user_blocks(cid))[-1]) == [mine.id]
    turn(ws, {"type": "message.regenerate", "conversation_id": cid})
    assert skills(asyncio.run(user_blocks(cid))[-1]) == [mine.id]
    assert "<name>周报格式</name>" in last_user(sent[-1])
    turn(ws, {"type": "message.regenerate", "conversation_id": cid, "text": "写个总结就行"})
    last = asyncio.run(user_blocks(cid))[-1]
    assert skills(last) == [] and last[0]["text"] == "写个总结就行"

    # 5) 技能删掉后：历史里第一条给说明、不给正文
    skills_store.delete_skill(mine.id)
    turn(ws, {"type": "user.message", "conversation_id": cid, "text": "再来"})
    hist = "\n".join(m["content"] for m in sent[-1] if m["role"] == "user" and isinstance(m["content"], str))
    assert "技能「周报格式」已被删除" in hist and "先列完成" not in hist, hist

# 6) render：停用 / 太长截断
mine = skills_store.save_skill("周报格式", "写周报时用", "步骤")
skills_store.set_enabled(mine.id, False)
assert "已被停用" in sm.render({"type": "skill", "id": mine.id, "name": "周报格式"})
s2 = skills_store.save_skill("长技能", "测", "x" * (sm.SKILL_BODY_CHARS + 50))
r = sm.render({"type": "skill", "id": s2.id, "name": s2.name})
assert r.count("x") <= sm.SKILL_BODY_CHARS + 5 and "太长已截断" in r
print("smoke_skill_mentions OK")
