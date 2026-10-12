# 冒烟：工具返回的图给模型看（ToolResult.images → vision.for_tool）。模拟模型，只看发给模型的消息：
# - 能看图的别名（fast）：read_file 读项目里的 PNG → 工具结果说“已附在下一条消息里”，紧跟一条 user 消息带 JPEG data URL；
#   这条图消息只活在本轮工具循环里（下一轮历史里没有）。
# - 不能看图的别名（smart）：同一张图 → 描述写进工具结果（看图模型调用一次，按内容哈希缓存，再读不再调用）。
# - 超过一步上限的图只报名字；坏图报“打不开”；超大图 read_file 直接拒绝；文本文件照旧。
# - browser_look：截图接口 404 → 提示先打开；200 → 实时画面卡 + 图。
# 运行：python tests/smoke_tool_images.py
import os, sys, asyncio, subprocess, tempfile, json, io
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速", "smart": "深度"}), DEFAULT_MODEL="fast",
  VISION_MODELS='["fast"]', VISION_MODEL="fast", IMAGE_MAX_SIDE="1280")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

import httpx
from PIL import Image
from app import llm, vision, browser_client
from app.agent import loop
from app.agent.tools import ToolContext, ToolImage, load_builtin
from app.db import SessionLocal
from app.storage import project_dir

load_builtin()

def png(w, h) -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (w, h), (255, 0, 0, 128)).save(out, "PNG")
    return out.getvalue()

pd = project_dir("p1")
pd.mkdir(parents=True, exist_ok=True)
(pd / "chart.png").write_bytes(png(2400, 800))
(pd / "notes.md").write_text("# 笔记\n内容", encoding="utf-8")
(pd / "huge.png").write_bytes(b"\x89PNG" + b"0" * (vision.TOOL_IMAGE_MAX_BYTES + 1))

captions = []
async def fake_complete(messages, model=None, kind="summary"):
    assert kind == "vision"
    captions.append(messages)
    return "红色半透明方块"
llm.complete = fake_complete

def script(*calls):
    """模型第一步调用给定工具，第二步说“好了”。返回每步收到的 messages。"""
    seen = []
    async def fake(messages, tools=None, model=None, effort=None):
        seen.append([dict(m) for m in messages])
        if len(seen) == 1:
            yield llm.Turn(tool_calls=[llm.ToolCall(f"c{i}", n, json.dumps(a)) for i, (n, a) in enumerate(calls)])
        else:
            yield "好了"
            yield llm.Turn(text="好了")
    loop.stream_turn = fake
    return seen

async def run(model, *calls, project="p1"):
    seen = script(*calls)
    async with SessionLocal() as db:
        events = [e async for e in loop.run("sys", [{"role": "user", "content": "看看"}],
                                             ToolContext(db=db, project_id=project), model=model)]
    return seen, events[-1].blocks

async def main():
    # 1) 能看图：原图消息紧跟工具结果
    seen, _ = await run("fast", ("read_file", {"path": "chart.png"}))
    msgs = seen[1]
    tool = next(m for m in msgs if m["role"] == "tool")
    assert "chart.png 是图片" in tool["content"] and "已附在下一条消息里" in tool["content"], tool
    img_msg = msgs[-1]
    assert img_msg["role"] == "user" and isinstance(img_msg["content"], list), img_msg
    assert "不是用户说的话" in img_msg["content"][0]["text"]
    url = img_msg["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    import base64
    w, h = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).size
    assert max(w, h) == 1280, (w, h)
    assert captions == []
    assert msgs.index(img_msg) == msgs.index(tool) + 1

    # 2) 不能看图：描述进工具结果，按内容缓存
    seen, _ = await run("smart", ("read_file", {"path": "chart.png"}))
    tool = next(m for m in seen[1] if m["role"] == "tool")
    assert "[图片 chart.png：红色半透明方块]" in tool["content"], tool
    assert seen[1][-1]["role"] == "tool"  # 没有补图消息
    assert len(captions) == 1
    seen, _ = await run("smart", ("read_file", {"path": "chart.png"}))
    assert len(captions) == 1, "同一张图不该再描述"

    # 3) 上限 / 坏图 / 超大 / 文本
    seen, _ = await run("fast", *[("read_file", {"path": "chart.png"})] * 4, ("read_file", {"path": "huge.png"}),
                        ("read_file", {"path": "notes.md"}))
    msgs = seen[1]
    tools = [m for m in msgs if m["role"] == "tool"]
    assert len(tools) == 6
    assert "一次最多看 3 张" in tools[-1]["content"], tools[-1]
    assert "太大" in tools[4]["content"]
    assert tools[5]["content"].startswith("# 笔记")
    assert len([p for p in msgs[-1]["content"] if p["type"] == "image_url"]) == 3
    note, msg = await vision.for_tool([ToolImage("坏.png", b"not an image")], "fast")
    assert msg is None and "打不开" in note, note

    # 4) browser_look
    shot = io.BytesIO(); Image.new("RGB", (800, 600), "white").save(shot, "JPEG")
    status = {"code": 404}
    async def fake_call(session, method, path, json=None):
        assert (session, method, path) == ("example-com", "GET", "/screen")
        return httpx.Response(status["code"], content=shot.getvalue() if status["code"] == 200 else b"")
    browser_client.call = fake_call
    seen, _ = await run("fast", ("browser_look", {}), project=None)
    tool = next(m for m in seen[1] if m["role"] == "tool")
    assert "先用 browser_open" in tool["content"] and seen[1][-1]["role"] == "tool"
    status["code"] = 200
    from app import browser_sessions
    browser_sessions.tab = lambda c, t=None: browser_sessions.Tab(session="example-com", url="https://example.com/")
    seen, blocks = await run("fast", ("browser_look", {}), project=None)
    assert seen[1][-1]["role"] == "user" and seen[1][-1]["content"][1]["type"] == "image_url"
    assert any(b["type"] == "browser" for b in blocks), blocks
    print("ok: tool images")

asyncio.run(main())
