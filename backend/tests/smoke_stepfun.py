# 冒烟：接入阶跃 Step Plan（不打真接口，模拟到 OpenAI 客户端 / httpx 这一层）。
# 1) 直连模式：MODEL_MAP 把别名翻译成上游模型名，记账仍按别名；
# 2) 每个包都带“累计”用量（阶跃的行为）→ 只记最后一次；中途停止也记已花的；
# 3) reasoning_content / reasoning 字段 → Reasoning 片段 → WS thinking.delta，不进回复块、不落库；
# 4) 语音：capabilities、SSE 解析、m4a → ffmpeg 转 wav、识别拼接与记账、朗读清理与 /api/voice/* 路由。
# 运行：python tests/smoke_stepfun.py
import os, sys, asyncio, subprocess, tempfile, json, base64, shutil
from types import SimpleNamespace as NS
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="https://api.stepfun.ai/step_plan/v1",
  LLM_API_KEY="sk-test", OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="",
  MODEL_MAP=json.dumps({"fast": "step-3.7-flash", "smart": "step-5-preview", "lite": "step-3.5-flash"}),
  VOICE_PROVIDER="stepfun", STEP_API_KEY="sk-step")
os.environ.pop("LITELLM_MASTER_KEY", None)
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, delete
from app import llm, voice
from app.agent import loop
from app.auth import issue_token, require_user
from app.db import SessionLocal
from app.llm import Reasoning, Turn
from app.models import Message, UsageRecord
from app.routes import conversations as rc, ws as rws, voice as rv

assert llm.client.api_key == "sk-test"  # LLM_API_KEY 优先，不再要求 LITELLM_MASTER_KEY
assert llm.upstream("fast") == "step-3.7-flash" and llm.upstream("other") == "other"

# ---- 1~3：流式解析 ----
def u(p, c): return NS(prompt_tokens=p, completion_tokens=c)
def chunk(content=None, reasoning=None, extra=None, usage=None, choices=True):
    d = NS(content=content, tool_calls=None, model_extra=extra or {})
    if reasoning is not None:
        d.reasoning_content = reasoning
    return NS(choices=[NS(delta=d)] if choices else [], usage=usage)

seen_models = []
async def fake_create(model, messages, stream=False, stream_options=None, **kw):
    seen_models.append(model)
    async def gen():
        yield chunk("", reasoning="先想", usage=u(100, 1))
        yield chunk("", extra={"reasoning": "一想"}, usage=u(100, 2))     # 只有 reasoning 字段的供应商
        yield chunk("好", usage=u(100, 3))
        yield chunk("的", usage=u(100, 4))
        yield chunk(choices=False, usage=u(100, 4))
    return gen()
llm.client.chat.completions.create = fake_create

async def usage_rows():
    async with SessionLocal() as db:
        return (await db.execute(select(UsageRecord))).scalars().all()

async def clear_usage():
    async with SessionLocal() as db:
        await db.execute(delete(UsageRecord)); await db.commit()

async def collect():
    return [x async for x in llm.stream_turn([{"role": "user", "content": "hi"}], model="fast")]

items = asyncio.run(collect())
assert seen_models[-1] == "step-3.7-flash", seen_models
assert [i.text for i in items if isinstance(i, Reasoning)] == ["先想", "一想"]
assert [i for i in items if isinstance(i, str)] == ["好", "的"]
assert isinstance(items[-1], Turn) and items[-1].text == "好的"
rows = asyncio.run(usage_rows())
assert len(rows) == 1 and rows[0].model == "fast" and rows[0].prompt_tokens == 100 and rows[0].completion_tokens == 4, rows

# 中途停止：已花的 token 也要记（只记一次）
async def stop_early():
    await clear_usage()
    g = llm.stream_turn([{"role": "user", "content": "hi"}], model="smart")
    async for x in g:
        if x == "好":
            break
    await g.aclose()
    return await usage_rows()
rows = asyncio.run(stop_early())
assert len(rows) == 1 and rows[0].model == "smart" and rows[0].completion_tokens == 3, rows
assert seen_models[-1] == "step-5-preview"

# WS：thinking.delta 发给客户端，回复块里没有思考内容
async def fake_stream_turn(messages, tools=None, model=None):
    yield Reasoning("让我想想")
    yield "答案"
    yield Turn(text="答案")
loop.stream_turn = fake_stream_turn
app = FastAPI()
for r in (rws.router, rc.router, rv.router):
    app.include_router(r)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
with c.websocket_connect(f"/ws?token={issue_token()}") as ws:
    ws.send_json({"type": "user.message", "text": "问题"})
    evs = []
    while True:
        e = ws.receive_json(); evs.append(e)
        if e["type"] in ("message.done", "error"):
            break
kinds = [e["type"] for e in evs]
assert {"type": "thinking.delta", "text": "让我想想"} in evs, evs
assert kinds.index("thinking.delta") < kinds.index("block.delta")
assert evs[-1]["message"]["blocks"] == [{"type": "text", "text": "答案"}]
async def stored():
    async with SessionLocal() as db:
        return [m.blocks for m in (await db.execute(select(Message).where(Message.role == "assistant"))).scalars()]
assert "让我想想" not in json.dumps(asyncio.run(stored()), ensure_ascii=False)

# ---- 4：语音 ----
assert voice.capabilities() == {"stt": True, "tts": "server"}
assert c.get("/api/voice/config").json() == {"stt": True, "tts": "server"}
assert voice.parse_sse('data: {"type":"x"}') == {"type": "x"}
for bad in ("", ": ping", "data: [DONE]", "data: {oops", "event: x", "data: [1]"):
    assert voice.parse_sse(bad) is None, bad
assert voice.tts_text("**好** 看 [链接](https://x) (轻声)\n```py\nx=1\n```") == "好 看 链接 （轻声） （代码略）"
assert len(voice.tts_text("字" * 5000)) == voice.TTS_MAX_CHARS

calls = []
def handler(req: httpx.Request):
    calls.append(req)
    assert req.headers["authorization"] == "Bearer sk-step"
    if req.url.path.endswith("/audio/asr/sse"):
        body = json.loads(req.content)
        calls[-1].body = body
        sse = ('data: {"type":"transcript.text.delta","delta":"明天"}\n\n'
               'data: {"type":"transcript.text.delta","delta":"八点"}\n\n'
               'data: {"type":"transcript.text.done","text":"明天 8 点","usage":{"input_tokens":90,"output_tokens":16}}\n\n')
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
    if req.url.path.endswith("/audio/speech"):
        calls[-1].body = json.loads(req.content)
        return httpx.Response(200, content=b"ID3fake", headers={"content-type": "audio/mpeg"})
    return httpx.Response(404)
_Real = httpx.AsyncClient
httpx.AsyncClient = lambda **kw: _Real(transport=httpx.MockTransport(handler), **kw)

asyncio.run(clear_usage())
r = c.post("/api/voice/transcribe", files={"file": ("v.mp3", b"\xff\xfbfake", "audio/mpeg")})
assert r.status_code == 200 and r.json() == {"text": "明天 8 点"}, r.text
fmt = calls[-1].body["audio"]["input"]
assert fmt["format"] == {"type": "mp3"} and fmt["transcription"]["model"] == "stepaudio-2.5-asr"
assert base64.b64decode(calls[-1].body["audio"]["data"]) == b"\xff\xfbfake"
rows = asyncio.run(usage_rows())
assert [(x.model, x.kind, x.prompt_tokens, x.completion_tokens) for x in rows] == [("stepaudio-2.5-asr", "stt", 90, 16)]

if shutil.which("ffmpeg"):  # App 录的 m4a → 转 16k 单声道 wav 再发
    m4a = os.path.join(tempfile.mkdtemp(), "v.m4a")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
                    "-c:a", "aac", m4a], check=True)
    r = c.post("/api/voice/transcribe", files={"file": ("voice-1.m4a", open(m4a, "rb").read(), "audio/mp4")})
    assert r.status_code == 200, r.text
    assert calls[-1].body["audio"]["input"]["format"] == {"type": "wav"}
    wav = base64.b64decode(calls[-1].body["audio"]["data"])
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    r = c.post("/api/voice/transcribe", files={"file": ("x.webm", b"not audio", "audio/webm")})
    assert r.status_code == 503 and "无法识别" in r.json()["detail"], r.text
else:
    print("（跳过 ffmpeg 转码检查：本机没有 ffmpeg）")

r = c.post("/api/voice/speak", json={"text": "**你好**"})
assert r.status_code == 200 and r.content == b"ID3fake" and r.headers["content-type"] == "audio/mpeg"
assert calls[-1].body == {"model": "stepaudio-2.5-tts", "voice": "elegantgentle-female", "input": "你好", "response_format": "mp3"}
assert c.post("/api/voice/speak", json={"text": "  **  "}).status_code == 422

from app.config import settings
settings.voice_provider = "gateway"
assert c.get("/api/voice/config").json() == {"stt": True, "tts": "device"}
assert c.post("/api/voice/speak", json={"text": "你好"}).status_code == 503
print("smoke_stepfun OK")
