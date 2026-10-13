# 冒烟：v1.36 浏览器登录过期 → 重登。
# 1) 规则：login_page（密码框 / 登录类网址与主机 / 页面开头“请重新登录”；正文深处的“登录”不算、/author 不算）；
#    observe：没登录过的会话见登录页不提醒；登录过的又见登录页 → expired（标一次、每次打开提醒一次）；
#    见过登录页 + auth 动作后不是登录页 → signed_in；非 auth 动作离开登录页不算登录成功；
# 2) 模拟模型 + 假浏览器（服务端登录标记也假在内存里）：
#    a. 聊天里打开登录过的淘宝 → 登录页 → 模型被告知“登录已过期”+ 保险箱没有 → 弹登录卡 / 接管；服务端记 expired；
#       用户在登录卡上填完 → 不再是登录页 → 服务端记 signed_in；
#    b. 保险箱有 → 提示直接 browser_login，不问用户；browser_login 代填 → signed_in；
#    c. 定时任务 + 保险箱没有 → 提示做不了 + Home 上一张系统提醒（去处 = 该任务、带“去做”），同一过期只发一次；
#       之后在聊天里重登成功 → 提醒收起；
#    d. 任务中途过期：打开时正常、点击后跳到登录页 → 提醒；
#    e. 从没登录过：登录页不提醒，browser_login 成功后记 signed_in；
#    f. v2.50 自动重登：保险箱有 + 登录页判得准 → 打开时直接代填，模型拿到登录后的页面（不用 browser_login）；
#       代填后还是登录页 → 说明没成功、别反复试（定时任务另发 Home 提醒“密码可能改了”）；两步登录（只有用户名框）→ 旧提示；
#       login_fields 规则：恰好一个密码框 + 它前面最近的文本类输入框。
# 3) listing 带 signed_in_at / expired_at（ISO 带时区）；退出登录路由收起提醒。
# 运行：python tests/smoke_browser_login_expiry.py
import os, sys, asyncio, subprocess, tempfile, json, base64, time
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY=base64.urlsafe_b64encode(os.urandom(32)).decode(),
  DATA_DIR=tmp, TIMEZONE="Asia/Shanghai", CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from sqlalchemy import select
from app import llm, browser_client, browser_sessions as bs, vault, system_alerts
from app.agent import loop
from app.agent.approvals import FormReply
from app.agent.tools import ToolContext, load_builtin
from app.agent.builtin import browser as bt
from app.db import SessionLocal
from app.models import Conversation, HomeCard, ScheduledTask

# ---- 1. 规则 ----
PWD = [{"ref": "1", "tag": "input", "type": "text", "name": "账号"}, {"ref": "2", "tag": "input", "type": "password", "name": "密码"}]
LP = lambda url, text="", els=(): bs.login_page({"url": url, "text": text, "elements": list(els)})
assert LP("https://shop.example.com/", els=PWD)
assert LP("https://login.taobao.com/member/x.htm")
assert LP("https://www.jd.com/user/login?from=x") and LP("https://a.com/signin") and LP("https://a.com/oauth/authorize")
assert LP("https://accounts.google.com/v3/") and LP("https://passport.bilibili.com/")
assert LP("https://a.com/home", "您的登录已过期，请重新登录")
assert LP("https://a.com/home", "Your session has expired.")
assert not LP("https://a.com/author/jack") and not LP("https://a.com/blog/how-to")
assert not LP("https://a.com/home", "文章" * 400 + "请重新登录")  # 只看开头
assert not LP("https://www.taobao.com/", "欢迎回来")

LF = lambda els: bs.login_fields({"elements": els})
assert LF(PWD) == ("1", "2")
assert LF([{"ref": "5", "tag": "input", "type": "search", "name": "搜"}, {"ref": "6", "tag": "input", "type": "email", "name": "邮箱"},
           {"ref": "7", "tag": "a", "type": "", "name": "忘记"}, {"ref": "8", "tag": "input", "type": "password", "name": "密码"}]) == ("6", "8")
assert LF([PWD[0]]) is None and LF([PWD[1]]) is None                     # 两步登录 / 没用户名框
assert LF(PWD + [{"ref": "3", "tag": "input", "type": "password", "name": "再输一次"}]) is None  # 注册 / 改密页
assert LF([]) is None

marks: list = []
async def fake_mark(session, state):
    marks.append((session, state))
    m = meta.setdefault(session, {"signed_in": None, "expired": None})
    if state == "signed_in":
        meta[session] = {"signed_in": time.time(), "expired": None}
    elif m["signed_in"] and not m["expired"]:
        m["expired"] = time.time()
browser_client.login_state = fake_mark
meta: dict = {}

async def rules():
    t = bs.Tab(session="s", url="https://a.com/")
    t.opened(None)
    assert await bs.observe(t, {"url": "https://a.com/login", "elements": PWD}) is None  # 没登录过：普通的要登录
    assert await bs.observe(t, {"url": "https://a.com/back"}) is None                   # 返回离开登录页 ≠ 登录成功
    assert await bs.observe(t, {"url": "https://a.com/home"}, auth=True) == "signed_in"
    assert marks[-1] == ("s", "signed_in") and t.signed_in
    assert await bs.observe(t, {"url": "https://a.com/login"}) == "expired" and marks[-1] == ("s", "expired")
    assert await bs.observe(t, {"url": "https://a.com/login"}) is None  # 每次打开只提醒一次
    t.opened({"signed_in": 1, "expired": 2})
    n = len(marks)
    assert await bs.observe(t, {"url": "https://a.com/login"}) == "expired" and len(marks) == n  # 已标过期：再提醒，不再标
    marks.clear(); meta.clear()
asyncio.run(rules())
print("ok: rules")

# ---- 2. 模拟模型 + 假浏览器 ----
pages: dict = {}  # 会话 → 下一张快照（按路径）
async def fake_snapshot(session, method, path, body=None):
    site = pages[session]
    snap = dict(site.get(path) or site["default"])
    if path == "/goto":
        snap["restored"] = True
        snap["login"] = dict(meta.get(session) or {"signed_in": None, "expired": None})
    return snap
browser_client.snapshot_call = fake_snapshot
async def no_downloads(session):
    return []
browser_client.downloads = no_downloads

script: list = []
model_saw: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    model_saw.append(list(messages))  # 拷一份：loop 之后会把旧快照换成占位
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

def tool_out(i=-1):
    return [m for m in model_saw[-1] if m.get("role") == "tool"][i]["content"]

async def run(cid=None, task_id=None, ask=None, *steps):
    script.extend(steps)
    async with SessionLocal() as db:
        if cid and not await db.get(Conversation, cid):
            db.add(Conversation(id=cid, title="t")); await db.commit()
        kw = {"ask": ask} if ask else {}
        ctx = ToolContext(db=db, conversation_id=cid, task_id=task_id, **kw)
        return [e async for e in loop.run("sys", [{"role": "user", "content": "看看订单"}], ctx)]

def answer(reply):
    async def ask(fid, form):
        return reply
    return ask

LOGIN = {"title": "登录", "url": "https://login.taobao.com/member/login.jhtml", "elements": PWD, "text": "密码登录"}
HOME = {"title": "我的淘宝", "url": "https://i.taobao.com/my_taobao.htm", "elements": [{"ref": "9", "tag": "a", "type": "", "name": "已买到的宝贝"}], "text": "欢迎回来"}

async def turns():
    # a. 聊天、登录过、保险箱没有 → 过期提醒 + 登录卡；填完 → signed_in
    meta["taobao-com"] = {"signed_in": time.time() - 86400 * 9, "expired": None}
    pages["taobao-com"] = {"default": LOGIN, "/login": HOME}
    await run("c1", None, answer(FormReply({"username": "me", "password": "pw"})),
              ("browser_open", {"url": "https://www.taobao.com/"}),
              ("browser_login", {"user_ref": "1", "pass_ref": "2"}), "好了")
    first = [m for m in model_saw[-2] if m.get("role") == "tool"][0]["content"]  # 最后一次调模型时它已被换成占位（v1.42）
    assert "登录已过期" in [m for m in model_saw[-1] if m.get("role") == "tool"][0]["content"]  # 说明保留
    assert "登录已过期" in first and "browser_login（会在聊天里弹登录卡" in first and "browser_handoff" in first, first
    assert first.index("登录已过期") < first.index("可操作元素"), first
    assert ("taobao-com", "expired") in marks and marks[-1] == ("taobao-com", "signed_in"), marks
    assert meta["taobao-com"]["expired"] is None
    assert "登录已过期" not in tool_out(), tool_out()
    print("ok: chat, no vault → login card → signed in")

    # b. 保险箱有 → 直接重登（不弹卡）
    marks.clear()
    async with SessionLocal() as db:
        db.add(vault.create("jd", "pw", ["jd.com"], kind="login", username="me")); await db.commit()
    meta["jd-com"] = {"signed_in": time.time(), "expired": None}
    pages["jd-com"] = {"default": {**LOGIN, "url": "https://passport.jd.com/new/login.aspx"},
                       "/login": {**HOME, "url": "https://home.jd.com/"}}
    asked = []
    async def never(fid, form):
        asked.append(form); return None
    await run("c2", None, never, ("browser_open", {"url": "https://www.jd.com/"}), "好了")
    first = tool_out(0)
    assert "已用保险箱「jd」自动重新登录" in first and "已买到的宝贝" in first and "密码登录" not in first, first
    assert "pw" not in first.replace("passport", "")  # 密码不进模型
    assert not asked and marks == [("jd-com", "expired"), ("jd-com", "signed_in")], (asked, marks)
    print("ok: vault → direct re-login")

    # c. 定时任务、保险箱没有 → 说明 + 系统提醒（只发一次）；后来聊天里重登 → 收起
    async with SessionLocal() as db:
        t = ScheduledTask(name="查订单", prompt="看淘宝订单", cron="0 8 * * *"); db.add(t); await db.commit()
        tid = t.id
    meta["taobao-com"]["signed_in"] = time.time()
    pages["taobao-com"] = {"default": LOGIN, "/login": HOME}
    for _ in range(2):
        await run(None, tid, None, ("browser_open", {"url": "https://www.taobao.com/"}), "做不了")
        out = tool_out(0)
        assert "定时任务" in out and "Home 上放了一张提醒" in out, out
    async with SessionLocal() as db:
        cards = (await db.scalars(select(HomeCard).where(HomeCard.alert_subject == "browser:taobao-com"))).all()
        assert len(cards) == 1, cards
        c = cards[0]
        assert c.title == "taobao.com 的登录过期了" and c.target == "tasks" and c.task_id == tid and c.action_prompt and not c.dismissed, c
    await run("c3", None, answer(FormReply({"username": "me", "password": "pw"})),
              ("browser_open", {"url": "https://www.taobao.com/"}), ("browser_login", {"user_ref": "1", "pass_ref": "2"}), "好")
    async with SessionLocal() as db:
        assert (await db.get(HomeCard, c.id)).dismissed
        assert await system_alerts.active(db, "browser:taobao-com") == []
    print("ok: task → alert once → cleared on re-login")

    # d. 中途过期：打开正常，点击后跳登录页
    meta["weibo-com"] = {"signed_in": time.time(), "expired": None}
    pages["weibo-com"] = {"default": {**HOME, "url": "https://weibo.com/u/1"},
                          "/act": {**LOGIN, "url": "https://passport.weibo.com/sso/signin"}}
    await run("c4", None, answer(None), ("browser_open", {"url": "https://weibo.com/"}),
              ("browser_click", {"ref": "9"}), "嗯")
    assert "登录已过期" not in tool_out(0) and "登录已过期" in tool_out(1), (tool_out(0), tool_out(1))
    print("ok: mid-task expiry")

    # e. 从没登录过：不提醒；登录成功 → 记 signed_in
    marks.clear()
    pages["zhihu-com"] = {"default": {**LOGIN, "url": "https://www.zhihu.com/signin"}, "/login": {**HOME, "url": "https://www.zhihu.com/"}}
    await run("c5", None, answer(FormReply({"username": "me", "password": "pw"})),
              ("browser_open", {"url": "https://www.zhihu.com/"}), ("browser_login", {"user_ref": "1", "pass_ref": "2"}), "好")
    assert "登录已过期" not in tool_out(0) and marks == [("zhihu-com", "signed_in")], marks
    print("ok: first login marked")

    # f1. 自动代填后还是登录页（密码改了）→ 说明 + 别反复试；聊天里 → 不发提醒
    marks.clear()
    async with SessionLocal() as db:
        db.add(vault.create("douban", "old", ["douban.com"], kind="login", username="me")); await db.commit()
    meta["douban-com"] = {"signed_in": time.time(), "expired": None}
    DLOGIN = {**LOGIN, "url": "https://accounts.douban.com/passport/login"}
    pages["douban-com"] = {"default": DLOGIN, "/login": {**DLOGIN, "text": "密码错误"}}
    await run("c6", None, never, ("browser_open", {"url": "https://www.douban.com/"}), "嗯")
    out = tool_out(0)
    assert "自动代填过一次，但还停在登录页" in out and "别用同一份密码反复试" in out and "browser_code" in out, out
    assert marks == [("douban-com", "expired")], marks
    # f2. 同样的情况在定时任务里 → Home 提醒（写明密码可能改了）
    async with SessionLocal() as db:
        t = ScheduledTask(name="豆瓣", prompt="看豆瓣", cron="0 9 * * *"); db.add(t); await db.commit()
        tid2 = t.id
    await run(None, tid2, None, ("browser_open", {"url": "https://www.douban.com/"}), "做不了")
    assert "定时任务" in tool_out(0) and "Home 上放了一张提醒" in tool_out(0), tool_out(0)
    async with SessionLocal() as db:
        cards = (await db.scalars(select(HomeCard).where(HomeCard.alert_subject == "browser:douban-com"))).all()
        assert len(cards) == 1 and "密码可能改了" in json.dumps(cards[0].blocks, ensure_ascii=False), [c.blocks for c in cards]
    # f3. 两步登录（只有用户名框）→ 不自动填，旧提示让模型自己 browser_login
    meta["qq-com"] = {"signed_in": time.time(), "expired": None}
    pages["qq-com"] = {"default": {**LOGIN, "url": "https://ssl.qq.com/login", "elements": [PWD[0]]}}
    calls = []
    real = browser_client.snapshot_call
    async def spy(session, method, path, body=None):
        calls.append(path); return await real(session, method, path, body)
    browser_client.snapshot_call = spy
    await run("c7", None, never, ("browser_open", {"url": "https://www.qq.com/"}), "嗯")
    browser_client.snapshot_call = real
    assert "/login" not in calls and "保险箱里有这个网站的登录" not in tool_out(0) and "登录已过期" in tool_out(0), (calls, tool_out(0))
    # f4. 第一次要登录（从没登录过）+ 保险箱有 → 也自动登录；判不准框 → 提示用 browser_login 别让用户自己登
    marks.clear()
    async with SessionLocal() as db:
        db.add(vault.create("shop", "pw", ["shop.example.com"], kind="login", username="me")); await db.commit()
    pages["example-com"] = {"default": {**LOGIN, "url": "https://shop.example.com/account/login"},
                                 "/login": {**HOME, "url": "https://shop.example.com/orders"}}
    await run("c8", None, never, ("browser_open", {"url": "https://shop.example.com/orders"}), "好")
    assert "要登录，已用保险箱「shop」自动登录" in tool_out(0) and marks == [("example-com", "signed_in")], (tool_out(0), marks)
    meta.pop("example-com", None)  # 当作从没登录过
    pages["example-com"] = {"default": {**LOGIN, "url": "https://shop.example.com/account/login", "elements": [PWD[1]]}}
    await run("c9", None, never, ("browser_open", {"url": "https://shop.example.com/orders"}), "好")
    assert "保险箱里有这个网站的登录「shop」：用 browser_login" in tool_out(0), tool_out(0)
    print("ok: auto login (expired success / wrong password / unattended alert / two-step skipped / first-time)")
asyncio.run(turns())

# ---- 3. listing + 退出登录收起提醒 ----
async def tail():
    async def fake_sessions():
        return {"sessions": [{"name": "taobao-com", "saved": True, "signed_in": 1760000000, "expired": 1760086400,
                              "domains": ["taobao.com"]}, {"name": "x", "saved": True}], "max_open": 1}
    browser_client.sessions = fake_sessions
    data = await bs.listing()
    s0, s1 = data["sessions"]
    assert s0["signed_in_at"].endswith("+00:00") and s0["expired_at"] and s1["expired_at"] is None, data
    async with SessionLocal() as db:
        await system_alerts.post(db, subject="browser:taobao-com", once="expired", title="t", text="x", open="vault")
        await db.commit()
    async def fake_close(session, forget=False):
        pass
    browser_client.close = fake_close
    from app.routes import browser as rb
    async with SessionLocal() as db:
        await rb.sign_out("taobao-com", db)
    async with SessionLocal() as db:
        assert await system_alerts.active(db, "browser:taobao-com") == []
        assert all(c.dismissed for c in (await db.scalars(select(HomeCard).where(HomeCard.alert_subject == "browser:taobao-com"))).all())
asyncio.run(tail())
print("ok: listing + sign out")
print("ALL OK")
