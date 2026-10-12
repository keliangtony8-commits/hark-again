# 冒烟：看图（vision.py）。模拟模型，只看发给模型的消息：
# 能看图的别名（fast）→ 当前这一问的图片缩到 IMAGE_MAX_SIDE 以内、作为 image_url 发出（透明 PNG 转 JPEG）；
# 下一轮这张图变成“文字描述”（看图模型描述一次，按上传 id 缓存，第三轮不再调用）；
# 不能看图的别名（smart）→ 当前这一问的图片直接给描述；描述失败不拖垮这一轮（只给名字，下轮再试）；
# 记忆检索用的 query 取多模态内容里的文字；非图片附件不受影响。
# 运行：python tests/smoke_vision.py
import os, sys, asyncio, subprocess, tempfile, json, base64, io
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速", "smart": "深度"}), DEFAULT_MODEL="fast",
  VISION_MODELS='["fast"]', VISION_MODEL="fast", IMAGE_MAX_SIDE="1280")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import llm, storage, vision
from app.agent import context, loop
from app.auth import issue_token, require_user
from app.routes import conversations as rc, files as rf, ws as rws

sent: list[list[dict]] = []
captions: list[tuple[str, list]] = []
fail_caption = False

async def fake_stream_turn(messages, tools=None, model=None, effort=None):
    sent.append(messages)
    yield "好"
    yield llm.Turn(text="好")
loop.stream_turn = fake_stream_turn

async def fake_complete(messages, model=None, kind="summary"):
    if kind == "vision":
        captions.append((model, messages))
        if fail_caption:
            raise RuntimeError("upstream down")
        return f"一张测试图 #{len(captions)}"
    return "摘要"
llm.complete = fake_complete

queries: list[str] = []
real_prompt = context.build_system_prompt
async def spy_prompt(db, project_id, query=""):
    queries.append(query)
    return await real_prompt(db, project_id, query)
import app.agent.runner as runner
runner.build_system_prompt = spy_prompt

app = FastAPI()
for r in (rws.router, rc.router, rf.router):
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
token = issue_token()

def png(w, h, mode="RGBA") -> bytes:
    out = io.BytesIO()
    Image.new(mode, (w, h), (200, 30, 30, 128) if mode == "RGBA" else (10, 120, 200)).save(out, "PNG")
    return out.getvalue()

def upload(name, data, mime):
    return c.post("/api/uploads", files={"file": (name, data, mime)}).json()

def turn(ws, event):
    ws.send_json(event)
    first = None
    while True:
        e = ws.receive_json()
        first = first or e
        if e["type"] in ("message.done", "error"):
            assert e["type"] == "message.done", e
            return first

def last_user(msgs):
    return [m for m in msgs if m["role"] == "user"][-1]["content"]

big = upload("a.png", png(3000, 1000), "image/png")
doc = upload("n.txt", "笔记内容".encode(), "text/plain")
assert big["mime"] == "image/png"

with c.websocket_connect(f"/ws?token={token}") as ws:
    # 1) 能看图：原图（缩过）+ 文字；文本附件照常内联；不调用描述
    e = turn(ws, {"type": "user.message", "text": "这是什么", "attachments": [big["id"], doc["id"]]})
    cid = e["conversation_id"]
    content = last_user(sent[-1])
    assert isinstance(content, list), content
    text, img = content[0], content[1]
    assert text["type"] == "text" and "这是什么" in text["text"] and "[图片 a.png]" in text["text"] and "笔记内容" in text["text"]
    url = img["image_url"]["url"]
    assert img["type"] == "image_url" and url.startswith("data:image/jpeg;base64,")
    w, h = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).size
    assert max(w, h) == 1280 and (w, h) == (1280, 427), (w, h)
    assert len(content) == 2 and not captions
    assert queries[-1].startswith("这是什么"), queries[-1]   # 多模态内容也能取到文字去挑记忆

    # 2) 下一轮：旧图变描述（只描述一次），当前这一问是纯文字
    turn(ws, {"type": "user.message", "text": "接着说", "conversation_id": cid})
    assert len(captions) == 1 and captions[0][0] == "fast"
    parts = captions[0][1][0]["content"]
    assert parts[0]["type"] == "text" and parts[1]["type"] == "image_url"
    old = [m for m in sent[-1] if m["role"] == "user"][0]["content"]
    assert isinstance(old, str) and "[图片 a.png：一张测试图 #1]" in old, old
    assert last_user(sent[-1]) == "接着说"
    assert storage.caption_path(big["id"]).read_text(encoding="utf-8") == "一张测试图 #1"

    turn(ws, {"type": "user.message", "text": "再说", "conversation_id": cid})
    assert len(captions) == 1                                   # 第三轮走缓存

    # 3) 不能看图的模型：当前这一问的新图直接给描述
    small = upload("b.jpg", png(200, 100, "RGB"), "image/jpeg")
    turn(ws, {"type": "user.message", "text": "这张呢", "conversation_id": cid, "model": "smart", "attachments": [small["id"]]})
    content = last_user(sent[-1])
    assert isinstance(content, str) and "[图片 b.jpg：一张测试图 #2]" in content, content
    assert len(captions) == 2

    # 4) 描述失败：只给名字，这一轮照常；下轮再试成功
    fail_caption = True
    third = upload("c.webp", png(64, 64), "image/webp")
    turn(ws, {"type": "user.message", "text": "第三张", "conversation_id": cid, "attachments": [third["id"]]})
    assert "[图片 c.webp]" in last_user(sent[-1]) and not storage.caption_path(third["id"]).exists()
    fail_caption = False
    turn(ws, {"type": "user.message", "text": "好了吗", "conversation_id": cid})
    assert any("[图片 c.webp：一张测试图" in m["content"] for m in sent[-1] if isinstance(m["content"], str))

# 5) 坏图：发不出原图就退回纯文字
bad = storage.save_upload("x.png", b"not an image")
blk = {"type": "file", "source": "upload", **bad}
assert vision.is_image(blk) and vision.content_with_images("hi", [blk]) == "hi"
assert not vision.is_image({**blk, "source": "project"}) and not vision.is_image({**blk, "mime": "image/svg+xml"})
assert vision.text_of([{"type": "text", "text": "a"}, {"type": "image_url"}]) == "a" and vision.text_of(None) == ""
print("smoke_vision OK")
