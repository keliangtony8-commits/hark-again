# 冒烟：运行中来的消息（app/message_intake.py，v2.90 home-redesign §C 定稿）。模拟模型（不打真接口）。
# 规则五类 → 静默合并（一口气发的几条一起判）→ 补充并进这一轮、回复一起结清 → 附和不回、挂在这一轮上结清 →
# 问进度不调模型、一句话 message.added → 无关新问题并行一路（主路还卡着时并行路先答完，reply_to + 结清）→
# 并行上限（第二件排在并行路后面）→ lite 判官失败按补充 → 重启的 interrupted 回复结清欠着的 → 迁移可回退。
# 运行：python tests/smoke_message_intake.py
import os, sys, asyncio, subprocess, tempfile
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from sqlalchemy import select
from app import live_turns, llm, message_intake as mi, steering, turn_journal
from app.agent import loop
from app.config import settings
from app.db import SessionLocal
from app.llm import Turn
from app.models import Message, TurnJournal
from app.routes import ws as rws

calls: list[list[dict]] = []
gates: dict[str, asyncio.Event] = {}  # 最后一条用户消息里含这个词 → 等这个闸门
entered: dict[str, asyncio.Event] = {}
judged: list[list[str]] = []


def text(c):
    return c if isinstance(c, str) else " ".join(p.get("text", "") for p in c if isinstance(p, dict))


async def fake_stream_turn(messages, tools=None, model=None, effort=None):
    calls.append([dict(m) for m in messages])
    last = text(next(m for m in reversed(messages) if m["role"] == "user")["content"])
    for k, g in gates.items():
        if k in last:
            entered.setdefault(k, asyncio.Event()).set()
            await g.wait()
            break
    out = f"答:{last[-12:]}"
    yield out
    yield Turn(text=out)
loop.stream_turn = fake_stream_turn


async def fake_complete(messages, model=None, kind="summary", **kw):
    if kind != "intake":
        return ""
    body = messages[0]["content"]
    judged.append([l[2:] for l in body.splitlines() if l.startswith("- ")])
    if "炸" in body:
        raise RuntimeError("网关挂了")
    return "NEW" if "天气" in body or "汇率" in body or "翻译" in body else "SUPPLEMENT"
llm.complete = fake_complete


class Client:
    def __init__(self):
        self.events: list[dict] = []
        self.conn = live_turns.Conn(self.send)

    async def send(self, e):
        self.events.append(e)

    async def until(self, pred, timeout=8):
        async with asyncio.timeout(timeout):
            while not pred(self.events):
                await asyncio.sleep(0.01)
        return self.events


def of(t):
    return lambda es: [e for e in es if e["type"] == t]


async def rows(cid):
    async with SessionLocal() as db:
        return list((await db.scalars(select(Message).where(Message.conversation_id == cid).order_by(Message.created_at))).all())


def txt(m):
    return "".join(b.get("text", "") for b in m.blocks)


async def start(c: Client, q: str, gate: str):
    gates[gate] = asyncio.Event()
    entered[gate] = asyncio.Event()
    t = live_turns.enqueue(rws._handle_user_message, {"type": "user.message", "text": q}, c.conn)
    await asyncio.wait_for(entered[gate].wait(), 5)
    cid = of("message.start")(c.events)[0]["conversation_id"]
    live_turns.resume(c.conn, {"conversation_id": cid})  # 客户端打开对话 = 旁观（message.added 推得到）
    return t, cid


async def say(cid, words, client_id=None):
    ev = {"type": "user.message", "conversation_id": cid, "text": words, "steer": True}
    if client_id:
        ev["client_id"] = client_id
    assert await rws._intake(ev), words


async def main():
    settings.turn_offline_minutes = 30

    # 0) 规则（只看用户在 Hark 里看到的公开表现：附和不回、问进度一句话、补充并进去）
    for s in ("好的", "嗯嗯", "OK", "就这种", "收到！", "👍"):
        assert mi.rule(s) == mi.RIDE, s
    for s in ("怎么样了", "是不是又停下来了", "好了没", "进度如何", "还要多久"):
        assert mi.rule(s) == mi.PROGRESS, s
    for s in ("对了，要按周排", "改成英文", "算了不用了", "不要加表情", "记得发我文件"):
        assert mi.rule(s) == mi.STEER, s
    for s in ("有没有做版本管理", "明天天气怎么样", "帮我把这段翻译成英文：你好"):
        assert mi.rule(s) is None, s
    assert mi.rule("", files=True) == mi.STEER and mi.rule("好的", files=True) == mi.STEER, "带附件不是附和"
    print("ok: 规则")

    mi.QUIET_S = 0.3

    # 1) 补充三连（一口气发）+ 附和：并进这一轮，一条回复结清全部；lite 判官只问一次
    a = Client()
    t, cid = await start(a, "写个周计划", "周计划")
    await say(cid, "对了，要按周排", "l1")
    await say(cid, "每天不超过一小时")
    await say(cid, "好的")
    await asyncio.sleep(0.05)
    assert len(of("turn.steered")(a.events)) == 3, "落库即认领，不等分流"
    assert of("turn.steered")(a.events)[0]["client_id"] == "l1"
    await mi.settle_all(cid)
    assert judged == [["每天不超过一小时"]], judged
    gates["周计划"].set()
    await a.until(lambda es: of("message.done")(es))
    await asyncio.wait_for(asyncio.shield(t.task), 5)
    await live_turns.drain()
    r = await rows(cid)
    reply = [m for m in r if m.role == "assistant"]
    assert len(reply) == 1, [(m.role, txt(m)) for m in r]
    users = [m for m in r if m.role == "user"]
    assert {m.answered_by for m in users} == {reply[0].id}, [(txt(m), m.answered_by) for m in users]
    assert reply[0].reply_to == users[0].id
    seen = [text(m["content"]) for m in calls[-1] if m["role"] == "user"]
    assert "对了，要按周排" in seen and "每天不超过一小时" in seen and "好的" not in seen, seen
    done = of("message.done")(a.events)[0]["message"]
    assert done["reply_to"] == users[0].id and done["quote"]["text"] == "写个周计划", done
    print("ok: 补充三连 + 附和 → 一条回复结清全部")

    # 2) 问进度：不调模型，从这一轮的步骤一句话答（message.added，reply_to = 那句）
    calls.clear(); judged.clear()
    b = Client()
    t2, cid2 = await start(b, "整理下载文件夹", "下载")
    live_turns.running(cid2).steps.append({"id": "s1", "title": "正在运行命令", "detail": "ls ~/Downloads", "state": "running"})
    n = len(calls)
    await say(cid2, "怎么样了")
    await b.until(lambda es: of("message.added")(es))
    added = of("message.added")(b.events)[0]
    assert added["conversation_id"] == cid2 and "正在运行命令" in str(added["message"]["blocks"]), added
    assert len(calls) == n and not judged, "问进度不调模型"
    q = [m for m in await rows(cid2) if txt(m) == "怎么样了"][0]
    assert added["message"]["reply_to"] == q.id and q.answered_by == added["message"]["id"]
    assert "turn_id" not in added, "对话级事件，不属于这一轮"
    gates["下载"].set()
    await asyncio.wait_for(asyncio.shield(t2.task), 5)
    print("ok: 问进度一句话")

    # 3) 无关的新问题：并行一路——主路还卡着，并行路先答完；主路的回复不受影响
    calls.clear(); judged.clear()
    c = Client()
    t3, cid3 = await start(c, "把报告写完", "报告")
    await say(cid3, "顺带问下，明天天气怎么样")
    await c.until(lambda es: of("message.added")(es))
    side = of("message.added")(c.events)[0]["message"]
    assert "天气" in str(side["blocks"]) and side["quote"]["text"].startswith("顺带问下"), side
    assert not of("message.done")(c.events), "主路还在跑"
    sys_side = calls[-1][0]["content"]
    assert "[并行处理]" in sys_side, "并行路的模型知道只回最后这件事"
    assert "把报告写完" not in str([m["content"] for m in calls[-1] if m["role"] == "user"]), "主路那件还没回复的事并行路看不到（E2E 不藏会去答它）"
    assert steering.active(cid3), "并行路不碰主路的收件箱"
    gates["报告"].set()
    await c.until(lambda es: of("message.done")(es))
    await live_turns.drain()
    r = await rows(cid3)
    users = [m for m in r if m.role == "user"]
    replies = [m for m in r if m.role == "assistant"]
    assert len(replies) == 2 and replies[0].id == side["id"], [(m.role, txt(m)) for m in r]
    assert users[0].answered_by == replies[1].id and users[1].answered_by == replies[0].id
    async with SessionLocal() as db:
        assert await mi.owed(db, cid3) == []
    print("ok: 新问题并行一路，各回各的")

    # 4) 带引用回复 = 另一件事（不问判官）；并行上限：第二件排在并行路后面
    judged.clear()
    d = Client()
    t4, cid4 = await start(d, "跑一下测试", "测试")
    gates["汇率"] = asyncio.Event(); entered["汇率"] = asyncio.Event()
    await say(cid4, "美元汇率多少")
    await asyncio.wait_for(entered["汇率"].wait(), 5)
    first = [m for m in await rows(cid4) if txt(m) == "美元汇率多少"][0]
    ev = {"type": "user.message", "conversation_id": cid4, "text": "这个要多久", "steer": True, "reply_to": first.id}
    assert await rws._intake(ev)
    await mi.settle_all(cid4)
    await asyncio.sleep(0.3)
    assert not of("message.added")(d.events), "第二件等并行路空出来"
    assert judged == [["美元汇率多少"]], judged
    gates["汇率"].set()
    await d.until(lambda es: len(of("message.added")(es)) >= 2)
    gates["测试"].set()
    await live_turns.drain()
    added = [e["message"] for e in of("message.added")(d.events)]
    assert added[1]["reply_to"] != added[0]["reply_to"]
    print("ok: 引用 = 新的一件事 + 并行上限 1")

    # 5) 判官出错 → 按补充并进去（宁少勿多）
    judged.clear()
    e = Client()
    t5, cid5 = await start(e, "装个依赖", "依赖")
    await say(cid5, "炸了的话就换个镜像源")
    await mi.settle_all(cid5)
    gates["依赖"].set()
    await live_turns.drain()
    r = await rows(cid5)
    assert len([m for m in r if m.role == "assistant"]) == 1 and len({m.answered_by for m in r if m.role == "user"}) == 1
    print("ok: 判官失败按补充")

    # 6) 收尾后才到的附和：不回，算被上一条回复结清
    async with SessionLocal() as db:
        m = Message(conversation_id=cid5, role="user", blocks=[{"type": "text", "text": "好的"}], status=steering.STEER)
        db.add(m); await db.commit()
    await mi._route(cid5, mi.RIDE, [mi.Arrival(m.id, "好的", "好的", m.created_at)])
    r = await rows(cid5)
    assert r[-1].answered_by == [x for x in r if x.role == "assistant"][-1].id and len([x for x in r if x.role == "assistant"]) == 1
    print("ok: 说完后的附和不回")

    # 7) 重启：被打断那一轮的 interrupted 回复结清它欠着的（不自动重跑）
    async with SessionLocal() as db:
        u = Message(conversation_id=cid5, role="user", blocks=[{"type": "text", "text": "再装一个"}])
        db.add(u); await db.flush()
        db.add(TurnJournal(conversation_id=cid5, owner=turn_journal.owner().split(":")[0] + ":old-boot", blocks=[{"type": "text", "text": "装到一半"}], steps=[], trace=[]))
        await db.commit()
        assert u.id in await mi.owed(db, cid5)
        assert await turn_journal.recover(db, cid5) == 1
        assert await mi.owed(db, cid5) == []
    print("ok: 重启恢复结清、不重发")

    await live_turns.drain()
    subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0063"], cwd=root, check=True, capture_output=True)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)
    print("ok: 迁移 0064 可回退")
    print("ALL OK")


asyncio.run(main())
