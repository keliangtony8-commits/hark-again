# 冒烟：v1.07 报告卡的“一眼”——定时任务的报告进收件箱时带 headline（摘要卡标题）+ gist（一句话），
# /api/inbox 的 latest 带上它们（横幅第二行），day_overview 的未读列表也用 gist；迁移 0025 回填老报告。
# 纯规则 + worker.run_task 端到端（模拟模型），无真模型调用。
# 运行：python tests/smoke_report_gist.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
def alembic(*a):
    subprocess.run([sys.executable, "-m", "alembic", *a], cwd=root, check=True, capture_output=True)

from app.report_gist import gist, GIST_MAX

# ---------- 纯规则 ----------
S = {"type": "summary", "title": "今天 · 10月12日 周一", "markdown": "## 时间线\n- **08:00** 背单词\n- 10:00 组会"}
T = {"type": "text", "text": "今天先背单词。"}
assert gist([S, T]) == ("今天 · 10月12日 周一", "今天先背单词。"), gist([S, T])
assert gist([S]) == ("今天 · 10月12日 周一", "08:00 背单词"), gist([S])                    # 没正文 → 摘要第一行内容
assert gist([{"type": "text", "text": "# 标题\n\n**3** 篇新论文，[链接](http://a)值得看"}]) == (None, "3 篇新论文，链接值得看")
assert gist([{"type": "table", "columns": ["a", "b"], "rows": [["1", "2"]]}])[0] is None    # 退路：纯文本，不报错
assert gist([]) == (None, None) and gist(None) == (None, None)
long = "第一句话很长" * 10 + "。" + "后面还有很多很多" * 20
h, g = gist([{"type": "text", "text": long}])
assert len(g) <= GIST_MAX + 1 and g.endswith("。"), g                                        # 句末断开
h, g = gist([{"type": "text", "text": "无标点" * 80}])
assert g.endswith("…") and len(g) == GIST_MAX + 1, g
assert gist([{"type": "text", "text": "| 项 | 值 |\n|---|---|\n| 气温 | 21° |"}])[1] == "项 · 值 气温 · 21°"

# ---------- 迁移回填：0024 时代的老报告 ----------
alembic("upgrade", "0024")
import sqlite3
con = sqlite3.connect(f"{tmp}/t.db")
con.execute("INSERT INTO home_cards (id, kind, title, blocks, dismissed, unread, created_at, updated_at) VALUES "
            "('old1','report','早间简报',?,0,1,'2026-10-11 00:00:00','2026-10-11 00:00:00')", (json.dumps([S, T]),))
con.execute("INSERT INTO home_cards (id, kind, title, blocks, dismissed, unread, created_at, updated_at) VALUES "
            "('act1','action','别动我',?,0,1,'2026-10-11 00:00:00','2026-10-11 00:00:00')", (json.dumps([T]),))
con.commit()
alembic("upgrade", "head")
assert con.execute("SELECT headline, gist FROM home_cards WHERE id='old1'").fetchone() == ("今天 · 10月12日 周一", "今天先背单词。")
assert con.execute("SELECT headline, gist FROM home_cards WHERE id='act1'").fetchone() == (None, None)  # 只回填报告
con.close()

# ---------- 端到端：worker 投递 ----------
from sqlalchemy import select
from app import llm, worker
from app.agent.tools import load_builtin
from app.db import SessionLocal
from app.models import HomeCard, ScheduledTask
from app.routes.inbox import summary
from app import day_brief

script: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
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

async def seed():
    async with SessionLocal() as db:
        t = ScheduledTask(name="论文追踪", prompt="看看新论文", cron="0 9 * * *")
        db.add(t); await db.commit()
        return t.id
tid = asyncio.run(seed())
script.extend([("show_summary", {"title": "本周 3 篇新论文", "markdown": "- 第一篇\n- 第二篇"}), "第二篇和你的课题最相关。"])
asyncio.run(worker.run_task(tid))

async def check():
    async with SessionLocal() as db:
        card = await db.scalar(select(HomeCard).where(HomeCard.task_id == tid, HomeCard.kind == "report"))
        inbox = await summary(db)
        brief = await day_brief.gather(db)
        return card, inbox, brief
card, inbox, brief = asyncio.run(check())
assert (card.headline, card.gist) == ("本周 3 篇新论文", "第二篇和你的课题最相关。"), (card.headline, card.gist)
assert inbox["latest"]["id"] == card.id and inbox["latest"]["gist"] == "第二篇和你的课题最相关。", inbox
assert inbox["latest"]["headline"] == "本周 3 篇新论文"
assert "「论文追踪」" in brief.text() and "：第二篇和你的课题最相关。" in brief.text(), brief.text()

# 跑失败（模型没出任何东西）：报告卡也有一句话
async def crash(*a, **k):
    raise RuntimeError("boom")
llm.client.chat.completions.create = crash
asyncio.run(worker.run_task(tid))
async def latest():
    async with SessionLocal() as db:
        return await db.scalar(select(HomeCard).where(HomeCard.task_id == tid, HomeCard.kind == "report",
                                                      HomeCard.dismissed.is_(False)))
c = asyncio.run(latest())
assert c.headline is None and c.gist == "这次没有跑成功，稍后会按计划再试。", (c.headline, c.gist)

# 接口：/api/cards 列表带上字段
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as cl:
    tok = cl.post("/api/auth/login", json={"username": "u", "password": "p"}).json()["token"]
    rows = cl.get("/api/cards", headers={"Authorization": f"Bearer {tok}"}).json()
    r = next(x for x in rows if x["id"] == c.id)
    assert "headline" in r and r["gist"] == c.gist, r
print("report gist ok")
