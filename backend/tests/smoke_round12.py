# 冒烟：v2.60 E2E 第十二轮两处修复（无迁移）。
# B30 web_fetch 读到登录页：是不是登录页只问 browser_sessions.login_page（密码框 / 登录网址 / 过期字样），
#     是 → 结果开头指向 browser_open（保险箱有这个网站的账号就说会自动登录，没有就说浏览器会请用户填），detail 带“登录页”；
#     登录页不进缓存；普通页不加提示；schedule_task 说明要求 prompt 保留“登录后看 / 用浏览器 / 哪个账号”。
# B31 定时任务时间带“今天 / 明天 / 周X”（clock.near_day），模型不再把今天 08:00 说成“明天”。
# 运行：python tests/smoke_round12.py
import os, sys, asyncio, tempfile, subprocess
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace as NS
from cryptography.fernet import Fernet
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY=Fernet.generate_key().decode(), DATA_DIR=tmp,
  TIMEZONE="Asia/Shanghai")
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

import httpx
from app import clock, schedule, vault, web_guard, web_page
from app.agent.builtin import tasks as task_tools
from app.agent.tools import REGISTRY, load_builtin
from app.db import SessionLocal

run = asyncio.run

# ---- B31 near_day ----
d = date(2026, 10, 14)
assert clock.near_day(d, d) == "今天 周三"
assert clock.near_day(d + timedelta(1), d) == "明天 周四"
assert clock.near_day(d + timedelta(2), d) == "后天 周五"
assert clock.near_day(d - timedelta(1), d) == "昨天 周二"
assert clock.near_day(d + timedelta(5), d) == "周一"
now = schedule.local_now()
t = now.replace(hour=23, minute=59, second=0, microsecond=0)
s = task_tools._local(t.astimezone(timezone.utc).replace(tzinfo=None))  # SQLite 读回无时区 UTC
assert s.startswith(t.strftime("%Y-%m-%d 23:59")) and "（今天 " in s, s
assert "（明天 " in task_tools._local(t + timedelta(days=1)), task_tools._local(t + timedelta(days=1))
assert task_tools._local(None) == "—"

load_builtin()
assert "“登录后看”" in REGISTRY["schedule_task"].description

# ---- B30 web_fetch 登录页 ----
DNS = {"shop.example": ["93.184.216.34"], "news.example": ["1.1.1.1"], "sso.example": ["1.1.1.2"]}
async def fake_resolve(host):
    if host not in DNS:
        raise OSError(-2, "Name or service not known")
    return DNS[host]
web_guard.resolve = fake_resolve
LOGIN = b"<html><head><title>Login</title></head><body><h1>Please sign in</h1><form><input name=u>" \
        b"<input name=p type='password'><button>Go</button></form><p>Welcome back to our shop, sign in to see orders.</p></body></html>"
ARTICLE = ("<html><head><title>News</title></head><body><article><h1>Library hours</h1>" + "<p>The library opens late on weekends for students.</p>" * 20
           + "</article></body></html>").encode()
hits = []
def handler(req: httpx.Request):
    hits.append(str(req.url))
    if req.url.path == "/orders":
        return httpx.Response(302, headers={"Location": "https://shop.example/account/login"})
    if req.url.host == "news.example":
        return httpx.Response(200, content=ARTICLE, headers={"content-type": "text/html"})
    return httpx.Response(200, content=LOGIN, headers={"content-type": "text/html"})
transport = httpx.MockTransport(handler)
real_fetch = web_page.fetch
async def fetch(url, max_age=None, **kw):
    return await real_fetch(url, max_age=max_age, transport=transport, **kw)
web_page.fetch = fetch

p = run(real_fetch("https://shop.example/orders", transport=transport))
assert p.password and p.url == "https://shop.example/account/login", p
n = len(hits)
run(real_fetch("https://shop.example/orders", transport=transport))
assert len(hits) > n, "登录页不该进缓存"

wf = REGISTRY["web_fetch"]
r = run(wf.run(NS(db=None), url="https://shop.example/orders"))
assert r.content.startswith("⚠ 这里读到的是登录页（https://shop.example/account/login）"), r.content[:200]
assert "browser_open 打开 https://shop.example/orders" in r.content and "请用户自己填账号" in r.content
assert "登录页" in r.detail and not r.failed

async def add_login():
    async with SessionLocal() as db:
        db.add(vault.create("小店账号", "pw-1", ["shop.example"], kind="login", username="me"))
        await db.commit()
run(add_login())
r = run(wf.run(NS(db=None), url="https://shop.example/orders"))
assert "保险箱里有这个网站的账号（小店账号）" in r.content and "自动登录" in r.content, r.content[:300]
assert "pw-1" not in r.content

r = run(wf.run(NS(db=None), url="https://news.example/today"))
assert "⚠" not in r.content and "登录页" not in r.detail and "library" in r.content.lower(), r.content[:200]
# 登录主机（sso.）+ 没有密码框（如扫码登录）也算
r = run(wf.run(NS(db=None), url="https://sso.example/qr"))
assert r.content.startswith("⚠ 这里读到的是登录页"), r.content[:120]
print("smoke_round12 ok")

# ---- B32 编号写成 "[3]"：tool_args 按 pattern=DIGITS 取出数字（在审批之前，风险判断看得到真名字）----
from app.agent import tool_args
click = REGISTRY["browser_click"].parameters
for raw, want in [("[3]", "3"), ("#12", "12"), ("ref=7", "7"), (" 3 ", "3"), ("【5】", "5"), ("编号4", "4"), ("REF: 9", "9")]:
    c = tool_args.check(click, {"ref": raw})
    assert not c.error and c.args["ref"] == want, (raw, c)
for raw in ["3,4", "a3", "[3] 保温杯"]:
    assert tool_args.check(click, {"ref": raw}).args["ref"] == raw, raw  # 不确定的不动
assert tool_args.check(REGISTRY["browser_login"].parameters, {"user_ref": "[1]", "pass_ref": "[2]"}).args == {"user_ref": "1", "pass_ref": "2"}
assert tool_args.check(REGISTRY["browser_press"].parameters, {"key": "Enter", "ref": ""}).args["ref"] == ""
assert tool_args.check(REGISTRY["browser_type"].parameters, {"ref": "[3]", "text": "[3]"}).args["text"] == "[3]"  # 只动编号
print("smoke_round12 B32 ok")
