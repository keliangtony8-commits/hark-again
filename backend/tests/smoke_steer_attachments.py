# 冒烟：回答途中补充带附件（v1.93，学 Codex steer_input 收完整 UserInput）。模拟模型（不打真接口）。
# 规则（空 / 只有附件 / !命令 / @子助手）→ 能看图的模型：补充 = 文字 + 文本附件内容 + 原图（image_url），下一次调模型前并进来 →
# 库里那条 steer 消息带着附件块、turn.steered 推出去也带 → 不能看图的模型：只发图也能插，图先写成描述（缓存）→
# @工作区文件 / 选的工作区文件 内容跟着进来 → 假附件且没字 / @子助手 → 不插（排队）→ 下一轮历史里有附件内容。
# 运行：python tests/smoke_steer_attachments.py
import os, sys, asyncio, subprocess, tempfile, json, io
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速", "smart": "深度"}), DEFAULT_MODEL="fast",
  VISION_MODELS='["fast"]', VISION_MODEL="fast")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from PIL import Image
from sqlalchemy import select
from app import live_turns, llm, steering, storage, workspaces
from app.agent import loop
from app.config import settings
from app.db import SessionLocal
from app.llm import Turn
from app.models import Message
from app.routes import ws as rws

calls: list[list[dict]] = []
gate: dict[str, asyncio.Event] = {}
entered = asyncio.Event()
captions: list[str] = []


async def fake_stream_turn(messages, tools=None, model=None, effort=None):
    calls.append([dict(m) for m in messages])  # 照抄：loop 之后还会往同一个列表里加
    n = len(calls)
    if f"g{n}" in gate:
        entered.set()
        await gate[f"g{n}"].wait()
    yield f"第{n}次"
    yield Turn(text=f"第{n}次")
loop.stream_turn = fake_stream_turn


async def fake_complete(messages, model=None, kind="summary"):
    if kind == "vision":
        captions.append(model)
        return "一张红色方块的测试图"
    return "摘要"
llm.complete = fake_complete


class Client:
    def __init__(self):
        self.events: list[dict] = []
        self.conn = live_turns.Conn(self.send)

    async def send(self, e):
        self.events.append(e)

    async def until(self, pred, timeout=5):
        async with asyncio.timeout(timeout):
            while not pred(self.events):
                await asyncio.sleep(0.01)


def png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (255, 0, 0)).save(out, "PNG")
    return out.getvalue()


def user_contents(msgs):
    return [m["content"] for m in msgs if m["role"] == "user"]


def parts(content):
    return [p.get("type") for p in content] if isinstance(content, list) else ["str"]


async def running(text: str, **extra) -> tuple[Client, object, str]:
    """开一轮并卡在第一次调模型上，返回 (client, turn, cid)。"""
    calls.clear()
    gate.clear()
    gate["g1"] = asyncio.Event()
    entered.clear()
    c = Client()
    t = live_turns.enqueue(rws._handle_user_message, {"type": "user.message", "text": text, **extra}, c.conn)
    await asyncio.wait_for(entered.wait(), 5)
    cid = next(e for e in c.events if e["type"] == "message.start")["conversation_id"]
    return c, t, cid


async def finish(c: Client, t) -> None:
    gate["g1"].set()
    await c.until(lambda es: any(e["type"] == "message.done" for e in es))
    await asyncio.wait_for(asyncio.shield(t.task), 5)


async def main():
    settings.turn_offline_minutes = 30

    # 0) 规则
    assert steering.reason("") == "empty" and steering.reason("", files=0) == "empty"
    assert steering.reason("", files=1) is None and steering.reason("看这个", files=2) is None
    assert steering.reason("x", agent=True) == "rich" and steering.reason("!ls", command=True) == "rich"
    print("ok: 规则")

    img = storage.save_upload("红.png", png())
    note = storage.save_upload("notes.txt", "第三条要删掉".encode())

    # 1) 能看图的模型：文字 + 文本附件 + 原图一起插进这一轮
    a, t, cid = await running("帮我整理清单")
    ok = await rws._steer({"conversation_id": cid, "text": "参考这两个", "attachments": [img["id"], note["id"]],
                           "steer": True, "client_id": "local-9"})
    assert ok
    await finish(a, t)
    assert len(calls) == 2, len(calls)
    last = user_contents(calls[1])[-1]
    assert parts(last) == ["text", "image_url"], parts(last)
    assert "参考这两个" in last[0]["text"] and "[附件 notes.txt]" in last[0]["text"] and "第三条要删掉" in last[0]["text"], last[0]
    assert last[1]["image_url"]["url"].startswith("data:image/"), last[1]["image_url"]["url"][:30]
    st = next(e for e in a.events if e["type"] == "turn.steered")
    assert st["client_id"] == "local-9" and st["message"]["status"] == "steer"
    kinds = [b["type"] for b in st["message"]["blocks"]]
    assert kinds.count("file") == 2 and kinds[0] == "text", kinds
    async with SessionLocal() as db:
        rows = (await db.scalars(select(Message).where(Message.conversation_id == cid).order_by(Message.created_at))).all()
    assert [(m.role, m.status) for m in rows] == [("user", "done"), ("user", "steer"), ("assistant", "done")]
    assert [b.get("name") for b in rows[1].blocks if b["type"] == "file"] == ["红.png", "notes.txt"]
    assert not captions, "能看图的模型这一步不用描述"
    print("ok: 文字 + 附件 + 原图插进这一轮，库里 / turn.steered 带附件块")

    # 2) 不能看图的模型：只发一张图（没字）也能插，图先写成描述
    b, t2, cid2 = await running("看看", model="smart")
    assert steering.model_of(cid2) == "smart"
    assert await rws._steer({"conversation_id": cid2, "text": "", "attachments": [img["id"]], "steer": True})
    await finish(b, t2)
    last = user_contents(calls[1])[-1]
    assert isinstance(last, str) and "一张红色方块的测试图" in last and "红.png" in last, last
    assert captions == ["fast"], captions
    print("ok: 不能看图的模型 → 描述（缓存）")

    # 3) @工作区文件 + 选的工作区文件：内容跟着进来
    root_dir = storage.project_file_root(workspaces.PERSONAL)
    root_dir.mkdir(parents=True, exist_ok=True)
    (root_dir / "plan.md").write_text("周一跑步\n周三游泳", encoding="utf-8")
    (root_dir / "budget.csv").write_text("项目,金额\n房租,2000", encoding="utf-8")
    c3, t3, cid3 = await running("排个计划")
    assert await rws._steer({"conversation_id": cid3, "text": "按 @plan.md 来", "project_files": ["budget.csv"], "steer": True})
    await finish(c3, t3)
    last = user_contents(calls[1])[-1]
    text = last if isinstance(last, str) else last[0]["text"]
    assert "周三游泳" in text and "房租,2000" in text, text
    print("ok: @文件 / 选的工作区文件")

    # 4) 不插：假附件且没字、@子助手（排队成下一轮）
    d, t4, cid4 = await running("慢慢想")
    assert not await rws._steer({"conversation_id": cid4, "text": "", "attachments": ["nope"], "steer": True})
    assert not await rws._steer({"conversation_id": cid4, "text": "", "steer": True})
    if settings.subagent_max_tasks > 0:
        assert not await rws._steer({"conversation_id": cid4, "text": "@子助手 去查一下", "steer": True})
    assert not await rws._steer({"conversation_id": cid4, "text": "/init", "steer": True})
    await finish(d, t4)
    assert len(calls) == 1, "没插进去：不再来一圈"
    print("ok: 不插的照常排队")

    # 5) 下一轮历史里有补充的附件内容（普通用户消息的渲染）
    calls.clear()
    gate.clear()
    e = Client()
    t5 = live_turns.enqueue(rws._handle_user_message, {"type": "user.message", "conversation_id": cid, "text": "总结一下"}, e.conn)
    await asyncio.wait_for(asyncio.shield(t5.task), 5)
    hist = "\n".join(c if isinstance(c, str) else c[0]["text"] for c in user_contents(calls[0]))
    assert "第三条要删掉" in hist and "红.png" in hist, hist
    print("ok: 下一轮历史里有附件")

    await live_turns.drain()
    print("ALL OK")


asyncio.run(main())
