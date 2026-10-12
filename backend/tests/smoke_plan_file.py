# 冒烟：批准的方案存成工作区文件（v1.72，plan_mode.plan_file / approved_prompt，Gemini approvedPlanPath）。模拟模型。
# 一、规则：plan_slug、plan_file（新建 / 重名加 -2 / 同标题原地更新 / 旧文件被删或越界 → 新建）、approved_path、approved_prompt。
# 二、整轮：交方案 → 卡上带 workspace/path → 批准 → plans/ 里有方案原文、conv.plan_path、整轮改动卡列出它；
#    “全部文件”里有它；下一轮系统提示有“已批准的方案”（普通模式说“先读它”）；再进计划模式交同标题方案 → 原地更新同一个文件；
#    换标题 → 新文件；用户删掉文件 → 系统提示不再提；磁盘满 → 仍批准、方案没存、模型收到原因；
#    没批准 → 不写文件；整轮撤销能删掉刚存的方案文件；迁移 down/up。
# 运行：python tests/smoke_plan_file.py
import os, sys, asyncio, subprocess, tempfile, json
from datetime import date
from pathlib import Path
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', AUTO_TITLE="false",
  NEXT_SPEAKER_CHECK="off", MODEL_ROUTER="off")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
sys.path.insert(0, os.path.dirname(__file__))
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import llm, plan_mode as P, quota, turn_changes, workspaces
from app.agent.runner import run_turn
from app.agent.tools import load_builtin
from app.db import SessionLocal
from app.models import Conversation, Message
from app.schedule import local_now
from app.storage import project_dir

# —— 一、规则 ——
assert P.plan_slug("改 a.txt") == "改-a-txt" and P.plan_slug("  //??  ") == "plan" and P.plan_slug("A_b c") == "A-b-c"
assert len(P.plan_slug("长" * 100)) == P.SLUG_MAX
r0 = Path(tempfile.mkdtemp())
d = date(2026, 10, 13)
assert P.plan_file(r0, "迁移方案", None, d) == "plans/2026-10-13-迁移方案.md"
(r0 / "plans").mkdir(); (r0 / "plans/2026-10-13-迁移方案.md").write_text("# 别的标题\n")
assert P.plan_file(r0, "迁移方案", None, d) == "plans/2026-10-13-迁移方案-2.md"            # 重名
assert P.plan_file(r0, "迁移方案", "plans/2026-10-13-迁移方案.md", d) == "plans/2026-10-13-迁移方案-2.md"  # 旧文件标题不同 → 新建
(r0 / "plans/old.md").write_text("前言\n# 迁移方案\n内容")
assert P.plan_file(r0, "迁移方案", "plans/old.md", d) == "plans/old.md"                    # 同标题 → 原地更新
assert P.plan_file(r0, "迁移方案", "plans/gone.md", d).endswith("-2.md")                  # 旧文件没了
assert P.plan_file(r0, "迁移方案", "../../etc/passwd", d).endswith("-2.md")               # 越界不读
assert P.approved_path(r0, "plans/old.md") == "plans/old.md"
assert P.approved_path(r0, "plans/gone.md") is None and P.approved_path(r0, None) is None and P.approved_path(r0, "../x") is None
assert "read_file" in P.approved_prompt("plans/x.md", False) and "plans/x.md" in P.approved_prompt("plans/x.md", False)
assert "同一个 # 标题" in P.approved_prompt("plans/x.md", True)
assert P.review_card("# T", "T", "me", "plans/t.md") == {"type": "plan_review", "title": "T", "plan": "# T", "state": "pending",
                                                         "workspace": "me", "path": "plans/t.md"}
print("ok: rules")

# —— 二、整轮 ——
script: list = []
requests: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    requests.append([dict(m) for m in messages])
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
wr = project_dir(workspaces.PERSONAL)
today = local_now().date().isoformat()

async def seed(mode="plan", text="帮我规划一下"):
    async with SessionLocal() as db:
        conv = Conversation(title="计划", mode=mode, mode_seen=mode); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=[{"type": "text", "text": text}]))
        await db.commit()
        return conv.id
async def turn(cid, approve=True, text=None, mode=None):
    async with SessionLocal() as db:
        if text:
            db.add(Message(conversation_id=cid, role="user", blocks=[{"type": "text", "text": text}]))
        if mode:
            (await db.get(Conversation, cid)).mode = mode
        await db.commit()
    async def emit(ev):
        pass
    async def appr(_id, _t, _d):
        return approve
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid), emit=emit, approve=appr)
async def conv_of(cid):
    async with SessionLocal() as db:
        return await db.get(Conversation, cid)
def last_tool(req):
    return [m["content"] for m in req if m["role"] == "tool"][-1]

PLAN = "# 搬家清单\n\n## 概要\n先打包书\n\n## 验证\n数箱子"
cid = asyncio.run(seed())
script.extend([[(P.TOOL, {"plan": PLAN})], "开始做。"])
reply = asyncio.run(turn(cid))
rel = f"plans/{today}-搬家清单.md"
card = next(b for b in reply.blocks if b["type"] == "plan_review")
assert card["state"] == "approved" and card["workspace"] == workspaces.PERSONAL and card["path"] == rel, card
assert (wr / rel).read_text() == PLAN + "\n"
assert asyncio.run(conv_of(cid)).plan_path == rel
res = last_tool(requests[-1])
assert res.startswith(P.LIFTED) and rel in res and "已存到" in res, res
from app import conversation_files as CF
assert any(i["id"] == rel and i["origin"] == "written" for i in CF._from_message(reply, workspaces.PERSONAL))  # 进“全部文件”
changes = next(b for b in reply.blocks if b["type"] == "changes")
assert [f["path"] for f in changes["files"]] == [rel], changes
assert "已批准的方案" not in requests[-1][0]["content"]                                   # 这一轮还没有（下一轮起）
print("ok: approved → saved")

# 下一轮（普通模式）：系统提示提到它
script.append("好的。")
asyncio.run(turn(cid, text="接着做"))
sysp = requests[-1][0]["content"]
assert "已批准的方案" in sysp and rel in sysp and "read_file" in sysp, sysp[-400:]
# 再进计划模式：同标题 → 原地更新
PLAN2 = "# 搬家清单\n\n## 概要\n先打包书，再打包衣服"
script.extend([[(P.TOOL, {"plan": PLAN2})], "继续。"])
reply = asyncio.run(turn(cid, text="加上衣服", mode="plan"))
assert "同一个 # 标题" in requests[-2][0]["content"]
assert (wr / rel).read_text() == PLAN2 + "\n" and "已更新" in last_tool(requests[-1])
card = next(b for b in reply.blocks if b["type"] == "plan_review")
assert card["path"] == rel
ch = next(b for b in reply.blocks if b["type"] == "changes")["files"][0]
assert ch["path"] == rel and "衣服" in ch.get("diff", ""), ch
# 换标题 → 新文件
script.extend([[(P.TOOL, {"plan": "# 退租\n\n- 联系房东"})], "好。"])
asyncio.run(turn(cid, text="另起一份退租方案", mode="plan"))
rel2 = f"plans/{today}-退租.md"
assert (wr / rel2).is_file() and (wr / rel).is_file() and asyncio.run(conv_of(cid)).plan_path == rel2
# 用户删掉文件 → 不再提
(wr / rel2).unlink()
script.append("嗯。")
asyncio.run(turn(cid, text="随便聊聊"))
assert "已批准的方案" not in requests[-1][0]["content"]
print("ok: refine / new / deleted")

# 没批准：不写文件
cid2 = asyncio.run(seed())
script.extend([[(P.TOOL, {"plan": "# 不批的方案\n- x"})], "要改哪里？"])
reply = asyncio.run(turn(cid2, approve=False))
assert not (wr / f"plans/{today}-不批的方案.md").exists() and asyncio.run(conv_of(cid2)).plan_path is None
assert next(b for b in reply.blocks if b["type"] == "plan_review")["path"] == f"plans/{today}-不批的方案.md"
assert not any(b["type"] == "changes" for b in reply.blocks)
print("ok: rejected not saved")

# 整轮撤销能删掉刚存的方案
cid3 = asyncio.run(seed())
script.extend([[(P.TOOL, {"plan": "# 可撤销\n- y"})], "好。"])
reply = asyncio.run(turn(cid3))
rel3 = f"plans/{today}-可撤销.md"
token = next(b for b in reply.blocks if b["type"] == "changes")["token"]
assert (wr / rel3).is_file()
turn_changes.undo(workspaces.PERSONAL, token)
assert not (wr / rel3).exists()
# 撤销后文件没了：下一轮不提
script.append("嗯。")
asyncio.run(turn(cid3, text="然后呢"))
assert "已批准的方案" not in requests[-1][0]["content"]
print("ok: undo")

# 磁盘满：仍批准、模型知道没存
orig = quota.check
def full(ws, adding=0):
    raise quota.QuotaError("工作区满了")
quota.check = full
cid4 = asyncio.run(seed())
script.extend([[(P.TOOL, {"plan": "# 满盘方案\n- z"})], "照做。"])
reply = asyncio.run(turn(cid4))
quota.check = orig
res = last_tool(requests[-1])
assert res.startswith(P.LIFTED) and "没能存成文件" in res, res
assert asyncio.run(conv_of(cid4)).mode == "default" and asyncio.run(conv_of(cid4)).plan_path is None
assert not (wr / f"plans/{today}-满盘方案.md").exists()
print("ok: quota full")

for stp in ("downgrade", "upgrade"):
    rv = subprocess.run([sys.executable, "-m", "alembic", stp, "-1" if stp == "downgrade" else "head"], cwd=root,
                        capture_output=True, text=True)
    assert rv.returncode == 0, rv.stderr
print("ok: migration")
print("all ok")
