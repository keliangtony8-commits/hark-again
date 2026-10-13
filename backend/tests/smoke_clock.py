# 冒烟：v1.99 大脑 (ao) 钟表工具——app/clock.py + get_current_time / convert_time / resolve_relative_date。模拟模型，无迁移（只读）。
# - 时区：IANA 大小写不敏感、中文城市、缩写、UTC+N；拼错给最像的；
# - 换算：按那天的夏令时（纽约 7 月 -4、1 月 -5）、跨天标“前一天/第二天”、春季跳过的钟点报错、秋季出现两次注明；
# - 相对日期：明天/后天/N 天后/N 周前/下周三/这周日/上周一/N 个月后（月底钳）/in N days；模型数错一天 → 以写法为准并注明；
#   认不出的写法按模型天数；天数太大、不是整数报错；
# - 一轮对话：模型并行调三个钟表工具 → 时间线摘要换成结果（“下周三 → 10-21 周三”）、结果交回模型；
#   计划模式、子助手都能用；系统提示里有规则、“现在是”带中文星期。
# 运行：python tests/smoke_clock.py
import os, sys, asyncio, subprocess, tempfile, json
from datetime import date, datetime, timezone
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from app import clock, llm, plan_mode
from app.agent import runner, subagent
from app.agent.tools import REGISTRY, load_builtin
from app.blocks import text_to_blocks
from app.config import settings
from app.db import SessionLocal
from app.models import Conversation, Message

SH = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 13, 8, 50, tzinfo=SH)  # 周二

def err(fn, *a, **k):
    try:
        fn(*a, **k)
    except clock.ClockError as e:
        return str(e)
    raise AssertionError(f"应报错：{a}")

# --- 时区 ---
assert clock.zone_name(clock.zone("asia/tokyo")) == "Asia/Tokyo"
assert clock.zone_name(clock.zone("纽约")) == "America/New_York"
assert clock.zone_name(clock.zone("东京时间")) == "Asia/Tokyo"
assert clock.zone_name(clock.zone("pst")) == "America/Los_Angeles"
assert clock.zone_name(clock.zone("")) == "Asia/Shanghai"
assert clock.zone_name(clock.zone("America/New York")) == "America/New_York"
assert clock.zone_name(clock.zone("UTC+5:30")) == "UTC+05:30"
assert "UTC-12" in err(clock.zone, "UTC+15")
e = err(clock.zone, "Asia/Shangai")
assert "Asia/Shanghai" in e and "可能是" in e, e
assert "IANA" in err(clock.zone, "火星")

# --- 现在 ---
t, d = clock.now_text("", now=NOW)
assert t == "现在是 2026-10-13 周二 08:50:00（Asia/Shanghai，UTC+08:00）。", t
assert d == "10-13 周二 08:50 Asia/Shanghai"
t, _ = clock.now_text("纽约", now=NOW)
assert "2026-10-12 周一 20:50:00（America/New_York，UTC-04:00，夏令时）" in t, t

# --- 换算 ---
c = clock.convert("09:00", "Asia/Shanghai", "America/New_York", "2026-07-15")
assert c.text.startswith("2026-07-15 周三 09:00（Asia/Shanghai，UTC+08:00） = 2026-07-14 周二 21:00（America/New_York，UTC-04:00）（前一天）"), c.text
assert c.detail == "09:00 Asia/Shanghai → 21:00 America/New_York（前一天）"
c = clock.convert("09:00", "上海", "纽约", "2026-01-15")
assert "20:00（America/New_York，UTC-05:00）" in c.text  # 冬令时差 13 小时
c = clock.convert("22:30", "伦敦", "东京", "2026-03-10")
assert "2026-03-11 周三 07:30（Asia/Tokyo" in c.text and "（第二天）" in c.text, c.text
assert "不存在" in err(clock.convert, "02:30", "America/New_York", "UTC", "2026-03-08")
c = clock.convert("01:30", "America/New_York", "UTC", "2026-11-01")
assert "出现两次" in c.text and "05:30（UTC" in c.text, c.text  # 第一次 = EDT
c = clock.convert("9:05", "UTC", "上海", None, now=NOW)
assert "2026-10-13 周二 17:05" in c.text and "没给日期" in c.text, c.text
assert "HH:MM" in err(clock.convert, "9点", "UTC", "上海")
assert "HH:MM" in err(clock.convert, "24:00", "UTC", "上海")
assert "YYYY-MM-DD" in err(clock.convert, "09:00", "UTC", "上海", "10/13")

# --- 相对日期 ---
r = lambda e, n: clock.resolve(e, n, now=NOW)
x = r("明天", 1)
assert x.date == date(2026, 10, 14) and not x.corrected
assert x.text == "「明天」= 2026-10-14 周三（今天 2026-10-13 周二，+1 天；Asia/Shanghai）。", x.text
assert x.detail == "明天 → 10-14 周三"
assert r("后天", 2).date == date(2026, 10, 15) and r("大前天", -3).date == date(2026, 10, 10)
assert r("10天后", 10).date == date(2026, 10, 23)
assert r("十五天以后", 15).date == date(2026, 10, 28)
assert r("两周前", -14).date == date(2026, 9, 29)
assert r("in 10 days", 10).date == date(2026, 10, 23)
assert r("3 days ago", -3).date == date(2026, 10, 10)
assert r("下周三", 8).date == date(2026, 10, 21) and r("下周三", 8).detail == "下周三 → 10-21 周三"
assert r("下星期一", 6).date == date(2026, 10, 19)
assert r("这周日", 5).date == date(2026, 10, 18)
assert r("本周一", -1).date == date(2026, 10, 12)
assert r("上周五", -4).date == date(2026, 10, 9)
assert r("下下周二", 14).date == date(2026, 10, 27)
x = r("下周三", 7)  # 模型数错一天
assert x.corrected and x.date == date(2026, 10, 21) and "对不上" in x.text and "+8 天" in x.text, x.text
x = r("明天", 2)
assert x.corrected and x.date == date(2026, 10, 14)
x = r("1个月后", 30)
assert x.date == date(2026, 11, 13) and x.corrected  # 日历月 31 天
jan31 = datetime(2026, 1, 31, 12, tzinfo=SH)
assert clock.resolve("一个月后", 28, now=jan31).date == date(2026, 2, 28)  # 月底钳
assert clock.resolve("明年今天", 365, now=NOW).date == date(2027, 10, 13)  # 认不出 → 按天数
x = r("周三", 1)  # 只说周三：不替模型选这周还是下周
assert x.date == date(2026, 10, 14) and not x.corrected
x = r("deadline", 3)
assert "认不出" in x.text and x.date == date(2026, 10, 16)
assert "太远" in err(r, "很久以后", 99999)
assert "整数" in err(r, "明天", "1")
assert r("tomorrow", 1).date == date(2026, 10, 14)
x = clock.resolve("明天", 1, "纽约", now=NOW)  # 纽约还是 12 日
assert x.date == date(2026, 10, 13) and "America/New_York" in x.text

# --- 一轮对话 ---
load_builtin()
for n in ("get_current_time", "convert_time", "resolve_relative_date"):
    assert n in REGISTRY and REGISTRY[n].parallel and n in plan_mode.READ_TOOLS and n in subagent.CHILD_TOOLS
assert "resolve_relative_date" in settings.system_prompt and "convert_time" in settings.system_prompt

script: list = []
tool_msgs: list[dict] = []
seen_system: list[str] = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    messages = [dict(m) for m in messages]
    seen_system.append(messages[0]["content"])
    tool_msgs.extend(m for m in messages if m["role"] == "tool" and m not in tool_msgs)
    step = script.pop(0)
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"c{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create

async def turn():
    today = datetime.now(SH).date()
    nxt_wed = today + __import__("datetime").timedelta(days=7 - today.weekday() + 2)
    script.extend([[("get_current_time", {}),
                    ("resolve_relative_date", {"expression": "下周三", "days_from_today": (nxt_wed - today).days - 1}),
                    ("convert_time", {"time": "21:00", "source_timezone": "纽约", "target_timezone": "Asia/Shanghai", "date": "2026-07-14"}),
                    ("convert_time", {"time": "9点", "source_timezone": "UTC", "target_timezone": "上海"})],
                   "北京是周四早上 9 点。"])
    async with SessionLocal() as db:
        conv = Conversation(id="c1", title="t"); db.add(conv); await db.commit()
        db.add(Message(conversation_id="c1", role="user", blocks=text_to_blocks("下周三纽约晚上九点开会，北京是几点？")))
        await db.commit()
        reply = await runner.run_turn(db, conv)
        return reply, nxt_wed
reply, nxt_wed = asyncio.run(turn())
steps = {s["tool"]: s for s in reply.steps if s["tool"] != "convert_time"}
conv_steps = [s for s in reply.steps if s["tool"] == "convert_time"]
assert steps["get_current_time"]["title"] == "看时间" and steps["get_current_time"]["state"] == "done"
assert steps["get_current_time"]["detail"].endswith("Asia/Shanghai"), steps
rd = steps["resolve_relative_date"]
assert rd["detail"] == f"下周三 → {nxt_wed:%m-%d} 周三" and rd["state"] == "done", rd
assert conv_steps[0]["detail"] == "21:00 America/New_York → 09:00 Asia/Shanghai（第二天）", conv_steps
assert conv_steps[1]["state"] == "error" and "HH:MM" in conv_steps[1]["note"], conv_steps[1]
contents = " | ".join(m["content"] for m in tool_msgs)
assert "对不上" in contents and nxt_wed.isoformat() in contents and "没算成" in contents, contents
assert "现在是 " in seen_system[0] and " 周" in seen_system[0].split("现在是 ", 1)[1][:20]

print("smoke_clock OK")
