# 冒烟：v2.95 项目 = 一段对话（app/project_chat.py + 迁移 0066）。无模型调用。
# 一、迁移：0065 下造多对话项目（含运行对话、报告卡 / 运行记录 / 反馈引用）→ upgrade head 合并成一段（保留最早那段的 id，
#     消息按时间交织、引用改指、标题 = 项目名、摘要清空、模型取最近那段），运行对话不动；再调一次 merge 无变化（幂等）；
#     downgrade 0065 → 对话、消息、引用、元数据全部还原；再 upgrade → 同样的结果。
# 二、约束：同一项目第二段普通对话插不进去；运行对话（task_id 非空）不受约束。
# 三、接口：建项目即建对话；GET /api/projects 带 conversation_id / status（conversation_count 已删）；
#     GET /api/conversations?project_id= = 那段对话（≤1 项、幂等、没有就建、未知项目 404）；项目对话删不了（409）；
#     项目改名 → 对话标题跟着改；主聊天列表不含项目对话。
# 四、运行对话：项目里的不 promote、用户回过话的清理时不删；主聊天的照旧 promote。
# 运行：python tests/smoke_project_chat.py
import os, sys, asyncio, importlib.util, json, sqlite3, subprocess, tempfile
tmp = tempfile.mkdtemp()
db_path = os.path.join(tmp, "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)


def alembic(*args):
    r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]


# ---------------------------------------------------------------- 一、迁移
alembic("upgrade", "0065")
sq = sqlite3.connect(db_path)
T = lambda h, m=0: f"2026-10-0{h} 10:{m:02d}:00.000000"
sq.executemany("INSERT INTO projects (id, name, emoji, rules, brief, created_at, updated_at) VALUES (?,?,?,?,?,?,?)", [
    ("p1", "考研", "📚", "", "", T(1), T(1)), ("p2", "旅行", "✈️", "", "", T(1), T(1)), ("p3", "空项目", "📁", "", "", T(1), T(1))])
def conv(cid, pid, title, created, updated, **kw):
    cols = dict(id=cid, project_id=pid, title=title, title_source=kw.get("src", "auto"), title_at=kw.get("title_at", 10),
                pinned=kw.get("pinned", 0), task_id=kw.get("task"), model=kw.get("model"), reasoning=kw.get("reasoning"),
                mode="default", summary=kw.get("summary", ""), summary_upto=kw.get("upto"), created_at=created, updated_at=updated)
    sq.execute(f"INSERT INTO conversations ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", list(cols.values()))
conv("c1", "p1", "数学", T(1), T(2), summary="旧摘要", upto="m1a")
conv("c2", "p1", "英语", T(2), T(4), model="m-old")
conv("c3", "p1", "政治", T(3), T(5), model="smart", reasoning="high", pinned=1)
conv("run", "p1", "脚本 · 10月05日", T(4), T(6), task="t1", src="fixed")      # 运行对话：不合并
conv("d1", "p2", "行程", T(1), T(1))
conv("main", None, "主聊天", T(1), T(1))
def msg(mid, cid, role, at):
    sq.execute("INSERT INTO messages (id, conversation_id, role, blocks, created_at) VALUES (?,?,?,?,?)",
               (mid, cid, role, json.dumps([{"type": "text", "text": mid}]), at))
for mid, cid, role, at in [("m1a", "c1", "user", T(1, 1)), ("m1b", "c1", "assistant", T(1, 2)), ("m2a", "c2", "user", T(2, 1)),
                           ("m3a", "c3", "user", T(3, 1)), ("m1c", "c1", "user", T(4, 1)), ("m2b", "c2", "assistant", T(4, 2)),
                           ("mr", "run", "user", T(4, 3)), ("md", "d1", "user", T(1, 3))]:
    msg(mid, cid, role, at)
sq.execute("INSERT INTO home_cards (id, kind, title, blocks, conversation_id, dismissed, unread, created_at, updated_at) "
           "VALUES ('card1', 'report', '报告', '[]', 'c2', 0, 0, ?, ?)", (T(4), T(4)))
sq.execute("INSERT INTO task_runs (id, task_id, trigger, status, conversation_id, started_at) VALUES ('r1', 't1', 'manual', 'ok', 'c3', ?)", (T(5),))
sq.commit()

def snapshot():
    q = lambda s: sq.execute(s).fetchall()
    return {"convs": q("SELECT id, project_id, title, title_source, title_at, pinned, task_id, model, reasoning, summary, summary_upto, "
                       "created_at FROM conversations ORDER BY id"),
            "msgs": q("SELECT id, conversation_id FROM messages ORDER BY id"),
            "card": q("SELECT conversation_id FROM home_cards"), "run": q("SELECT conversation_id FROM task_runs")}
before = snapshot()

alembic("upgrade", "head")
sq = sqlite3.connect(db_path)
after = snapshot()
p1 = sq.execute("SELECT id, title, title_source, title_at, summary, summary_upto, model, reasoning, pinned, updated_at FROM conversations "
                "WHERE project_id = 'p1' AND task_id IS NULL").fetchall()
assert len(p1) == 1, p1
kid, title, src, title_at, summary, upto, model, effort, pinned, updated = p1[0]
assert kid == "c1" and title == "考研" and src == "fixed" and title_at is None and summary == "" and upto is None, p1
assert (model, effort, pinned) == ("smart", "high", 1) and updated.startswith("2026-10-05"), p1           # 取最近那段
order = [r[0] for r in sq.execute("SELECT id FROM messages WHERE conversation_id = 'c1' ORDER BY created_at")]
assert order == ["m1a", "m1b", "m2a", "m3a", "m1c", "m2b"], order                                       # 按原时间交织
assert after["card"] == [("c1",)] and after["run"] == [("c1",)], after                                 # 引用改指
assert sq.execute("SELECT task_id FROM conversations WHERE id = 'run'").fetchone() == ("t1",)            # 运行对话不动
assert sq.execute("SELECT conversation_id FROM messages WHERE id = 'mr'").fetchone() == ("run",)
assert sq.execute("SELECT title FROM conversations WHERE id = 'd1'").fetchone() == ("行程",)              # 本来就一段：不碰
assert {r[0] for r in sq.execute("SELECT id FROM conversations")} == {"c1", "run", "d1", "main"}
backup = sq.execute("SELECT conversation_id, role FROM project_chat_merge_convs ORDER BY conversation_id").fetchall()
assert backup == [("c1", "kept"), ("c2", "merged"), ("c3", "merged")], backup

# 幂等：再跑一次合并函数，什么都不变
spec = importlib.util.spec_from_file_location("m0066", os.path.join(root, "migrations/versions/0066_project_one_chat.py"))
m0066 = importlib.util.module_from_spec(spec); spec.loader.exec_module(m0066)
import sqlalchemy as sa
eng = sa.create_engine(f"sqlite:///{db_path}")
with eng.begin() as cx:
    assert m0066.merge(cx) == 0
assert snapshot() == after

# 回退
alembic("downgrade", "0065")
sq = sqlite3.connect(db_path)
undone = snapshot()
norm = lambda s: {**s, "convs": [(*r[:11], r[11][:19]) for r in s["convs"]]}  # 回退后时间串格式可能少了微秒
assert norm(undone) == norm(before), (undone, before)
assert {r[1] for r in sq.execute("PRAGMA index_list(conversations)")} & {"uq_conversations_project_chat"} == set()
assert not {"project_chat_merge_convs", "project_chat_merge_refs"} & {r[0] for r in sq.execute("SELECT name FROM sqlite_master")}

# 再升级：结果与第一次一致
alembic("upgrade", "head")
sq = sqlite3.connect(db_path)
again = snapshot()
assert again["msgs"] == after["msgs"] and again["card"] == after["card"] and [r[0] for r in again["convs"]] == [r[0] for r in after["convs"]]

# 0067（v2.96）：主页卡去处 vault 并进 connectors（保险箱页合进“连接的账号”）
alembic("downgrade", "0066")
sq = sqlite3.connect(db_path)
sq.execute("INSERT INTO home_cards (id, kind, title, blocks, target, dismissed, unread, created_at, updated_at) "
           "VALUES ('cardv', 'action', '登录过期', '[]', 'vault', 0, 0, ?, ?)", (T(5), T(5)))
sq.commit()
alembic("upgrade", "head")
sq = sqlite3.connect(db_path)
assert sq.execute("SELECT target FROM home_cards WHERE id = 'cardv'").fetchone() == ("connectors",)
sq.execute("DELETE FROM home_cards WHERE id = 'cardv'"); sq.commit()

# ---------------------------------------------------------------- 二、约束
try:
    sq.execute("INSERT INTO conversations (id, project_id, title, title_source, pinned, mode, summary, created_at, updated_at) "
               "VALUES ('dup', 'p1', 'x', 'fixed', 0, 'default', '', ?, ?)", (T(6), T(6)))
    raise AssertionError("同一项目第二段普通对话不该插得进去")
except sqlite3.IntegrityError:
    pass
sq.execute("INSERT INTO conversations (id, project_id, title, title_source, pinned, mode, summary, task_id, created_at, updated_at) "
           "VALUES ('run2', 'p1', 'x', 'fixed', 0, 'default', '', 't9', ?, ?)", (T(6), T(6)))
sq.commit()
sq.close()

# ---------------------------------------------------------------- 三、接口
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import home_offers, project_chat, run_conversations
from app.auth import require_user
from app.db import SessionLocal
from app.models import Conversation, HomeCard, Message, Project, ScheduledTask
from app.routes import conversations
from app.routes.resources import routers

app = FastAPI()
for r in [*routers, conversations.router]:
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)

new = c.post("/api/projects", json={"name": "找实习"}).json()
assert new["conversation_id"] and "conversation_count" not in new and new["status"] is None, new
rows = {p["id"]: p for p in c.get("/api/projects").json()}
assert rows["p1"]["conversation_id"] == "c1" and rows["p3"]["conversation_id"] is None, rows
one = c.get("/api/conversations", params={"project_id": new["id"]}).json()
assert [x["id"] for x in one] == [new["conversation_id"]] and one[0]["title"] == "找实习" and "status" in one[0], one
assert c.get("/api/conversations", params={"project_id": new["id"]}).json()[0]["id"] == new["conversation_id"]  # 幂等
lazy = c.get("/api/conversations", params={"project_id": "p3"}).json()                                    # 没有 → 当场建
assert len(lazy) == 1 and c.get("/api/projects/p3").json()["conversation_id"] == lazy[0]["id"]
assert c.get("/api/conversations", params={"project_id": "nope"}).status_code == 404
assert c.get("/api/conversations", params={"project_id": "p1", "q": "数学"}).json()[0]["id"] == "c1"     # 项目里不搜索，只给那段
assert c.delete("/api/conversations/c1").status_code == 409
c.patch(f"/api/projects/{new['id']}", json={"name": "找暑期实习"})
assert c.get("/api/conversations", params={"project_id": new["id"]}).json()[0]["title"] == "找暑期实习"
main_ids = {x["id"] for x in c.get("/api/conversations").json()}
assert main_ids == {"main"}, main_ids

# ---------------------------------------------------------------- 四、运行对话 + 建议卡
async def runs():
    async with SessionLocal() as db:
        run = await db.get(Conversation, "run")
        assert run_conversations.promote(run) is False and run.task_id == "t1"     # 项目里：不 promote
        m = Conversation(title="早报", task_id="t1"); db.add(m); await db.flush()
        assert run_conversations.promote(m) is True and m.task_id is None          # 主聊天：照旧
        db.add_all([Message(conversation_id="run2", role="user", blocks=[]), Message(conversation_id="run2", role="user", blocks=[])])
        await db.commit()
        dropped = await run_conversations.drop(db, task_id="t9")                   # run2 用户回过话 → 不删
        assert dropped == 0 and await db.get(Conversation, "run2") is not None
        # 建议卡指向项目：“去做”发进项目那段对话，不新开
        card = HomeCard(kind="action", title="背单词", origin=home_offers.ORIGIN, action_prompt="安排背单词", target="project:p2")
        db.add(card); await db.commit()
        card, started = await home_offers.start(db, card.id)
        assert started and card.conversation_id == "d1", card.conversation_id
        assert (await project_chat.of(db, "p2")).id == "d1"
asyncio.run(runs())
print("ok smoke_project_chat")
