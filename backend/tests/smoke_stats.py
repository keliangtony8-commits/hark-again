# 冒烟：stats 块（关键数字小卡片）。模拟模型：第一轮调用 show_stats（7 项，超出的截掉）→ 第二轮一句话收尾；
# 回复消息里依次是 stats 块和文字块；块通过 Block 联合校验；喂回模型的历史文字里带“标签：数值（变化）”；
# 空 items 被拒（min_length=1）；面板刷新提示里提到 show_stats。
# 运行：python tests/smoke_stats.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from pydantic import TypeAdapter, ValidationError
from app import llm, worker
from app.agent import runner
from app.agent.tools import load_builtin
from app.blocks import Block, StatsBlock, blocks_to_text, text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message
from sqlalchemy import select

items = [{"label": "今日最高", "value": "26°C", "note": "比昨天 ↑3°"}, {"label": "日落", "value": "17:42"}] + \
        [{"label": f"x{i}", "value": str(i)} for i in range(5)]
calls = {"n": 0}

def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)

async def fake_create(model, messages, stream=False, stream_options=None, **kw):
    calls["n"] += 1
    first = calls["n"] == 1
    async def gen():
        if first:
            yield chunk(tool=[NS(index=0, id="c1", function=NS(name="show_stats", arguments=json.dumps({"items": items}, ensure_ascii=False)))])
        else:
            yield chunk("今天适合出门。")
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()

async def main():
    async with SessionLocal() as db:
        conv = Conversation(); db.add(conv); await db.commit()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("今天天气")))
        await db.commit()
        assert await runner.run_turn(db, conv) is not None
        reply = (await db.scalars(select(Message).where(Message.conversation_id == conv.id, Message.role == "assistant"))).all()[-1]
    types = [b["type"] for b in reply.blocks]
    assert types == ["stats", "text"], reply.blocks
    st = reply.blocks[0]
    assert len(st["items"]) == 6 and st["items"][0] == {"label": "今日最高", "value": "26°C", "note": "比昨天 ↑3°"}, st
    assert st["items"][1]["note"] is None
    TypeAdapter(list[Block]).validate_python(reply.blocks)
    text = blocks_to_text(reply.blocks)
    assert "今日最高：26°C（比昨天 ↑3°）" in text and "日落：17:42" in text, text
    try:
        StatsBlock(items=[]); raise AssertionError("empty items accepted")
    except ValidationError:
        pass
    assert "show_stats" in worker.PANEL_STYLE
    print("ok smoke_stats")

asyncio.run(main())
