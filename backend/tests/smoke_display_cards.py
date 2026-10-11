# 冒烟：v0.78 回复卡片补齐——草稿卡 show_draft、摘要卡 show_summary、图片卡 show_images。模拟模型（不打真接口），无迁移。
# 一轮里模型依次调三个工具 → 回复的 blocks 里有 draft / summary / images 三张卡且能被 Block 校验；
# 打不开的图片被丢掉（探测函数换成假的，不上网）、全打不开 → 不出卡并告诉模型；非 http 地址直接拒绝；
# blocks_to_text 能把三张卡压回文字喂模型；分享成网页时三张卡都在、正文被转义（无注入）。
# 运行：python tests/smoke_display_cards.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, PUBLIC_URL="https://me.example",
  TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from pydantic import TypeAdapter
from app import llm, conversation_share
from app.agent import runner
from app.agent.builtin import display
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.blocks import Block, blocks_to_text, text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message
from app.config import settings

BAD = "https://img.example/broken.jpg"
async def fake_probe(client, url):
    return url != BAD
real_probe = display.probe_image
display.probe_image = fake_probe

script: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)

async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
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
for n in ("show_draft", "show_summary", "show_images"):
    assert n in REGISTRY, n
assert "show_draft" in settings.system_prompt and "show_images" in settings.system_prompt

DRAFT = "Subject: 十月房租晚两天\n\n王先生您好：\n这个月工资 15 号才到，<b>房租</b>想晚两天交。"
script.extend([
    ("show_draft", {"title": "给房东的邮件", "body": DRAFT}),
    ("show_summary", {"title": "杭州两日行程", "subtitle": "10 月 18–19 日", "markdown": "## 周六\n- 断桥骑行\n- 楼外楼<script>"}),
    ("show_images", {"items": [{"url": "https://img.example/a.jpg", "caption": "白堤"}, {"url": BAD, "caption": "坏图"},
                               {"url": "javascript:alert(1)"}]}),
    "都放好了。",
])

async def turn():
    async with SessionLocal() as db:
        conv = Conversation(id="c1", title="杭州"); db.add(conv); await db.commit()
        db.add(Message(conversation_id="c1", role="user", blocks=text_to_blocks("帮我写邮件、排行程、看看白堤")))
        await db.commit()
        reply = await runner.run_turn(db, conv)
        msgs = (await conversation_share.load(db, "c1")).messages
        return reply.blocks, msgs
blocks, msgs = asyncio.run(turn())
types = [b["type"] for b in blocks]
assert types.count("draft") == 1 and types.count("summary") == 1 and types.count("images") == 1, types
ta = TypeAdapter(Block)
for b in blocks:
    ta.validate_python(b)
img = next(b for b in blocks if b["type"] == "images")
assert [i["url"] for i in img["items"]] == ["https://img.example/a.jpg"] and img["items"][0]["caption"] == "白堤", img
d = next(b for b in blocks if b["type"] == "draft")
assert d["body"] == DRAFT.strip() and d["title"] == "给房东的邮件"

text = blocks_to_text(blocks)
assert "[草稿「给房东的邮件」]" in text and "Subject: 十月房租晚两天" in text, text
assert "# 杭州两日行程" in text and "10 月 18–19 日" in text and "白堤 https://img.example/a.jpg" in text, text

page = conversation_share.render(NS(title="杭州"), msgs)
assert "草稿 · 给房东的邮件" in page and "&lt;b&gt;房租" in page and "<b>房租" not in page
assert "<h3>杭州两日行程</h3>" in page and "<script>" not in page and "&lt;script&gt;" in page
assert 'src="https://img.example/a.jpg"' in page and BAD not in page and "javascript:" not in page

async def call(name, **kw):
    async with SessionLocal() as db:
        return await REGISTRY[name].run(ToolContext(db=db, conversation_id="c1"), **kw)
r = asyncio.run(call("show_images", items=[{"url": BAD}]))
assert not r.blocks and "打不开" in r.content, r
r = asyncio.run(call("show_images", items=[{"url": "ftp://x/y.png"}]))
assert not r.blocks and "http" in r.content, r
r = asyncio.run(call("show_images", items=[{"url": f"https://img.example/{i}.jpg"} for i in range(9)]))
assert len(r.blocks[0]["items"]) == 6, r
assert not asyncio.run(call("show_draft", title="x", body="  ")).blocks
assert asyncio.run(call("show_summary", title="", markdown="正文")).blocks[0]["title"] == "摘要"

# 真探测函数：非图片类型 / 404 都算打不开（httpx MockTransport，不上网）
import httpx
def handler(req):
    if req.url.path == "/ok.png":
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"x")
    if req.url.path == "/page":
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>")
    return httpx.Response(404)
async def probes():
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as cl:
        return [await real_probe(cl, f"https://h{p}") for p in ("/ok.png", "/page", "/nope")]
assert asyncio.run(probes()) == [True, False, False]
print("ok: display cards (draft / summary / images)")
