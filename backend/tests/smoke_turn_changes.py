# 冒烟：v1.68 一轮回复的净改动卡 + 整轮撤销（app/turn_changes.py，移植 Codex turn_diff_tracker 的基线规则，
# 嫁接 Gemini 检查点回退）。模拟模型，不用沙盒。运行：python tests/smoke_turn_changes.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', AUTO_TITLE="false")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from pathlib import Path
from app import llm, turn_changes as T, workspaces
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.blocks import blocks_to_text
from app.db import SessionLocal
from app.models import Conversation, Message
from app.storage import HIDDEN_DIRS, project_dir

assert ".turns" in HIDDEN_DIRS

# ---- 1. 规则（Codex turn_diff_tracker_tests 的语义，换成我们的落盘基线）----
ws = workspaces.PERSONAL
wr = project_dir(ws)
t = T.Tracker()
a = wr / "a.txt"; a.write_text("one\ntwo\n")
t.before(wr, a); a.write_text("one\nTWO\n")
t.before(wr, a); a.write_text("one\nTWO\nthree\n")          # 第二次碰：基线不变（first touch）
n = wr / "sub/new.md"
t.before(wr, n); n.parent.mkdir(); n.write_text("hi\n")      # accumulates_add_then_update_as_single_add
n.write_text("hi\nthere\n")
same = wr / "same.txt"; same.write_text("x\n")
t.before(wr, same); same.write_text("y\n"); same.write_text("x\n")  # 改了又改回去 → 不出
card = T.finish(t, ws)
assert card["type"] == "changes" and card["token"], card
paths = [f["path"] for f in card["files"]]
assert paths == ["a.txt", "sub/new.md"], paths
fa, fn = card["files"]
assert fa["added"] == 2 and fa["removed"] == 1 and "-two" in fa["diff"] and "+three" in fa["diff"], fa
assert fn["created"] and fn["added"] == 2, fn
assert T.finish(T.Tracker(), ws) is None and T.finish(None, ws) is None
line = T.history_text(card)
assert "a.txt（+2 −1）" in line and "sub/new.md（新建 +2 −0）" in line, line
# 冲突：之后又被改过 → 一个都不动
a.write_text("user edit\n")
assert T.conflicts(ws, card["token"]) == ["a.txt"]
try:
    T.undo(ws, card["token"]); raise AssertionError
except T.Conflict as e:
    assert e.paths == ["a.txt"] and n.exists()
a.write_text("one\nTWO\nthree\n")
assert T.undo(ws, card["token"]) == ["a.txt", "sub/new.md"]
assert a.read_text() == "one\ntwo\n" and not n.exists()
try:
    T.undo(ws, card["token"]); raise AssertionError
except T.UndoError as e:
    assert not isinstance(e, T.Conflict) and "过期" in str(e)
for bad in ("", "../x", "a/b"):
    try:
        T.undo(ws, bad); raise AssertionError
    except T.UndoError:
        pass
# 秘密文件：不给 diff；太大：列出、不撤销、没有可撤销的就没有 token
t = T.Tracker()
env = wr / ".env"; t.before(wr, env); env.write_text("API_KEY=abc\n")
c = T.finish(t, ws)
assert c["files"][0]["hidden"] and c["files"][0]["diff"] == "" and "abc" not in json.dumps(c)
old = T.TRACK_MAX; T.TRACK_MAX = 4
t = T.Tracker()
big = wr / "big.txt"; big.write_text("0123456789\n"); t.before(wr, big); big.write_text("changed\n")
c = T.finish(t, ws)
assert c["token"] == "" and c["files"][0]["big"] and c["files"][0]["diff"] == "", c
T.TRACK_MAX = old
# 命令删了这一轮新改的文件：标 deleted；撤销把原文件写回
t = T.Tracker()
d = wr / "gone.txt"; d.write_text("a\nb\n"); t.before(wr, d); d.write_text("c\n"); d.unlink()
c = T.finish(t, ws)
assert c["files"][0]["deleted"] and c["files"][0]["removed"] == 2
T.undo(ws, c["token"]); assert d.read_text() == "a\nb\n"
# 卡片最多 FILES_MAX 个，撤销覆盖全部
old = T.FILES_MAX; T.FILES_MAX = 2
t = T.Tracker()
for i in range(4):
    f = wr / f"many{i}.txt"; t.before(wr, f); f.write_text(str(i))
c = T.finish(t, ws)
assert len(c["files"]) == 2 and c["more"] == 2 and "等 4 个文件" in T.history_text(c)
T.undo(ws, c["token"]); assert not any((wr / f"many{i}.txt").exists() for i in range(4))
T.FILES_MAX = old
# 过期清理
import time as _t
stale = wr / ".turns" / "old"; stale.mkdir(parents=True)
os.utime(stale, (_t.time() - 40 * 86400,) * 2)
t = T.Tracker(); f = wr / "sweep.txt"; t.before(wr, f); f.write_text("1")
T.finish(t, ws)
assert not stale.exists()
f.unlink()

# ---- 2. 真实回合（模拟模型）：写两个文件 → 回复末尾一张改动卡；REST 撤销；下一轮历史里说清楚 ----
script: list = []
seen_requests: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen_requests.append([dict(m) for m in messages])
    step = script.pop(0)
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"c{len(script)}-{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()

async def seed(text="改一下"):
    async with SessionLocal() as db:
        conv = Conversation(title="改文件"); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=[{"type": "text", "text": text}]))
        await db.commit()
        return conv.id
async def turn(cid):
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=lambda ev: asyncio.sleep(0))

(wr / "notes.md").write_text("第一行\n第二行\n")
cid = asyncio.run(seed())
script.extend([
    [("read_file", {"path": "notes.md"})],
    [("edit_file", {"path": "notes.md", "old_string": "第二行", "new_string": "第二行（改）"}),
     ("write_file", {"path": "out/report.md", "content": "# 报告\n"})],
    [("edit_file", {"path": "notes.md", "old_string": "（改）", "new_string": "（再改）"})],
    "改好了。"])
reply = asyncio.run(turn(cid))
types = [b["type"] for b in reply.blocks]
assert types == ["text", "changes"], types
card = reply.blocks[-1]
assert [f["path"] for f in card["files"]] == ["notes.md", "out/report.md"] and card["token"]
assert card["files"][0]["added"] == 1 and card["files"][0]["removed"] == 1      # 两次改动合成一份净 diff
assert "+第二行（再改）" in card["files"][0]["diff"]

import httpx
from fastapi import FastAPI
from app.auth import require_user
from app.routes import conversations as rc
api = FastAPI(); api.include_router(rc.router)
api.dependency_overrides[require_user] = lambda: "u"
async def rest():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://t") as http:
        url = f"/api/conversations/{cid}/messages/{reply.id}/changes/undo"
        (wr / "notes.md").write_text("用户手改了\n")
        r = await http.post(url)
        assert r.status_code == 409 and r.json()["detail"]["conflicts"] == ["notes.md"], r.text
        assert (wr / "out/report.md").exists()                                  # 冲突：一个都没动
        (wr / "notes.md").write_text("第一行\n第二行（再改）\n")
        r = await http.post(url)
        assert r.status_code == 200 and r.json()["blocks"][-1]["undone"] is True, r.text
        assert (wr / "notes.md").read_text() == "第一行\n第二行\n" and not (wr / "out/report.md").exists()
        assert (await http.post(url)).status_code == 410
        assert (await http.post(f"/api/conversations/{cid}/messages/nope/changes/undo")).status_code == 404
        m0 = await seed("没改文件")
        script.append("好。")
        plain = await turn(m0)
        assert [b["type"] for b in plain.blocks] == ["text"]                    # 没改文件：没有卡
        assert (await http.post(f"/api/conversations/{m0}/messages/{plain.id}/changes/undo")).status_code == 404
asyncio.run(rest())

# 下一轮：历史里告诉模型改动已被撤销；写之前读过的版本已过期 → 覆盖被拒（file_seen）
async def add_user(cid, text):
    async with SessionLocal() as db:
        db.add(Message(conversation_id=cid, role="user", blocks=[{"type": "text", "text": text}])); await db.commit()
asyncio.run(add_user(cid, "再来"))
seen_requests.clear()
script.extend([[("write_file", {"path": "notes.md", "content": "覆盖\n"})], "好。"])
r2 = asyncio.run(turn(cid))
hist = json.dumps(seen_requests[0], ensure_ascii=False)
assert "用户已撤销这些改动" in hist, hist[-800:]
assert r2.steps[0]["state"] == "error" and (wr / "notes.md").read_text() == "第一行\n第二行\n"
assert [b["type"] for b in r2.blocks] == ["text"]                               # 被拒的写不算改动

# 被停下的一轮也出卡（文件已经改了）
from app.agent import loop
cid3 = asyncio.run(seed())
stop = asyncio.Event()
async def stopping():
    async with SessionLocal() as db:
        conv = await db.get(Conversation, cid3)
        async def emit(ev):
            if ev.get("type") == "tool.status" and ev.get("state") == "done":
                stop.set(); raise asyncio.CancelledError
        try:
            return await run_turn(db, conv, emit=emit, stop=stop)
        except asyncio.CancelledError:
            return None
script.extend([[("write_file", {"path": "stopped.txt", "content": "半截\n"})], "不会到这"])
asyncio.run(stopping())
async def last(cid):
    async with SessionLocal() as db:
        from sqlalchemy import select
        return (await db.scalars(select(Message).where(Message.conversation_id == cid, Message.role == "assistant"))).all()
ms = asyncio.run(last(cid3))
assert ms and ms[-1].status == "stopped" and ms[-1].blocks[-1]["type"] == "changes", [(m.status, m.blocks) for m in ms]
script.clear()
print("smoke_turn_changes ok")
