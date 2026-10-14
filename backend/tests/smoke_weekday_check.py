# 冒烟：v2.70 E2E B37 回复里“日期 + 星期几”对不上日历 → 就地改正（app/agent/weekday_check.py）。无迁移。
# 1) 规则：各种写法（中文 / ISO / 11/3 / 星期在前 / 英文）错的改、对的不动；星期范围、复述用户原话、引号里、
#    在指出写错、不存在的日期 → 不改；没写年份取离今天最近的那年，回复里只有一个年份就用它。
# 2) 一轮模拟模型（真机 r8 原样）：回“11月3日（周一）”→ 落库的回复是“周二”，只调一次模型（零额外调用），
#    客户端收到撤回（block.update）再收到改好的文字；对的回复原样、不撤回。
# 运行：python tests/smoke_weekday_check.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', NEXT_SPEAKER_CHECK="off")
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

# 1) 规则
from datetime import date
from app.agent.weekday_check import fix
T = date(2026, 10, 14)  # 周三
CASES = [
    ("通知改好了：11月3日（周一）上午9点开会。", "", "11月3日（周二）上午"),   # 真机 r8
    ("2026年11月3日 星期一", "", "2026年11月3日 星期二"),
    ("2026-11-03（周一）", "", "2026-11-03（周二）"),
    ("周一（11月3日）报名截止", "", "周二（11月3日）"),
    ("11/3（礼拜一）交", "", "11/3（礼拜二）"),
    ("11月3号周一、11月5号周三", "", "11月3号周二、11月5号周四"),
    ("1月5日（周一）", "", "1月5日（周二）"),                 # 10 月说 1 月 → 明年 2027-01-05 周二
    ("2025年的11月3日（周一）", "", None),                    # 回复里唯一年份 2025：那天确实周一
    ("2025年11月3日（周一）", "", None),
    ("11月3日（周二）没问题", "", None),
    ("11月3日（周一至周三）", "", None),                      # 星期范围
    ("11月3日起（周一、三）", "", None),
    ("通知上写的「11月3日（周一）」，日期没问题。", "", None),  # 引号里
    ("11月3日（周一）这个星期写错了，应为周二。", "", None),    # 在指出写错
    ("对，11月3日周一开会", "通知：11月3日周一 开会", None),     # 复述用户原话
    ("2月30日（周一）", "", None),                            # 不存在的日期
    ("今天10月14日，周三", "", None),
    ("Meeting on Monday, November 3.", "", "Tuesday, November 3"),
    ("Nov 3 (Mon)", "", "Nov 3 (Tue)"),
    ("Nov 3 (Tue)", "", None),
    ("| 2026年11月5日 | 星期三 |\n| 2026年11月12日 | 星期四 |", "", "| 2026年11月5日 | 星期四 |\n| 2026年11月12日 | 星期四 |"),  # 表格
    ("明天周四见", "", None),                                 # 没有绝对日期
]
bad = []
for r, q, want in CASES:
    out, ch = fix(r, q, T)
    if (want is None and (ch or out != r)) or (want is not None and (not ch or want not in out)):
        bad.append((r, out, ch))
assert not bad, bad
out, ch = fix("11月3日（周一）", "", T)
assert ch == [("一", "二")], ch
assert fix("", "", T) == ("", [])
print("rules ok")

# 2) 一轮模拟模型
from app import llm
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message
load_builtin()

seen, script = [], []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
ids = iter(range(10_000))
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append([dict(m) for m in messages])
    step = script.pop(0)
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"c{next(ids)}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create

async def seed(ask):
    async with SessionLocal() as db:
        conv = Conversation(title="t"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks(ask)))
        await db.commit(); return conv.id
async def turn(cid):
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))
def text_of(reply):
    return "".join(b.get("text", "") for b in reply.blocks if b.get("type") == "text")

R8 = "已修复。期中考试在 11月3日（周一）上午 9:00，地点 A201。"
cid = asyncio.run(seed("考试是哪天？"))
script.extend([R8])
n0, events = len(seen), []
async def turn_ev(cid):
    async with SessionLocal() as db:
        async def emit(ev):
            events.append(ev)
        return await run_turn(db, await db.get(Conversation, cid), emit=emit)
from unittest import mock
from app.agent import weekday_check
real_fix = weekday_check.fix
with mock.patch.object(weekday_check, "fix", lambda r, q, today=None: real_fix(r, q, T)):
    reply = asyncio.run(turn_ev(cid))
assert len(seen) - n0 == 1, len(seen) - n0
body = text_of(reply)
assert "11月3日（周二）" in body and "周一" not in body, reply.blocks
names = [e.get("type") for e in events]
assert names.index("block.update") < len(names) - 2 and names[-2] == "block.delta", names
async def stored(cid):
    async with SessionLocal() as db:
        from sqlalchemy import select
        rows = (await db.execute(select(Message).where(Message.conversation_id == cid, Message.role == "assistant"))).scalars().all()
        return "".join(b.get("text", "") for b in rows[-1].blocks if b.get("type") == "text")
assert "11月3日（周二）" in asyncio.run(stored(cid))
print("r8 weekday fixed in place ok")

cid = asyncio.run(seed("考试是哪天？"))
script.extend(["期中考试在 11月3日（周二）上午 9:00。"])
events.clear(); n0 = len(seen)
with mock.patch.object(weekday_check, "fix", lambda r, q, today=None: real_fix(r, q, T)):
    reply = asyncio.run(turn_ev(cid))
assert len(seen) - n0 == 1 and "block.update" not in [e.get("type") for e in events]
assert "11月3日（周二）" in text_of(reply)
assert not script
print("smoke_weekday_check OK")
