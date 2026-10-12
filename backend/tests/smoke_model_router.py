# 冒烟：自动选模型（app/model_router.py，移植自 Gemini CLI routing）。模拟模型（不打真接口）。
# 一、规则：寒暄 → 简单；代码块 / 堆栈 / 很长 → 复杂；“继续”沿用上一轮（没有上一轮 → 不定）；图片 + 简单档看不了图 → 复杂；
#    系统事件沿用；分类器回复解析（Gemini 测试：非 JSON / 缺字段 / 枚举外 → None）；上文挑选（去工具、取最后 4 条、截断、不含这一问）。
# 二、route：override 零调用；auto 模式规则拿不准才问分类器（kind=router、最便宜别名、最低档）；分类器报错 / 超时 / 答非所问 → 默认复杂档；
#    rules 模式零调用；off → 不可选、目录里没有、存着的 auto 回落 default_model；router_default。
# 三、整轮（WebSocket）：选 auto → turn.model 事件在 message.done 之前、对话记下 routed_model、stream_turn 用路由到的别名且思考强度 None；
#    “继续”沿用不问分类器；REST PATCH auto / 目录 auto 在最前 / 详情带 routed_model；任务能选 auto；迁移 down/up。
# 运行：python tests/smoke_model_router.py
import os, sys, asyncio, subprocess, tempfile
from types import SimpleNamespace as NS
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", LLM_MAX_RETRIES="0",
  MODEL_REASONING='{"smart": ["low", "medium", "high"]}', NEXT_SPEAKER_CHECK="off", AUTO_TITLE="false")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from app import llm, model_router as mr, task_store
from app.agent import loop
from app.auth import issue_token, require_user
from app.config import settings
from app.db import SessionLocal
from app.llm import Turn
from app.models import Conversation, UsageRecord
from app.routes import catalog as rcat, conversations as rc, ws as rws

S, C = settings.router_simple, settings.router_complex
assert (S, C) == ("fast", "smart") and mr.enabled() and mr.choosable("auto") and mr.choosable("fast") and not mr.choosable("x")

# —— 一、规则 ——
R = lambda t, prev=None, img=False, notice=False: mr.rules(t, [], prev, img, notice)
for t in ("你好", "谢谢！", "hi", "Thanks", "晚安~", "辛苦了"):
    d = R(t)
    assert d and d.model == S and d.complexity == mr.SIMPLE and d.source == "rules", t
for t in ("看看这个\n```py\nprint(1)\n```", "x" * 2001,
          'Traceback (most recent call last):\n  File "a.py", line 3, in <module>\nKeyError: 1',
          "报错了\n    at foo (src/a.js:12:5)"):
    d = R(t)
    assert d and d.model == C and d.complexity == mr.COMPLEX, t
for t in ("帮我查一下明天上海的天气", "你好，帮我订机票", "继续", "好的"):
    if t in ("继续", "好的"):
        assert R(t) is None                                                   # 没有上一轮：拿不准
        assert R(t, prev=S).model == S and R(t, prev=S).source == "sticky"   # 接话沿用
        assert R(t, prev=C).model == C and R(t, prev="other") is None       # 上一轮别名已不在两档里 → 不沿用
    else:
        assert R(t) is None, t
assert R("", img=True) is None                                              # 简单档能看图：图片不强制
settings.vision_models = ["smart"]
assert R("这是什么", img=True).model == C and R("这是什么", img=True).reason.startswith("带了图片")
settings.vision_models = ["fast", "smart"]
assert R("这张图", img=True) is None
assert R("[系统提示] 任务结束", notice=True) is None and R("x", prev=S, notice=True).model == S
assert mr.view("auto") == C and mr.view("fast") == "fast"

for raw, want in [
    ('{"reasoning": "一步", "model_choice": "simple"}', ("simple", "一步")),
    ('```json\n{"reasoning": "多步", "model_choice": "complex"}\n```', ("complex", "多步")),
    ('好的：{"reasoning":"r","model_choice":"simple"} 以上', ("simple", "r")),
    ("not json", None), ('{"reasoning": "r"}', None), ('{"model_choice": "simple"}', None),
    ('{"reasoning": "r", "model_choice": "pro"}', None), ('{"reasoning": 3, "model_choice": "simple"}', None),
    ("[1, 2]", None), ("", None), (None, None),
]:
    assert mr.parse(raw) == want, (raw, mr.parse(raw))

hist = [{"role": "user", "content": f"问{i}"} if i % 2 == 0 else {"role": "assistant", "content": f"答{i}"} for i in range(10)]
hist += [{"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]}, {"role": "tool", "tool_call_id": "1", "content": "结果"},
         {"role": "user", "content": "[系统提示] 内部"}, {"role": "assistant", "content": "长" * 900},
         {"role": "user", "content": [{"type": "text", "text": "这一问"}]}]
ctx = mr.context_for(hist)
assert [m["content"][:2] for m in ctx] == ["答7", "问8", "答9", "长长"], ctx
assert all(m["role"] in ("user", "assistant") for m in ctx) and not any("结果" in m["content"] or "系统提示" in m["content"] for m in ctx)
assert ctx[-1]["content"] == "长" * mr.TURN_MAX + "…" and ctx[0]["content"] == "答7" and "这一问" not in str(ctx)
assert mr.context_for([]) == [] and mr.context_for([{"role": "user", "content": "只有这一问"}]) == []
print("ok: rules")

# —— 二、route ——
calls: list[dict] = []
mode = {"reply": '{"reasoning": "查一次", "model_choice": "simple"}', "delay": 0.0, "error": False}


class FakeCompletions:
    async def create(self, **kw):
        calls.append(kw)
        if mode["delay"]:
            await asyncio.sleep(mode["delay"])
        if mode["error"]:
            raise RuntimeError("网关挂了")
        return NS(choices=[NS(message=NS(content=mode["reply"]), finish_reason="stop")],
                  usage=NS(prompt_tokens=400, completion_tokens=20, prompt_tokens_details=None))


llm.client = NS(chat=NS(completions=FakeCompletions()))


async def routes():
    calls.clear()
    d = await mr.route("smart", "随便", [])
    assert d.model == "smart" and d.source == "router/override" and not calls
    d = await mr.route("auto", "你好", [])
    assert d.model == S and d.source == "router/rules" and not calls
    d = await mr.route("auto", "明天上海天气怎么样", hist)
    assert d.model == S and d.source == "router/classifier" and d.reason == "查一次" and len(calls) == 1
    kw = calls[0]
    assert kw["model"] == llm.upstream(settings.summary_model) and kw["max_tokens"] == 200
    assert kw["messages"][0]["content"] == mr.CLASSIFIER_PROMPT and "明天上海天气怎么样" in kw["messages"][-1]["content"]
    assert len(kw["messages"]) == 2 + 4
    mode["reply"] = '{"reasoning": "要规划", "model_choice": "complex"}'
    assert (await mr.route("auto", "帮我规划日本十天行程", [])).model == C
    for setup in ({"error": True}, {"reply": "我觉得简单"}, {"delay": 0.3}):
        mode.update({"reply": '{"reasoning": "x", "model_choice": "simple"}', "error": False, "delay": 0.0, **setup})
        old = mr.TIMEOUT_S
        mr.TIMEOUT_S = 0.05
        d = await mr.route("auto", "帮我看看这个", [])
        mr.TIMEOUT_S = old
        assert d.model == C and d.source == "router/default", (setup, d)
    mode.update(error=False, delay=0.0, reply='{"reasoning": "x", "model_choice": "simple"}')
    n = len(calls)
    d = await mr.route("auto", "[系统提示] 后台任务结束", [], previous=None, notice=True)
    assert d.model == C and len(calls) == n                                   # 系统事件不问分类器
    settings.model_router = "rules"
    d = await mr.route("auto", "帮我看看这个", [])
    assert d.model == C and d.source == "router/default" and len(calls) == n  # 零调用
    settings.model_router = "off"
    assert not mr.enabled() and not mr.choosable("auto") and mr.catalog_entry() is None
    assert llm.chat_model("auto") == settings.default_model and all(m["id"] != "auto" for m in llm.chat_models()["models"])
    d = await mr.route("auto", "x", [])
    assert d.model == settings.default_model
    settings.model_router = "auto"
    settings.router_simple = "smart"                                          # 两档相同 → 不提供
    assert not mr.enabled()
    settings.router_simple = "nope"
    assert not mr.enabled()
    settings.router_simple = "fast"
    assert llm.chat_model(None) == settings.default_model
    settings.router_default = True
    assert llm.chat_model(None) == "auto" and llm.chat_models()["default"] == "auto"
    settings.router_default = False
    async with SessionLocal() as db:
        kinds = [u.kind for u in (await db.scalars(select(UsageRecord))).all()]
    assert "router" in kinds
asyncio.run(routes())
print("ok: route")

# —— 三、整轮 ——
used: list[tuple] = []


async def fake_stream_turn(messages, tools=None, model=None, effort=None):
    used.append((model, effort))
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
    got = []
    while True:
        e = ws.receive_json()
        got.append(e)
        if e["type"] in ("message.done", "error"):
            return got


async def stored(cid):
    async with SessionLocal() as db:
        cv = await db.get(Conversation, cid)
        return cv.model, cv.routed_model


models = c.get("/api/catalog/models").json()
assert models["models"][0] == {"id": "auto", "label": "自动", "auto": True, "routes": {"simple": "fast", "complex": "smart"}}
assert [m["id"] for m in models["models"]] == ["auto", "fast", "smart"] and models["default"] == "fast"

with c.websocket_connect(f"/ws?token={token}") as ws:
    calls.clear()
    mode["reply"] = '{"reasoning": "查一次", "model_choice": "simple"}'
    ev = turn(ws, {"type": "user.message", "text": "明天上海天气怎么样", "model": "auto", "reasoning": "high"})
    types = [e["type"] for e in ev]
    cid = ev[0]["conversation_id"]
    assert "turn.model" in types and types.index("turn.model") < types.index("message.done"), types
    tm = next(e for e in ev if e["type"] == "turn.model")
    assert tm["model"] == "fast" and tm["label"] == "快速" and tm["complexity"] == "simple" and tm["source"] == "router/classifier"
    assert used[-1] == ("fast", None) and asyncio.run(stored(cid)) == ("auto", "fast")
    n = len(calls)
    ev = turn(ws, {"type": "user.message", "text": "继续", "conversation_id": cid})
    tm = next(e for e in ev if e["type"] == "turn.model")
    assert tm["source"] == "router/sticky" and used[-1] == ("fast", None) and len(calls) == n   # 接话沿用，不问
    mode["reply"] = '{"reasoning": "要排查", "model_choice": "complex"}'
    turn(ws, {"type": "user.message", "text": "网站报错了，帮我查原因修好", "conversation_id": cid})
    assert used[-1] == ("smart", None) and asyncio.run(stored(cid)) == ("auto", "smart")
    ev = turn(ws, {"type": "user.message", "text": "换深度", "conversation_id": cid, "model": "smart", "reasoning": "high"})
    assert "turn.model" not in [e["type"] for e in ev] and used[-1] == ("smart", "high")   # 手选：不路由、不推事件

assert c.patch(f"/api/conversations/{cid}", json={"model": "auto"}).json()["model"] == "auto"
detail = c.get(f"/api/conversations/{cid}").json()
assert detail["model"] == "auto" and detail["routed_model"] == "smart"
settings.model_router = "off"
assert c.patch(f"/api/conversations/{cid}", json={"model": "auto"}).status_code == 422
try:
    task_store.model_choice("auto")
    raise AssertionError("off 时任务不该能选 auto")
except ValueError:
    pass
settings.model_router = "auto"
assert task_store.model_choice("auto") == "auto"
print("ok: turns")

for step in ("downgrade", "upgrade"):
    rv = subprocess.run([sys.executable, "-m", "alembic", step, "-1" if step == "downgrade" else "head"], cwd=root,
                        capture_output=True, text=True)
    assert rv.returncode == 0, rv.stderr
print("ok: migration")
print("all ok")
