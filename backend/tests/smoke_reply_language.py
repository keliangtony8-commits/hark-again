# 冒烟：v2.67 回复语言（app/reply_language.py，不打真模型）。
# 默认 auto：系统提示不加字；PATCH 设 en → 提示 STABLE 段有“都用英文”，标题提示带“用英文写。”，记忆概括“请用英文”，语音识别 en；
# 别名（English / zh_CN / 繁體）规范化；不认识的值 422 且不改；工具 set_reply_language 改设置并回文案；坏值存在库里读成 auto。
import os, sys, asyncio, subprocess, tempfile, types
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import conversation_title, llm, memory_digest, reply_language as L, voice
from app.auth import require_user
from app.db import SessionLocal
from app.models import AppSetting, Conversation, Memory, Message
from app.routes import preferences
from app.routes import voice as voice_route
from app.agent import context
from app.agent.tools import REGISTRY, load_builtin

load_builtin()
app = FastAPI(); app.include_router(preferences.router); app.include_router(voice_route.router)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)

async def prompt_text():
    async with SessionLocal() as db:
        return (await context.build_system_prompt(db, None, "hi")).text()

# —— 默认 auto ——
w = c.get("/api/preferences").json()
assert w["reply_language"] == "auto" and [x["code"] for x in w["reply_languages"]] == ["auto", "zh-Hans", "zh-Hant", "en"], w
base = asyncio.run(prompt_text())
assert "回复语言" not in base

# —— 别名 + 拒绝 ——
assert L.normalize("English") == "en" and L.normalize("zh_CN") == "zh-Hans" and L.normalize("繁體") == "zh-Hant" and L.normalize("klingon") is None
r = c.patch("/api/preferences", json={"reply_language": "klingon"}); assert r.status_code == 422, r.text
assert c.get("/api/preferences").json()["reply_language"] == "auto"
r = c.patch("/api/preferences", json={"reply_language": "English"}); assert r.status_code == 200 and r.json()["reply_language"] == "en", r.text
assert c.patch("/api/preferences", json={}).json()["reply_language"] == "en"  # 空 PATCH 不改

# —— 系统提示 ——
t = asyncio.run(prompt_text())
assert "必须用英文（English）写" in t and "set_reply_language" in t, t[-400:]
assert t.rstrip().endswith(L.prompt_line("en").rstrip()) and t.index("现在是") < t.index("【回复语言设置】")  # 放在最后

# —— 标题 / 记忆概括 / 语音 用同一设置 ——
seen = []
async def fake_complete(messages, model=None, kind="", **kw):
    seen.append((kind, [dict(m) for m in messages]))
    return "Plan a weekend trip" if kind == "title" else "You like tea."
llm.complete = fake_complete
async def titles():
    async with SessionLocal() as db:
        cv = Conversation(title="周末", title_source=conversation_title.FIRST)
        db.add(cv); await db.flush()
        db.add_all([Message(conversation_id=cv.id, role="user", blocks=[{"type": "text", "text": "周末去哪玩"}]),
                    Message(conversation_id=cv.id, role="assistant", blocks=[{"type": "text", "text": "去杭州"}])])
        db.add(Memory(content="喜欢喝茶", category="preference")); await db.commit()
        cid = cv.id
    async with SessionLocal() as db:
        got = await conversation_title.maybe(db, cid)
    async with SessionLocal() as db:
        await memory_digest.regenerate(db)
    return got
assert asyncio.run(titles()) == "Plan a weekend trip"
title_prompt = seen[0][1][0]["content"]; assert "用英文（English）写。\n标题：" in title_prompt, title_prompt[-80:]
digest_prompt = seen[1][1][0]["content"]; assert "请用英文（English）、第二人称" in digest_prompt, digest_prompt
asked = {}
async def fake_tr(name, data, language="zh"):
    asked["lang"] = language; return "hello"
voice.transcribe = fake_tr
r = c.post("/api/voice/transcribe", files={"file": ("a.webm", b"xx")}); assert r.json()["text"] == "hello" and asked["lang"] == "en", (r.text, asked)

# —— 工具 ——
tool = REGISTRY["set_reply_language"]; assert tool.deferred
async def call(code):
    async with SessionLocal() as db:
        return await tool.run(types.SimpleNamespace(db=db), code=code)
res = asyncio.run(call("zh-Hant")); assert not res.failed and "繁体中文" in res.content, res.content
assert c.get("/api/preferences").json()["reply_language"] == "zh-Hant"
res = asyncio.run(call("martian")); assert res.failed
res = asyncio.run(call("auto")); assert "跟随" in res.content
assert "回复语言" not in asyncio.run(prompt_text())
seen.clear(); asyncio.run(titles())
assert "写。\n标题：" not in seen[0][1][0]["content"] and "请用中文" in seen[1][1][0]["content"]  # auto → 原样

# —— 库里存了坏值 → auto ——
async def corrupt():
    async with SessionLocal() as db:
        (await db.get(AppSetting, L.KEY)).value = {"code": "xx"}; await db.commit()
asyncio.run(corrupt()); assert c.get("/api/preferences").json()["reply_language"] == "auto"
print("smoke_reply_language OK")

# —— nudge：只改请求副本 ——
h = [{"role": "user", "content": "旧问题"}, {"role": "assistant", "content": "a"}, {"role": "user", "content": "推荐甜点"}]
n = L.nudge(h, "en")
assert n[-1]["content"].endswith("（用英文（English）回复。）") and h[-1]["content"] == "推荐甜点" and n[0] is h[0]
assert L.nudge(h, "auto") is h
img = [{"role": "user", "content": [{"type": "text", "text": "这是什么"}, {"type": "image_url", "image_url": {"url": "x"}}]}]
assert L.nudge(img, "zh-Hant")[-1]["content"][-1] == {"type": "text", "text": "（用繁体中文（台湾/香港用字）回复。）"} and len(img[0]["content"]) == 2
assert L.nudge([{"role": "assistant", "content": "x"}], "en")[0]["content"] == "x"
print("smoke_reply_language nudge OK")
