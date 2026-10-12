# 冒烟：手动整理上文（context.compact_now / GET context / POST compact；Codex /compact、Gemini /compress 的对应物）
# + 压成检查点后重新钉上当前计划（plan.pinned → compact.checkpoint）。模拟模型，不打真接口。
# 一、计划钉回：没有计划 → 检查点原样；有计划 → 摘要之后贴整张清单（状态原样）；is_checkpoint 仍认得；
#    Compactor 强制压一次 → 新检查点带着压缩那一刻的计划（之后改的计划下次压缩时更新）。
# 二、手动整理：GET context 报原文条数/字数/可整理条数 → POST compact 把最后一问之前全部并进摘要（摘要模型拿到的是
#    这些消息、不含最后一问）→ 再点一次 noop 不调模型 → 新消息后再整理会带上旧摘要（合并不叠层）→
#    摘要比原文还长 inflated 不换 → 摘要模型出错 502 原样不动 → 正在回复 409、心跳过期不算忙 →
#    下一轮 build_history 用这份摘要、只发最后一问及其后的原文 → 不存在的对话 404。
# 运行：python tests/smoke_manual_compact.py
import os, sys, asyncio, subprocess, tempfile, json
from datetime import datetime, timedelta, timezone
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", HISTORY_CHARS="100000")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

import httpx
from app import llm, plan, turn_journal
from app.agent import compact, context
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message, TurnJournal

# —— 一、计划钉回 ——
assert plan.pinned([]) == "" and plan.pinned([{"type": "plan", "items": []}]) == ""
cp = compact.checkpoint("摘要正文")
assert cp["content"].endswith(compact.SUMMARY_CLOSE) and compact.is_checkpoint(cp)
items = [{"content": "读代码", "status": "completed"}, {"content": "改接口", "status": "in_progress"},
         {"content": "跑测试", "status": "pending"}]
pin = plan.pinned([{"type": "text", "text": "x"}, plan.block(items)])
assert pin.startswith(plan.PINNED_HEAD) and "1. [completed] 读代码" in pin and "3. [pending] 跑测试" in pin, pin
cp = compact.checkpoint("摘要正文", pin)
assert compact.is_checkpoint(cp) and cp["content"].index(compact.SUMMARY_CLOSE) < cp["content"].index(plan.PINNED_HEAD)
assert compact.checkpoint("s", "   ")["content"].endswith(compact.SUMMARY_CLOSE)

summaries = []
async def fake_complete(messages, model=None, **kw):
    summaries.append(messages)
    return "检查点摘要"
llm.complete = fake_complete

async def pinned_compactor():
    blocks = [plan.block(items)]
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "做事"}]
    for i in range(4):
        msgs += [{"role": "assistant", "content": None, "tool_calls": [
            {"id": f"c{i}", "type": "function", "function": {"name": "t", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": f"c{i}", "content": "结果" * 50}]
    c = compact.Compactor(1, None, None, pinned=lambda: plan.pinned(blocks))
    info = await c.maybe(msgs, force=True)
    assert info and info["folded"], info
    cps = [m for m in msgs if compact.is_checkpoint(m)]
    assert len(cps) == 1 and "2. [in_progress] 改接口" in cps[0]["content"], cps
    blocks[0] = plan.block([{**i, "status": "completed"} for i in items])  # 计划后来变了：下次压缩钉新版本
    msgs += [{"role": "assistant", "content": None, "tool_calls": [
        {"id": "z", "type": "function", "function": {"name": "t", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "z", "content": "后来" * 50}]
    await c.maybe(msgs, force=True)
    cps = [m for m in msgs if compact.is_checkpoint(m)]
    assert len(cps) == 1 and "2. [completed] 改接口" in cps[0]["content"] and "[in_progress]" not in cps[0]["content"]
    print("ok: pinned plan")

asyncio.run(pinned_compactor())

# —— 二、手动整理 ——
folds = []
mode = {"v": "ok"}
async def fake_fold(messages, model=None, **kw):
    folds.append(messages[1]["content"])
    if mode["v"] == "fail":
        raise RuntimeError("摘要网关挂了")
    if mode["v"] == "inflate":
        return "长" * 100000
    return f"摘要{len(folds)}"
llm.complete = fake_fold


async def add(cid, role, text):
    async with SessionLocal() as db:
        db.add(Message(conversation_id=cid, role=role, blocks=text_to_blocks(text)))
        await db.commit()
        await asyncio.sleep(0.002)  # created_at 有序


async def main():
    from fastapi import FastAPI
    from app.auth import require_user
    from app.routes import conversations as rc
    app = FastAPI(); app.include_router(rc.router)
    app.dependency_overrides[require_user] = lambda: "u"
    async with SessionLocal() as db:
        conv = Conversation(); db.add(conv); await db.commit(); cid = conv.id
    for n in range(4):
        await add(cid, "user", f"问题{n}" + "q" * 30)
        await add(cid, "assistant", f"回答{n}" + "a" * 30)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        s = (await c.get(f"/api/conversations/{cid}/context")).json()
        assert s["messages"] == 8 and s["summarized"] == 0 and s["raw"] == 8 and s["compactable"] == 6, s
        assert s["budget"] == 100000 and s["summary"] == "" and s["raw_chars"] > 8 * 30

        r = (await c.post(f"/api/conversations/{cid}/compact")).json()
        assert r["status"] == "compressed" and r["summarized"] == 6 and r["raw"] == 2 and r["compactable"] == 0, r
        assert r["summary"] == "摘要1" and r["after"] < r["before"], r
        assert len(folds) == 1 and "问题0" in folds[0] and "回答2" in folds[0] and "问题3" not in folds[0], folds[0]
        assert "【已有摘要】\n（无）" in folds[0]

        r = (await c.post(f"/api/conversations/{cid}/compact")).json()
        assert r["status"] == "noop" and len(folds) == 1 and r["before"] == r["after"], r

        async with SessionLocal() as db:
            h = await context.build_history(db, cid)
        assert h.summary == "摘要1" and [m["content"][:3] for m in h.messages] == ["问题3", "回答3"], h
        assert len(folds) == 1  # 预算内：下一轮不再自动折叠

        await add(cid, "user", "问题4"); await add(cid, "assistant", "回答4")
        r = (await c.post(f"/api/conversations/{cid}/compact")).json()
        assert r["status"] == "compressed" and r["summary"] == "摘要2" and r["summarized"] == 8, r
        assert "【已有摘要】\n摘要1" in folds[-1] and "问题3" in folds[-1] and "问题0" not in folds[-1]

        await add(cid, "user", "问题5"); await add(cid, "assistant", "回答5")
        mode["v"] = "inflate"
        r = (await c.post(f"/api/conversations/{cid}/compact")).json()
        assert r["status"] == "inflated" and r["summary"] == "摘要2" and r["summarized"] == 8 and r["compactable"] == 2, r

        mode["v"] = "fail"
        r = await c.post(f"/api/conversations/{cid}/compact")
        assert r.status_code == 502 and "摘要网关挂了" in r.json()["detail"], r.text
        s = (await c.get(f"/api/conversations/{cid}/context")).json()
        assert s["summary"] == "摘要2" and s["summarized"] == 8 and s["compactable"] == 2, s

        mode["v"] = "ok"
        async with SessionLocal() as db:
            j = TurnJournal(conversation_id=cid, owner=turn_journal.owner()); db.add(j); await db.commit(); jid = j.id
        n = len(folds)
        r = await c.post(f"/api/conversations/{cid}/compact")
        assert r.status_code == 409 and "正在回复" in r.json()["detail"] and len(folds) == n, r.text
        async with SessionLocal() as db:
            j = await db.get(TurnJournal, jid)
            j.beat_at = datetime.now(timezone.utc) - timedelta(seconds=turn_journal.STALE_S + 5)
            j.owner = "worker:gone"
            await db.commit()
            assert not await turn_journal.busy(db, cid)
        r = (await c.post(f"/api/conversations/{cid}/compact")).json()
        assert r["status"] == "compressed" and r["summary"] == f"摘要{n + 1}" and r["summarized"] == 10, r

        assert (await c.get("/api/conversations/nope/context")).status_code == 404
        assert (await c.post("/api/conversations/nope/compact")).status_code == 404

        async with SessionLocal() as db:  # 空对话：noop
            e = Conversation(); db.add(e); await db.commit(); eid = e.id
        r = (await c.post(f"/api/conversations/{eid}/compact")).json()
        assert r["status"] == "noop" and r["messages"] == 0 and r["compactable"] == 0, r
    print("ok: manual compact")

asyncio.run(main())
print("ALL OK")
