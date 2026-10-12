# 冒烟：思考强度（app/reasoning.py，移植自 deepseek-harness 的 reasoning efforts 校验/默认，嫁接 Codex 按模型档位 + 子助手沿用、
# Gemini 后台小活少想）。一、配置校验 / 解析规则 / 拒绝识别；二、真的 llm.stream_turn / llm.complete（假的 create）：
# 发的档、没配的模型不发、后台最低档、压缩沿用、供应商拒收 → 去掉参数重发且之后不再发；三、整轮：WS 带 reasoning 记到对话、
# 沿用、"" 回默认、非法忽略、换模型后按新模型解析、重新生成带 reasoning；REST 列表/详情/PATCH（422、不改 updated_at）；
# GET /api/catalog/models 带 efforts；子助手沿用；迁移 down/up。
# 运行：python tests/smoke_reasoning.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速", "smart": "深度"}), DEFAULT_MODEL="fast",
  MODEL_REASONING=json.dumps({"smart": {"levels": ["low", "medium", "high"], "default": "medium"}, "fast": ["minimal", "low"]}),
  LLM_MAX_RETRIES="0")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

import httpx, openai
from app import llm, reasoning
from app.reasoning import ReasoningConfigError, _parse

# —— 一、规则 ——
for bad in ({"a": []}, {"a": ["low", "low"]}, {"a": ["turbo"]}, {"a": ["high", "low"]},
            {"a": {"levels": ["low"], "default": "high"}}, {"a": "high"}):
    try:
        _parse(bad)
        raise AssertionError(bad)
    except ReasoningConfigError:
        pass
assert _parse({"a": ["low", "high"]})["a"] == (("low", "high"), "high")      # 没 medium：取中间偏上那档
assert _parse({"a": ["low", "medium", "high"]})["a"][1] == "medium"
assert _parse({"a": ["minimal"]})["a"] == (("minimal",), "minimal")
assert reasoning.levels("smart") == ("low", "medium", "high") and reasoning.levels("nope") == ()
assert reasoning.resolve("smart", None) == "medium" and reasoning.resolve("smart", "high") == "high"
assert reasoning.resolve("smart", "minimal") == "medium"   # 这个模型没有这档：回默认，不报错（存下来的偏好）
assert reasoning.resolve("fast", "high") == "low" and reasoning.resolve("fast", "minimal") == "minimal"
assert reasoning.resolve("other", "high") is None           # 没配：不发
assert reasoning.for_helper("smart") == "low" and reasoning.for_helper("other") is None
assert reasoning.valid("xhigh") and not reasoning.valid("turbo") and not reasoning.valid(None) and not reasoning.valid(3)
assert reasoning.kwargs("high") == {"reasoning_effort": "high"} and reasoning.kwargs(None) == {}
cat = reasoning.catalog("smart")
assert cat["effort"] == "medium" and [e["id"] for e in cat["efforts"]] == ["low", "medium", "high"]
assert cat["efforts"][2]["label"] == "高" and cat["efforts"][2]["description"] and reasoning.catalog("other") == {}

REQ = httpx.Request("POST", "http://x/chat/completions")
def bad_request(msg, code=400):
    cls = openai.BadRequestError if code == 400 else openai.UnprocessableEntityError
    return cls(msg, response=httpx.Response(code, request=REQ), body={"error": {"message": msg}})
assert reasoning.rejected(bad_request("Unrecognized request argument supplied: reasoning_effort"))
assert reasoning.rejected(bad_request("extra_forbidden: reasoning_effort", 422))
assert reasoning.rejected(bad_request("该模型不支持 reasoning_effort 参数"))
assert not reasoning.rejected(bad_request("messages too long"))
assert not reasoning.rejected(bad_request("invalid messages[2].content"))
assert not reasoning.rejected(openai.RateLimitError("reasoning_effort unsupported", response=httpx.Response(429, request=REQ), body=None))
print("ok: rules")

# —— 二、真的 stream_turn / complete，假的 create ——
sent: list[dict] = []
reject_for: set[str] = set()

def chunk(text=None, finish=None, usage=None):
    return NS(choices=[NS(delta=NS(content=text, tool_calls=None, model_extra={}), finish_reason=finish)] if text or finish else [],
              usage=usage)

async def fake_create(**kw):
    sent.append(kw)
    if "reasoning_effort" in kw and kw["model"] in reject_for:
        raise bad_request("Unrecognized request argument supplied: reasoning_effort")
    if kw.get("stream"):
        async def gen():
            yield chunk("好")
            yield chunk(finish="stop")
            yield chunk(usage=NS(prompt_tokens=3, completion_tokens=1))
        return gen()
    return NS(choices=[NS(message=NS(content="摘要"), finish_reason="stop")], usage=NS(prompt_tokens=3, completion_tokens=1))
llm.client.chat.completions.create = fake_create

async def stream(model, effort=None):
    async for item in llm.stream_turn([{"role": "user", "content": "x"}], None, model, effort):
        last = item
    return last

asyncio.run(stream("smart", "high"))
assert sent[-1]["reasoning_effort"] == "high" and sent[-1]["model"] == "smart"
asyncio.run(stream("smart"))
assert sent[-1]["reasoning_effort"] == "medium"
asyncio.run(stream("other", "high"))
assert "reasoning_effort" not in sent[-1]
asyncio.run(llm.complete([{"role": "user", "content": "x"}], model="smart"))
assert sent[-1]["reasoning_effort"] == "low"                       # 后台小活：最低档
asyncio.run(llm.complete([{"role": "user", "content": "x"}], model="smart", effort="high", helper=False))
assert sent[-1]["reasoning_effort"] == "high"                      # 上文压缩：沿用这一轮
asyncio.run(llm.complete([{"role": "user", "content": "x"}], model="smart", helper=False))
assert sent[-1]["reasoning_effort"] == "medium"

reject_for.add("fast")
n = len(sent)
t = asyncio.run(stream("fast", "low"))
assert t.text == "好" and len(sent) == n + 2 and "reasoning_effort" in sent[n] and "reasoning_effort" not in sent[n + 1]
assert reasoning.levels("fast") == () and reasoning.catalog("fast") == {}       # 记住了：本进程不再给这个档位
asyncio.run(stream("fast", "low"))
assert len(sent) == n + 3 and "reasoning_effort" not in sent[-1]
reasoning.reload()
reject_for.clear()

async def boom(**kw):
    raise bad_request("messages too long")
llm.client.chat.completions.create = boom
try:
    asyncio.run(stream("smart", "high"))
    raise AssertionError("should raise")
except openai.BadRequestError:
    pass
assert reasoning.levels("smart")                                     # 别的 400 不算拒收
llm.client.chat.completions.create = fake_create
print("ok: llm")

# —— 三、整轮 + REST ——
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.agent import loop, subagent
from app.agent.tools import ToolContext
from app.auth import issue_token, require_user
from app.db import SessionLocal
from app.llm import Turn
from app.models import Conversation
from app.routes import catalog as rcat, conversations as rc, ws as rws

used: list[tuple] = []
async def fake_stream_turn(messages, tools=None, model=None, effort=None):
    used.append((model, reasoning.resolve(model or "fast", effort)))
    yield "好"
    yield Turn(text="好")
loop.stream_turn = fake_stream_turn

app = FastAPI()
for rt in (rws.router, rc.router, rcat.router):
    app.include_router(rt)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
token = issue_token()

def turn(ws, event):
    ws.send_json(event)
    while True:
        e = ws.receive_json()
        if e["type"] == "message.start":
            start = e
        if e["type"] in ("message.done", "error"):
            return start, e

async def stored(cid):
    async with SessionLocal() as db:
        cv = await db.get(Conversation, cid)
        return cv.model, cv.reasoning

models = c.get("/api/catalog/models").json()["models"]
assert models[1]["id"] == "smart" and models[1]["effort"] == "medium" and len(models[1]["efforts"]) == 3
assert [e["id"] for e in models[0]["efforts"]] == ["minimal", "low"]

with c.websocket_connect(f"/ws?token={token}") as ws:
    s, _ = turn(ws, {"type": "user.message", "text": "难题", "model": "smart", "reasoning": "high"})
    cid = s["conversation_id"]
    assert used[-1] == ("smart", "high") and asyncio.run(stored(cid)) == ("smart", "high")
    turn(ws, {"type": "user.message", "text": "接着", "conversation_id": cid})              # 沿用
    assert used[-1] == ("smart", "high")
    turn(ws, {"type": "user.message", "text": "x", "conversation_id": cid, "reasoning": "turbo"})  # 非法：忽略
    assert asyncio.run(stored(cid)) == ("smart", "high")
    turn(ws, {"type": "user.message", "text": "x", "conversation_id": cid, "model": ""})   # 换回快速：high → fast 的默认
    assert used[-1] == ("fast", "low") and asyncio.run(stored(cid)) == (None, "high")
    turn(ws, {"type": "user.message", "text": "x", "conversation_id": cid, "reasoning": ""})
    assert asyncio.run(stored(cid)) == (None, None) and used[-1] == ("fast", "low")
    _, done = turn(ws, {"type": "user.message", "text": "再来", "conversation_id": cid})
    turn(ws, {"type": "message.regenerate", "conversation_id": cid, "message_id": done["message"]["id"],
              "model": "smart", "reasoning": "low"})
    assert used[-1] == ("smart", "low") and asyncio.run(stored(cid)) == ("smart", "low")

lst = {x["id"]: x for x in c.get("/api/conversations").json()}
assert lst[cid]["reasoning"] == "low"
before = lst[cid]["updated_at"]
assert c.patch(f"/api/conversations/{cid}", json={"reasoning": "turbo"}).status_code == 422
rr = c.patch(f"/api/conversations/{cid}", json={"reasoning": "high"}).json()
assert rr["reasoning"] == "high" and rr["updated_at"] == before
rr = c.patch(f"/api/conversations/{cid}", json={"reasoning": ""}).json()
assert rr["reasoning"] is None and c.get(f"/api/conversations/{cid}").json()["reasoning"] is None
rr = c.patch(f"/api/conversations/{cid}", json={"model": "smart", "reasoning": "xhigh"}).json()  # 认识但 smart 没有：存下，解析回默认
assert rr["reasoning"] == "xhigh" and reasoning.resolve("smart", "xhigh") == "medium"
print("ok: turns + rest")

# 子助手沿用父级的选择（Codex child_config）
import time
seen_ctx = {}
async def fake_run(system, history, ctx, builder=None, model=None, limits=None):
    seen_ctx.update(effort=ctx.effort, model=ctx.model, passed=model)
    if False:
        yield None
orig = loop.run
loop.run = fake_run
try:
    asyncio.run(subagent._child(ToolContext(db=None, model="smart", effort="high"), subagent.Task(title="a", prompt="p"),
                                lambda: None, time.monotonic() + 30))
finally:
    loop.run = orig
assert seen_ctx == {"effort": "high", "model": "smart", "passed": "smart"}, seen_ctx
print("ok: subagent inherits")

for step in ("downgrade", "upgrade"):
    rv = subprocess.run([sys.executable, "-m", "alembic", step, "-1" if step == "downgrade" else "head"], cwd=root,
                        capture_output=True, text=True)
    assert rv.returncode == 0, rv.stderr
print("ok: migration")
print("all ok")
