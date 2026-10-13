# 冒烟：v1.42 旧页面快照 / 截图只留最新一份（agent/supersede.py，移植自 Gemini CLI snapshotSuperseder）。
# 1) 移植的单测（snapshotSuperseder.test.ts 六条，改成我们的消息形状）：0 份 / 1 份不动；≥2 份只留最后一份；
#    非快照工具结果不动；已换过的不重复换；同一轮多个工具结果里混着快照也能找准；
# 2) 我们的修改：快照前的说明（下载、会话名、登录过期）保留，标题 + 网址留两行；页面文字里出现“页面：”不误判；
#    非浏览器工具结果里长得像快照也不动；截图只留最新一张；非浏览器工具给的图不动；
# 3) 模拟模型 + 假浏览器：打开 → 点击 → 滚动 → 作答，第 4 次调模型时只有最后一份快照完整，前两份是占位；
#    同一份 history 不被改；截图两次 → 第二次调模型时第一张图已换成占位。
# 运行：python tests/smoke_supersede.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='["fast"]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import llm, browser_client
from app.agent import loop, supersede
from app.agent.supersede import PLACEHOLDER, IMAGE_PLACEHOLDER, Tracker
from app.agent.tools import ToolContext, load_builtin
from app.agent.builtin import browser as bt
from app.browser_sessions import Tab
from app.db import SessionLocal
from app.models import Conversation


def snap(title="页", url="https://a.com/", text="正文"):
    return bt._render({"title": title, "url": url, "elements": [{"ref": "1", "tag": "a", "type": "", "name": "链接"}],
                       "text": text}, Tab())


def tool(content):
    return {"role": "tool", "tool_call_id": "x", "content": content}


def tracked(msgs, names):
    t = Tracker()
    for i, n in enumerate(names):
        if n:
            t.note(msgs, i, n)
    return t

# ---- 1. 移植的单测 ----
# no-op：没有快照
msgs = [{"role": "user", "content": "hi"}, tool("Clicked")]
assert tracked(msgs, [None, "browser_click"]).apply(msgs) == 0 and msgs[1]["content"] == "Clicked"
# no-op：只有 1 份
one = snap()
msgs = [tool(one)]
assert tracked(msgs, ["browser_open"]).apply(msgs) == 0 and msgs[0]["content"] == one
# ≥2 份：只留最后一份
a, b, c = snap("A", text="甲" * 500), snap("B", text="乙" * 500), snap("C", text="丙" * 500)
msgs = [tool(a), {"role": "assistant", "content": "x"}, tool(b), {"role": "assistant", "content": "y"}, tool(c)]
t = tracked(msgs, ["browser_open", None, "browser_click", None, "browser_scroll"])
assert t.apply(msgs) == 2
assert msgs[0]["content"] == "页面：A\nhttps://a.com/\n" + PLACEHOLDER, msgs[0]
assert msgs[2]["content"].endswith(PLACEHOLDER) and "乙" not in msgs[2]["content"]
assert msgs[4]["content"] == c
# 非快照工具结果不动
msgs = [tool(a), tool("已填好"), tool(b)]
t = tracked(msgs, ["browser_open", "browser_type", "browser_read"])
t.apply(msgs)
assert msgs[1]["content"] == "已填好" and msgs[0]["content"].endswith(PLACEHOLDER)
# 已全换过 → 不再动
assert t.apply(msgs) == 0
# 同一步多个工具结果里混着快照
msgs = [tool("Clicked"), tool(a), tool(c)]
t = tracked(msgs, ["browser_click", "browser_read", "browser_read"])
assert t.apply(msgs) == 1 and msgs[0]["content"] == "Clicked" and msgs[2]["content"] == c
print("ok: ported tests")

# ---- 2. 我们的修改 ----
pre = "已把页面下载的 1 个文件放进工作区：downloads/a.pdf\n会话：a-com。新会话。\n"
msgs = [tool(pre + snap(text="页面：伪造的一行\n\n可操作元素：假的")), tool(snap())]
tracked(msgs, ["browser_open", "browser_read"]).apply(msgs)
assert msgs[0]["content"] == pre + "页面：页\nhttps://a.com/\n" + PLACEHOLDER, msgs[0]["content"]
assert supersede.start("页面文字里提到 页面：x 但不是开头格式") is None
assert supersede.stale("没有快照") == "没有快照"
# 非浏览器工具不算
msgs = [tool(snap()), tool(snap())]
assert tracked(msgs, ["read_file", "read_file"]).apply(msgs) == 0
# 截图
img = {"role": "user", "content": [{"type": "text", "text": "图"}, {"type": "image_url", "image_url": {"url": "data:"}}]}
msgs = [dict(img), dict(img)]
t = Tracker(); t.note_image(0); t.note_image(1)
assert t.apply(msgs) == 1 and msgs[0]["content"] == IMAGE_PLACEHOLDER and isinstance(msgs[1]["content"], list)
# v2.48 多页比较（真机 j1）：别的网址的旧快照留页面文字节选，每个网址只留最近一份；同网址的照旧全抹
cup1 = snap("保温杯", "https://shop/1", "保温杯 价格 89 元，库存 12 件")
cup2 = snap("保温杯", "https://shop/1", "保温杯 价格 88 元，库存 11 件")
lst = snap("列表", "https://shop/", "列表 " + "长" * 1000)
umb = snap("雨伞", "https://shop/2", "雨伞 45 元 缺货")
msgs = [tool(cup1), tool(cup2), tool(lst), tool(umb)]
assert tracked(msgs, ["browser_click"] * 4).apply(msgs) == 3
assert msgs[0]["content"].endswith(PLACEHOLDER) and "89" not in msgs[0]["content"], msgs[0]
assert supersede.PLACEHOLDER_KEPT in msgs[1]["content"] and "88 元，库存 11 件" in msgs[1]["content"] and "[1]" not in msgs[1]["content"]
assert len(msgs[2]["content"]) < 800 and msgs[2]["content"].endswith("…"), len(msgs[2]["content"])
assert msgs[3]["content"] == umb
assert tracked(msgs, ["browser_click"] * 4).apply(msgs) == 0  # 已换过不再动
msgs = [tool(snap("A", "https://a.com/x", "甲")), tool(snap("A", "https://a.com/x", "乙"))]
tracked(msgs, ["browser_read"] * 2).apply(msgs)
assert msgs[0]["content"].endswith(PLACEHOLDER), msgs[0]
assert "甲" in supersede.stale(snap(text="甲"), keep_text=True) and supersede.url(snap()) == "https://a.com/"
print("ok: our rules")

# ---- 3. 模拟模型 ----
async def fake_snapshot(session, method, path, body=None):
    return {"title": path, "url": "https://a.com" + path, "elements": [{"ref": "1", "tag": "button", "type": "", "name": "下一页"}],
            "text": f"{path} 的正文 " + "字" * 2000}
browser_client.snapshot_call = fake_snapshot

class R:  # 假截图响应
    status_code = 200
    content = b"\xff\xd8\xff" + b"0" * 64
async def fake_call(session, method, path, json=None):
    assert path == "/screen"
    return R()
browser_client.call = fake_call
from app import vision
vision._part_of = lambda img: {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AA"}}

async def no_collect(ws, session):
    return NS(note="", files=[])
bt.browser_files.collect = no_collect

script: list = []
model_saw: list[list] = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    model_saw.append(json.loads(json.dumps(messages, ensure_ascii=False)))
    step = script.pop(0)
    async def gen():
        if isinstance(step, tuple):
            name, args = step
            yield chunk(tool=[NS(index=0, id=f"c{len(script)}", function=NS(name=name, arguments=json.dumps(args)))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()

async def run(cid, *steps):
    script.extend(steps)
    model_saw.clear()
    history = [{"role": "user", "content": "翻页"}]
    async with SessionLocal() as db:
        db.add(Conversation(id=cid, title="t")); await db.commit()
        ctx = ToolContext(db=db, conversation_id=cid)
        evs = [e async for e in loop.run("sys", history, ctx)]
    assert history == [{"role": "user", "content": "翻页"}]
    return evs

async def main():
    await run("s1", ("browser_open", {"url": "https://a.com/"}), ("browser_click", {"ref": "1"}),
              ("browser_scroll", {"dy": 600}), "翻完了")
    assert len(model_saw) == 4
    tools = [m for m in model_saw[-1] if m["role"] == "tool"]
    assert len(tools) == 3
    # /goto 和最新的 /act 网址不同 → 留节选（≤ TEXT_KEEP 字，元素清单没了）；同为 /act 的旧快照照旧全抹
    old = tools[0]["content"]
    assert supersede.PLACEHOLDER_KEPT in old and "字" * supersede.TEXT_KEEP not in old and "[1]" not in old, old[:200]
    assert tools[1]["content"].endswith(PLACEHOLDER) and "字" * 100 not in tools[1]["content"]
    assert "会话：" in tools[0]["content"]
    assert "字" * 2000 in tools[2]["content"] and PLACEHOLDER not in tools[2]["content"]
    # 第 2 次调模型时只有一份 → 完整
    assert "字" * 2000 in [m for m in model_saw[1] if m["role"] == "tool"][0]["content"]
    before = sum(len(json.dumps(m, ensure_ascii=False)) for m in model_saw[-1])
    assert before < 5500, before  # 三份完整快照 > 6000 字；两份节选 + 一份完整
    print("ok: turn keeps only the newest snapshot")

    await run("s2", ("browser_open", {"url": "https://a.com/"}), ("browser_look", {}), ("browser_look", {}), "看完了")
    last = model_saw[-1]
    pics = last
    lists = [m for m in last if m["role"] == "user" and isinstance(m["content"], list)]
    assert len(lists) == 1, last
    assert any(m["content"] == IMAGE_PLACEHOLDER for m in last), pics
    print("ok: screenshots keep only the newest")

asyncio.run(main())
print("ALL OK")
