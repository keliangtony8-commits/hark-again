# 冒烟（v2.91 §N）：项目对话列表的状态胶囊（app/conversation_status.py 唯一规则）。
# 一、纯规则：问号收尾（含 Markdown / 引号收尾、只看最后一段）、挂起卡片（审批 / 表单 / 下单 / 方案 / 浏览器接管）、
#    在跑 > 任务 > 最后一条；被停 / 打断 / 用户消息结尾 / 没消息 → None；
# 二、接口：GET /api/conversations?project_id= 每项带 status（最后一条取对、常驻任务不算、followup=pending 算、
#    live_turns 在跑的一轮 running、挂着表单 waiting、并行路也算）；主聊天列表和搜索结果不带 status。
# 三、v2.93 §Q 项目汇总：summarize 纯规则（waiting > running > 最近那段 done > None），
#    GET /api/projects 的只读字段 status（_project_activity）：同口径（定时任务的运行对话不算）、空项目 None。
# 运行：python tests/smoke_conversation_status.py
import os, sys, asyncio, subprocess, tempfile
from datetime import datetime, timedelta, timezone
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from app import conversation_status as cs, live_turns
from app.db import SessionLocal
from app.models import Conversation, Job, Message, Project
from sqlalchemy import select
from app.routes.conversations import list_conversations


def text(t):
    return [{"type": "text", "text": t}]


# —— 一、纯规则 ——
assert cs.asks(text("要我接着把测试补上吗？")) and cs.asks(text("Shall I continue?"))
assert cs.asks(text("**要现在部署吗？**")) and cs.asks(text("你说的是“这一版吗？”"))
assert not cs.asks(text("已部署完成。")) and not cs.asks([]) and not cs.asks(None)
assert not cs.asks(text("你问：要不要部署？\n\n已经部署好了。"))           # 只看最后一段
assert cs.asks(text("结果如下。\n\n要不要再查一遍？"))
assert cs.asks([*text("要不要再查一遍？"), {"type": "file", "name": "a.txt"}])  # 最后一个文字块
done = ("assistant", "done", text("好了。"))
assert cs.derive(None, False, done) == cs.DONE
assert cs.derive(None, False, ("assistant", "wrapped", text("先到这里。"))) == cs.DONE
assert cs.derive(None, False, ("assistant", "done", text("要继续吗？"))) == cs.WAITING
for st in ("stopped", "interrupted", "looped"):
    assert cs.derive(None, False, ("assistant", st, text("要继续吗？"))) is None
assert cs.derive(None, False, ("user", "done", text("在吗"))) is None and cs.derive(None, False, None) is None
assert cs.derive(None, True, done) == cs.RUNNING                                  # 后台任务在跑
assert cs.derive([[]], False, done) == cs.RUNNING                                 # 一轮在跑
for b in [{"type": "approval", "id": "a", "title": "", "detail": "", "state": "pending"},
          {"type": "form", "id": "f", "state": "pending"}, {"type": "order", "id": "o", "state": "pending"},
          {"type": "plan_review", "id": "p", "state": "pending"},
          {"type": "browser", "handoff": {"id": "h", "reason": "验证码", "state": "pending"}}]:
    assert cs.derive([[*text("稍等"), b]], False, done) == cs.WAITING, b
assert cs.derive([[{"type": "form", "id": "f", "state": "submitted"}]], False, done) == cs.RUNNING
assert cs.derive([[{"type": "browser", "handoff": {"state": "done"}}]], True, None) == cs.RUNNING
# 三、项目汇总（纯规则）：列表按最近更新排在前
assert cs.summarize(["done", None, "waiting", "running"]) == cs.WAITING     # 任一等你回复
assert cs.summarize([None, "done", "running"]) == cs.RUNNING                # 否则任一进行中
assert cs.summarize(["done", None]) == cs.DONE                              # 否则看最近那段
assert cs.summarize([None, "done"]) is None and cs.summarize([]) is None    # 最近那段没结论 → 不画


async def main():
    t0 = datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)
    async with SessionLocal() as db:
        db.add(Project(id="p1", name="考研"))
        convs = {k: Conversation(title=k, project_id="p1") for k in
                 ("done", "ask", "stopped", "user_last", "empty", "job", "service", "followup", "live", "live_form", "side")}
        convs["main"] = Conversation(title="main")
        db.add_all(convs.values())
        await db.flush()
        ids = {k: c.id for k, c in convs.items()}

        def msg(k, role, blocks, status="done", dt=0):
            db.add(Message(conversation_id=ids[k], role=role, blocks=blocks, status=status, created_at=t0 + timedelta(seconds=dt)))
        msg("done", "assistant", text("要继续吗？"), dt=1)          # 早的那条在问，最后一条没问 → done
        msg("done", "user", text("继续"), dt=2)
        msg("done", "assistant", text("已经全部整理好了。"), dt=3)
        msg("ask", "user", text("帮我看看"), dt=1)
        msg("ask", "assistant", text("找到两个版本，要用哪一个？"), dt=2)
        msg("stopped", "assistant", text("写到一半"), status="stopped", dt=1)
        msg("user_last", "assistant", text("好了。"), dt=1)
        msg("user_last", "user", text("再改一下"), dt=2)
        for k in ("job", "service", "followup", "live", "live_form", "side", "main"):
            msg(k, "assistant", text("好了。"), dt=1)
        db.add(Job(id="j1", project_id="p1", conversation_id=ids["job"], title="训练", command="x", timeout=60, state="running"))
        db.add(Job(id="j2", project_id="p1", conversation_id=ids["service"], title="服务", command="x", timeout=0, state="running", keep_alive=True))
        db.add(Job(id="j3", project_id="p1", conversation_id=ids["followup"], title="爬取", command="x", timeout=60, state="done", followup="pending"))
        db.add(Job(id="j4", project_id="p1", conversation_id=ids["done"], title="旧任务", command="x", timeout=60, state="done", followup="done"))
        await db.commit()

    # 本进程在跑的轮次：主路（含 / 不含挂起表单）、并行路（还没 message.start，只认 key）
    def fake(key, conv_id, blocks):
        t = live_turns.Turn(key)
        t.conv_id, t.running, t.blocks = conv_id, True, blocks
        live_turns._turns[t.id] = t
        return t
    fake(ids["live"], ids["live"], text("正在查"))
    fake(ids["live_form"], ids["live_form"], [*text("需要你登录"), {"type": "form", "id": "f1", "state": "pending"}])
    fake(ids["side"] + live_turns.SIDE, None, [])
    ended = fake(ids["empty"], ids["empty"], [])
    ended.ended = True                                                    # 收尾保留期里的旧轮次不算

    async with SessionLocal() as db:
        rows = await list_conversations(project_id="p1", q="", db=db)
    got = {r["title"]: r["status"] for r in rows}
    assert got == {"done": "done", "ask": "waiting", "stopped": None, "user_last": None, "empty": None, "job": "running",
                   "service": "done", "followup": "running", "live": "running", "live_form": "waiting", "side": "running"}, got
    async with SessionLocal() as db:
        main_rows = await list_conversations(project_id=None, q="", db=db)
        found = await list_conversations(project_id="p1", q="ask", db=db)
    assert main_rows and all("status" not in r for r in main_rows)       # 主聊天列表不带
    assert found and all("status" not in r for r in found)               # 搜索结果不带
    assert live_turns.busy().keys() == {ids["live"], ids["live_form"], ids["side"]}

    # 三、项目汇总：p1 里有挂着表单的一轮 → waiting；p2 最近一段做完 → done；p3 最近一段被停（更早的做完）→ None；
    # p4 只有一个后台任务在跑 → running；p5 没对话 → None；p6 只有定时任务的运行对话（不在列表里）→ None
    from app.routes.resources import _project_activity
    async with SessionLocal() as db:
        db.add_all([Project(id=f"p{i}", name=f"p{i}") for i in range(2, 7)])
        c = {k: Conversation(title=k, project_id=pid, updated_at=t0 + timedelta(minutes=m), task_id=task) for k, pid, m, task in [
            ("p2_old", "p2", 1, None), ("p2_new", "p2", 5, None), ("p3_old", "p3", 1, None), ("p3_new", "p3", 5, None),
            ("p4_job", "p4", 1, None), ("p6_run", "p6", 1, "t1")]}
        db.add_all(c.values())
        await db.flush()
        for k, role, st, body in [("p2_old", "assistant", "stopped", "停"), ("p2_new", "assistant", "done", "好了。"),
                                  ("p3_old", "assistant", "done", "好了。"), ("p3_new", "assistant", "stopped", "停"),
                                  ("p4_job", "assistant", "done", "好了。"), ("p6_run", "assistant", "done", "要继续吗？")]:
            db.add(Message(conversation_id=c[k].id, role=role, blocks=text(body), status=st, created_at=t0))
        db.add(Job(id="j5", project_id="p4", conversation_id=c["p4_job"].id, title="训练", command="x", timeout=60, state="running"))
        await db.commit()
        projects = list((await db.scalars(select(Project))).all())
        stats = await _project_activity(db, projects)
    assert {pid: v["status"] for pid, v in stats.items()} == {
        "p1": "waiting", "p2": "done", "p3": None, "p4": "running", "p5": None, "p6": None}, stats
    assert stats["p6"]["conversation_count"] == 1                        # 统计口径不变（只读字段只多一个 status）
    print("smoke_conversation_status ok")


asyncio.run(main())
