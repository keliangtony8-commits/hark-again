# 冒烟：v1.29 浏览器接管交还（browser_handoff）。
# 1) 规则：handoff_reason 压成一行、截长、空 → 通用说法；BrowserBlock.handoff 校验；
# 2) 模拟模型 + 假浏览器：打开淘宝 → browser_handoff → 同一张画面卡原地出现 handoff pending（不插第二张）→
#    用户交还（form.reply 走 approvals.resolve_form，values={}）→ 卡上 done、模型拿到交还后的新快照、时间线一步 done 带 reason；
#    用户点“做不了”（values=None）→ cancelled、模型被告知别再弹、时间线 error；
#    超时 → expired；定时任务（ask=nobody）→ 不推卡、直接说明；没打开 → 提示；
# 3) 停止：partial() 把还在等的接管条标 expired；
# 4) ws 真实的 _ask（等 wait_form、fields=[]）能被 resolve_form 唤醒。
# 运行：python tests/smoke_browser_handoff.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import llm, browser_client, blocks
from app.agent import loop, approvals
from app.agent.loop import MessageBuilder, BlockStart, BlockUpdate, ToolStatus
from app.agent.tools import ToolContext, load_builtin
from app.agent.builtin import browser as bt
from app.db import SessionLocal
from app.models import Conversation

# ---- 1. 规则 ----
assert bt.handoff_reason("  拖动滑块\n完成验证 ") == "拖动滑块 完成验证"
assert bt.handoff_reason("") == "需要你在画面里操作一下"
long = bt.handoff_reason("字" * 100)
assert len(long) == bt.REASON_MAX and long.endswith("…")
b = blocks.BrowserBlock(session="taobao-com", handoff={"id": "h", "reason": "扫码"})
assert b.handoff.state == "pending"
try:
    blocks.BrowserBlock(session="x", handoff={"id": "h", "reason": "r", "state": "weird"}); raise SystemExit("bad state accepted")
except ValueError:
    pass
print("ok: rules")

# ---- 2. 模拟模型 ----
calls: list = []
async def fake_snapshot(session, method, path, body=None):
    calls.append((session, method, path))
    url = body["url"] if body and "url" in body else "https://www.taobao.com/after"
    return {"title": "已登录" if path == "/snapshot" else "登录页", "url": url, "elements": [], "text": "欢迎回来" if path == "/snapshot" else "请扫码"}
browser_client.snapshot_call = fake_snapshot

script: list = []
model_saw: list[str] = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    model_saw.append(json.dumps(messages, ensure_ascii=False))
    step = script.pop(0)
    async def gen():
        if isinstance(step, tuple):
            name, args = step
            yield chunk(tool=[NS(index=0, id=f"c{len(script)}", function=NS(name=name, arguments=json.dumps(args, ensure_ascii=False)))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()

def asker(answer, seen):
    """模拟用户：卡片推出来后（看到 pending 的条）再答复。answer = {} 交还 / None 做不了。"""
    async def ask(fid, form):
        seen.append((fid, form))
        await asyncio.sleep(0.05)
        return approvals.FormReply({}) if answer is not None else None
    return ask

async def run(cid, ask, *steps):
    script.extend(steps)
    async with SessionLocal() as db:
        if not await db.get(Conversation, cid):
            db.add(Conversation(id=cid, title="t")); await db.commit()
        kw = {"ask": ask} if ask else {}
        ctx = ToolContext(db=db, conversation_id=cid, **kw)
        return [e async for e in loop.run("sys", [{"role": "user", "content": "登录淘宝"}], ctx)]

def browser_events(evs):
    return [e for e in evs if isinstance(e, (BlockStart, BlockUpdate)) and e.block["type"] == "browser"]

async def turns():
    seen: list = []
    evs = await run("h1", asker({}, seen), ("browser_open", {"url": "https://www.taobao.com/"}),
                    ("browser_handoff", {"reason": "用淘宝 App 扫码登录"}), "登好了")
    bev = browser_events(evs)
    assert sum(isinstance(e, BlockStart) for e in bev) == 1, bev  # 同一张卡原地更新
    pend = [e.block for e in bev if (e.block.get("handoff") or {}).get("state") == "pending"]
    assert pend and pend[0]["handoff"]["reason"] == "用淘宝 App 扫码登录" and pend[0]["session"] == "taobao-com", bev
    assert seen and seen[0][0] == pend[0]["handoff"]["id"] and seen[0][1]["fields"] == []
    final = evs[-1].blocks
    assert [x["type"] for x in final] == ["browser", "text"], final
    assert final[0]["handoff"]["state"] == "done" and "live" not in final[0], final[0]
    blocks.BrowserBlock(**final[0])  # 落库形状合法
    tool_msg = json.loads(model_saw[-1])[-1]["content"]
    assert "交还给你了" in tool_msg and "欢迎回来" in tool_msg, tool_msg
    assert calls[-1] == ("taobao-com", "GET", "/snapshot")
    steps = [e.step for e in evs if isinstance(e, ToolStatus) and e.name == "browser_handoff" and e.state == "done"]
    assert steps and steps[-1]["detail"] == "用淘宝 App 扫码登录" and steps[-1]["state"] == "done", steps

    # 做不了 → cancelled，模型被告知别再弹；时间线 error
    seen = []
    evs = await run("h2", asker(None, seen), ("browser_open", {"url": "https://www.jd.com/"}),
                    ("browser_handoff", {"reason": "拖动滑块"}), "好")
    final = evs[-1].blocks
    assert final[0]["handoff"]["state"] == "cancelled", final
    tool_msg = json.loads(model_saw[-1])[-1]["content"]
    assert "别再弹接管" in tool_msg and "点了做不了" in tool_msg, tool_msg
    errs = [e.step for e in evs if isinstance(e, ToolStatus) and e.name == "browser_handoff" and e.state == "error"]
    assert errs and errs[-1]["note"] == "用户点了做不了", errs

    # 超时 → expired
    old = approvals.TIMEOUT_SECONDS
    approvals.TIMEOUT_SECONDS = 0.2
    async def slow(fid, form):
        await asyncio.sleep(0.25); return None
    evs = await run("h3", slow, ("browser_open", {"url": "https://www.jd.com/"}), ("browser_handoff", {"reason": "x"}), "好")
    approvals.TIMEOUT_SECONDS = old
    assert evs[-1].blocks[0]["handoff"]["state"] == "expired"
    assert "等了 10 分钟没人交还" in json.loads(model_saw[-1])[-1]["content"]

    # 定时任务（默认 ask=nobody）：不推接管条
    evs = await run("h4", None, ("browser_open", {"url": "https://www.jd.com/"}), ("browser_handoff", {"reason": "x"}), "好")
    assert all("handoff" not in e.block for e in browser_events(evs))
    assert "定时任务在跑" in json.loads(model_saw[-1])[-1]["content"]

    # 没打开过 → 提示先打开
    evs = await run("h5", asker({}, []), ("browser_handoff", {"reason": "x"}), "好")
    assert "还没打开浏览器" in json.loads(model_saw[-1])[-1]["content"]
    assert not browser_events(evs)
asyncio.run(turns())
print("ok: model turns")

# ---- 3. 停止 ----
mb = MessageBuilder()
mb.add({"type": "browser", "session": "s", "live": True, "handoff": {"id": "h", "reason": "r", "state": "pending"}})
mb.add({"type": "browser", "session": "t", "handoff": {"id": "g", "reason": "r", "state": "done"}})
out = mb.partial()
assert out[0] == {"type": "browser", "session": "s", "handoff": {"id": "h", "reason": "r", "state": "expired"}}, out
assert out[1]["handoff"]["state"] == "done"
print("ok: partial")

# ---- 4. ws 的 _ask 能被 form.reply 唤醒 ----
from app.routes import ws
async def wake():
    t = asyncio.create_task(ws._ask("hid", {"type": "handoff", "fields": []}))
    await asyncio.sleep(0.01)
    assert approvals.resolve_form("hid", {})
    r = await t
    assert r is not None and r.values == {}
    t = asyncio.create_task(ws._ask("hid2", {"type": "handoff", "fields": []}))
    await asyncio.sleep(0.01)
    assert approvals.resolve_form("hid2", None)
    assert await t is None
asyncio.run(wake())
print("ok: ws wake")
print("ALL OK")
