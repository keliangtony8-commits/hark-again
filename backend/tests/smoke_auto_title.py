# 冒烟：对话自动起标题（app/conversation_title.py，移植自 Gemini CLI sessionSummaryService）。模拟模型（不打真接口）。
# 一、Gemini 测试改写：选材（只 user/assistant 非空、滑动窗口前 10 + 后 10、顺序、系统消息不占名额）、截 500 字加 ...、
#    清洗（换行空白、引号、中文前缀/书名号/句号、截断）、空材料不调模型、超时 / 报错 / 空回复 → None；
# 二、整轮：新对话 first → 第一轮后标题换成模型起的 + conversation.title 事件排在 message.done 之后 + 用量 kind=title + 不改 updated_at；
#    第二轮不再起；用户改名后不覆盖（含起名途中改名）；失败下一轮重试、超过 TITLE_TRIES 不再试；fixed（任务对话）不碰；关闭开关；
#    v2.91：名词短语清洗（无标点、不口语、≤14 字）、due()、auto 标题每 10 条复查（没变不推事件、变了换名、途中改名不覆盖）、0065 回填；
#    （停在还没吐字时 run_turn 返回 None，不起名：见 ws.py 的判断）断线续传快照停在 message.done 之前，收尾事件照补；迁移 down/up。
# 运行：python tests/smoke_auto_title.py
import os, sys, asyncio, subprocess, tempfile
from types import SimpleNamespace as NS
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", LLM_MAX_RETRIES="0")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from sqlalchemy import select
from app import conversation_title as ct, live_turns, llm, usage
from app.agent import loop
from app.config import settings
from app.db import SessionLocal
from app.llm import Turn
from app.models import Conversation, Message, UsageRecord
from app.routes import ws as rws

# —— 一、规则 ——
msgs = [("user", "How do I add dark mode?"), ("assistant", "Here is a detailed explanation")]
assert ct.select_messages(msgs) == msgs
assert ct.select_messages([]) == [] and ct.select_messages([("user", "  "), ("system", "x")]) == []
many = [("user" if i % 2 == 0 else "assistant", f"Message {i}") for i in range(50)]
picked = ct.select_messages(many)
assert len(picked) == 20 and picked[0][1] == "Message 0" and picked[9][1] == "Message 9"
assert picked[10][1] == "Message 40" and picked[-1][1] == "Message 49" and "Message 25" not in str(picked)
idx = [int(t.split()[1]) for _, t in picked]
assert idx == sorted(idx)                                              # 顺序保留
assert len(ct.select_messages(many[:20])) == 20 and len(ct.select_messages(many[:5])) == 5
mixed = [("system", "info")] * 30 + many[:20]                          # 系统消息不占窗口名额
assert ct.select_messages(mixed) == many[:20]
assert len(ct.select_messages(many, 7)) == 7 and ct.select_messages(many, 1) == many[:1]
text = ct.conversation_text([("user", "a" * 600), ("assistant", "好的")])
assert "a" * 500 + "..." in text and "a" * 501 not in text and "助手: 好的" in text and text.startswith("用户: ")
for raw, want in [
    ("Add dark mode\n\nto the app", "Add dark mode to the app"),
    ('"Add dark mode to the app"', "Add dark mode to the app"),
    ("'Add dark mode to the app'", "Add dark mode to the app"),
    ("标题：给 App 加深色模式。", "给 App 加深色模式"),
    ("《杭州两日游》", "杭州两日游"), ("“「修登录 bug」”", "修登录 bug"),
    ("- 搞懂路由", "搞懂路由"), ("Title: Fix auth bug.", "Fix auth bug"),
    ("", None), (None, None), ("   。", None), ("“”", None),
]:
    assert ct.clean(raw) == want, (raw, ct.clean(raw))
assert len(ct.clean("长" * 80)) == ct.TITLE_MAX
# v2.91 §N：名词短语、无标点、不口语、≤14 字 / 英文按词 ≤40
for raw, want in [
    ("帮我把 App 加上深色模式，跟随系统", "把 App 加上深色模式跟随系统"),
    ("考研数学：错题整理（第二轮）", "考研数学错题整理第二轮"),
    ("新标题：杭州周末两日行程。", "杭州周末两日行程"),
    ("请问如何部署到 VPS？", "部署到 VPS"),
    ("Vue.js 与 C++ 接口对接", "Vue.js 与 C++ 接口对接"),
    ("A very long english conversation title that keeps going on", "A very long english conversation title"),
    ("？！。", None),
]:
    assert ct.clean(raw) == want, (raw, ct.clean(raw))
assert ct.clean("一二三四五六七八九十一二三四五六") == "一二三四五六七八九十一二三四"
assert ct.clean("给 App 加深色模式并且适配所有页面的颜色") == "给 App 加深色模式并且适配所"
assert ct.clean("考研数学错题整理与 PostgreSQL") == "考研数学错题整理与"  # 截点落在英文词中间：退到词前
assert len(ct.clean("x " * 60)) <= ct.TITLE_MAX_LATIN
# 该不该叫模型
assert ct.due("first", 1, 2, None) and not ct.due("first", 0, 0, None) and not ct.due("first", 4, 8, None)
assert ct.due("auto", 9, 12, 2) and not ct.due("auto", 9, 11, 2) and ct.due("auto", 5, 10, None)
assert not ct.due("user", 9, 99, 0) and not ct.due("fixed", 9, 99, 0)
assert ct.first_title("  你好\n\n世界  ") == "你好 世界" and ct.first_title("") == "新对话" and len(ct.first_title("x" * 99)) == 40

calls: list[dict] = []
mode = {"reply": "给 App 加深色模式", "delay": 0.0, "error": False}


def tcalls():
    return [k for k in calls if "作为对话标题" in str(k.get("messages"))]


class FakeCompletions:
    async def create(self, **kw):
        calls.append(kw)
        if mode["delay"]:
            await asyncio.sleep(mode["delay"])
        if mode["error"]:
            raise RuntimeError("网关挂了")
        return NS(choices=[NS(message=NS(content=mode["reply"]), finish_reason="stop")],
                  usage=NS(prompt_tokens=50, completion_tokens=8, prompt_tokens_details=None))


llm.client = NS(chat=NS(completions=FakeCompletions()))


async def fake_stream_turn(messages, tools=None, model=None, effort=None):
    yield "好的，"
    yield Turn(text="好的，这样做。")
loop.stream_turn = fake_stream_turn


async def rules():
    calls.clear()
    assert await ct.generate([]) is None and not calls                      # 空材料不调模型
    assert await ct.generate([("system", "x")]) is None and not calls
    assert await ct.generate(msgs) == "给 App 加深色模式" and len(calls) == 1
    kw = calls[0]
    assert kw["model"].endswith(settings.summary_model) or settings.summary_model in str(kw["model"])
    assert "用户: How do I add dark mode?" in kw["messages"][0]["content"] and kw["max_tokens"] == 60
    mode.update(delay=0.5)
    assert await ct.generate(msgs, timeout=0.05) is None                    # 超时
    mode.update(delay=0.0, error=True)
    assert await ct.generate(msgs) is None                                  # 报错
    mode.update(error=False, reply="   ")
    assert await ct.generate(msgs) is None                                  # 空回复
    mode.update(reply="给 App 加深色模式")


class Client:
    def __init__(self):
        self.events: list[dict] = []
        self.conn = live_turns.Conn(self.send, self.overflow)

    async def send(self, e):
        self.events.append(e)

    async def overflow(self):
        pass


async def turn(text, cid=None):
    c = Client()
    ev = {"type": "user.message", "text": text, **({"conversation_id": cid} if cid else {})}
    t = live_turns.enqueue(rws._handle_user_message, ev, c.conn)
    await t.task
    await ct.drain()
    await asyncio.sleep(0.05)
    return c, t


def racing_cid(target):
    async def racing(m, timeout=ct.TIMEOUT_S, **kw):
        async with SessionLocal() as db2:
            await db2.execute(Conversation.__table__.update().where(Conversation.id == target)
                              .values(title_source="user", title="用户起的"))
            await db2.commit()
        return "模型起的"
    return racing


async def conv(cid):
    async with SessionLocal() as db:
        return await db.get(Conversation, cid, populate_existing=True)


async def main():
    await rules()

    # 1) 新对话：第一轮后自动起名，事件在 message.done 之后
    calls.clear()
    c, t = await turn("帮我  把 app 加一个深色模式，跟随系统切换")
    cid = c.events[0]["conversation_id"]
    assert c.events[0]["title"] == "帮我 把 app 加一个深色模式，跟随系统切换"[:40]
    types = [e["type"] for e in c.events]
    assert types.index("conversation.title") > types.index("message.done"), types
    te = next(e for e in c.events if e["type"] == "conversation.title")
    assert te == {"type": "conversation.title", "conversation_id": cid, "title": "给 App 加深色模式",
                  "turn_id": t.id, "seq": te["seq"]}
    cv = await conv(cid)
    assert cv.title == "给 App 加深色模式" and cv.title_source == "auto"
    assert "帮我  把 app" in tcalls()[-1]["messages"][0]["content"] and "助手: 好的，" in tcalls()[-1]["messages"][0]["content"]
    async with SessionLocal() as db:
        kinds = [u.kind for u in (await db.scalars(select(UsageRecord))).all()]
    assert "title" in kinds

    # 断线续传：快照停在 message.done 之前，done + title 照补
    snap = t.snapshot()
    done_seq = next(e["seq"] for e in c.events if e["type"] == "message.done")
    assert snap["seq"] == done_seq - 1
    t.log.popleft()  # 让游标落进缺口
    r = Client()
    live_turns.resume(r.conn, {"type": "turn.resume", "turn_id": t.id, "after": 0})
    await asyncio.sleep(0.05)
    assert [e["type"] for e in r.events][:2] == ["turn.resumed", "turn.snapshot"]
    assert [e["type"] for e in r.events][-2:] == ["message.done", "conversation.title"], [e["type"] for e in r.events]

    # 2) 第二轮不再起
    n = len(tcalls())
    c2, _ = await turn("再加个开关", cid)
    assert not any(e["type"] == "conversation.title" for e in c2.events) and len(tcalls()) == n

    # 3) 用户改过名：不覆盖（REST PATCH 设 user）
    from app.routes.conversations import ConversationPatch, patch_conversation
    c3, _ = await turn("今晚吃什么")
    cid3 = c3.events[0]["conversation_id"]
    assert (await conv(cid3)).title_source == "auto"
    c4, _ = await turn("周末去哪玩")
    cid4 = c4.events[0]["conversation_id"]
    async with SessionLocal() as db:   # 回到 first 再模拟“用户改名”
        await db.execute(Conversation.__table__.update().where(Conversation.id == cid4).values(title_source="first"))
        await db.commit()
        await patch_conversation(cid4, ConversationPatch(title=" 我的周末 "), db)
    cv4 = await conv(cid4)
    assert cv4.title == "我的周末" and cv4.title_source == "user"
    n = len(tcalls())
    async with SessionLocal() as db:
        assert await ct.maybe(db, cid4) is None and len(tcalls()) == n          # 根本不调模型

    # 4) 起名途中用户改名：UPDATE 里的条件挡住
    c5, _ = await turn("x")
    cid5 = c5.events[0]["conversation_id"]
    async with SessionLocal() as db:
        await db.execute(Conversation.__table__.update().where(Conversation.id == cid5).values(title_source="first", title="x"))
        await db.commit()
    real = ct.generate

    async def racing(m, timeout=ct.TIMEOUT_S, **kw):
        async with SessionLocal() as db2:
            await db2.execute(Conversation.__table__.update().where(Conversation.id == cid5)
                              .values(title_source="user", title="用户起的"))
            await db2.commit()
        return "模型起的"
    ct.generate = racing
    async with SessionLocal() as db:
        assert await ct.maybe(db, cid5) is None
    ct.generate = real
    cv5 = await conv(cid5)
    assert cv5.title == "用户起的" and cv5.title_source == "user"

    # 5) 失败下一轮重试；超过 TITLE_TRIES 不再试
    mode.update(error=True)
    c6, _ = await turn("第一句")
    cid6 = c6.events[0]["conversation_id"]
    assert not any(e["type"] == "conversation.title" for e in c6.events)
    cv6 = await conv(cid6)
    assert cv6.title == "第一句" and cv6.title_source == "first"
    mode.update(error=False, reply="重试成功的标题")
    c7, _ = await turn("第二句", cid6)
    assert any(e["type"] == "conversation.title" and e["title"] == "重试成功的标题" for e in c7.events)
    mode.update(error=True)
    c8, _ = await turn("A")
    cid8 = c8.events[0]["conversation_id"]
    for s in ("B", "C"):
        await turn(s, cid8)
    mode.update(error=False)
    n = len(tcalls())
    await turn("D", cid8)                                                      # 第 4 个用户回合：不再试
    assert len(tcalls()) == n and (await conv(cid8)).title_source == "first"

    # 6) fixed（定时任务对话、老数据）不碰；关掉开关不起
    async with SessionLocal() as db:
        fx = Conversation(title="每日简报")
        db.add(fx)
        await db.flush()
        db.add(Message(conversation_id=fx.id, role="user", blocks=[{"type": "text", "text": "hi"}]))
        db.add(Message(conversation_id=fx.id, role="assistant", blocks=[{"type": "text", "text": "yo"}]))
        await db.commit()
        assert fx.title_source == "fixed"
        global fx_id
        fx_id = fx.id
        assert await ct.maybe(db, fx.id) is None
    settings.auto_title = False
    n = len(tcalls())
    c9, _ = await turn("关掉之后")
    assert not any(e["type"] == "conversation.title" for e in c9.events) and len(tcalls()) == n
    assert ct.schedule("x", c9.conn.put) is None
    settings.auto_title = True

    # 7) v2.91 复查：auto 标题每多 RETITLE_EVERY 条消息问一次；话题没变 → 不推事件只推进 title_at；变了 → 换名 + 事件
    mode.update(reply="App 深色模式适配", error=False)
    c10, _ = await turn("给 app 做深色模式")
    cid10 = c10.events[0]["conversation_id"]
    cv10 = await conv(cid10)
    assert cv10.title == "App 深色模式适配" and cv10.title_source == "auto" and cv10.title_at == 2
    n = len(tcalls())
    for k in range(4):                                                      # 2 → 10 条：比上次多不到 10 条，不问
        cx, _ = await turn(f"继续 {k}", cid10)
        assert not any(e["type"] == "conversation.title" for e in cx.events)
    assert len(tcalls()) == n
    c11, _ = await turn("再调一下颜色", cid10)                              # 12 条：多了 10 条，复查一次，话题没变
    assert len(tcalls()) == n + 1 and "现在的标题是：App 深色模式适配" in tcalls()[-1]["messages"][0]["content"]
    assert not any(e["type"] == "conversation.title" for e in c11.events)
    cv10 = await conv(cid10)
    assert cv10.title == "App 深色模式适配" and cv10.title_at == 12
    mode.update(reply="「周末杭州行程规划」。")
    for k in range(4):                                                      # 12 → 20：不问
        await turn(f"换个话题 {k}", cid10)
    assert len(tcalls()) == n + 1
    c12, _ = await turn("杭州住哪", cid10)                                   # 22 条：复查，话题变了
    assert len(tcalls()) == n + 2
    te = next(e for e in c12.events if e["type"] == "conversation.title")
    assert te["title"] == "周末杭州行程规划"
    cv10 = await conv(cid10)
    assert cv10.title == "周末杭州行程规划" and cv10.title_source == "auto" and cv10.title_at == 22
    # 复查途中用户改名：UPDATE 条件挡住（来源已不是 auto）
    async with SessionLocal() as db:
        await db.execute(Conversation.__table__.update().where(Conversation.id == cid10).values(title_at=0))
        await db.commit()
    ct.generate = racing_cid(cid10)
    async with SessionLocal() as db:
        assert await ct.maybe(db, cid10) is None
    ct.generate = real
    assert (await conv(cid10)).title == "用户起的"
    mode.update(reply="给 App 加深色模式")

    # 8) 迁移 down/up；0065 回填已有 auto 对话的 title_at = 当前消息数
    r = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0064"], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    cv = await conv(cid)
    async with SessionLocal() as db:
        from sqlalchemy import func
        nmsg = await db.scalar(select(func.count()).select_from(Message).where(Message.conversation_id == cid))
    assert cv.title_source == "auto" and cv.title_at == nmsg, (cv.title_at, nmsg)
    assert (await conv(cid6)).title_at is not None and (await conv(fx_id)).title_at is None
    r = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "0036"], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    print("smoke_auto_title ok")


asyncio.run(main())
