# 冒烟：模型调用重试 + 备用模型（app/llm_retry.py，移植自 deepseek-harness retry-policy / llm-retry / transport 分类，MIT；
# 嫁接 Codex responses_retry 的“Retry-After 只定时长不加次数 + 告诉客户端正在重试”、Gemini retry.ts 的持续失败换备用模型）。
# 一、deepseek 的策略校验 / 退避用例翻译过来 + 分类表 + Retry-After 解析 + 给人看的话；
# 二、模拟模型（真的 llm.stream_turn，假的 client.chat.completions.create）整轮：限流两次后成功、流到一半断开（半截撤回不进回复也不回传）、
#    鉴权错不重试、重试用完抛出、换备用模型、额度用完直接换、空答复重试 / 用完照收、等待中被停止、WRAP_UP 不重复、llm.complete 重试、
#    runner 发 turn.retry 与说人话的错误、SDK 自带重试已关。
# 运行：python tests/smoke_llm_retry.py
import os, sys, asyncio, subprocess, tempfile, json, time
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai",
  CHAT_MODELS=json.dumps({"fast": "快速", "smart": "深度"}), DEFAULT_MODEL="smart",
  LLM_RETRY_INITIAL_MS="1", LLM_RETRY_MAX_MS="20", LLM_MAX_RETRIES="3")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

import httpx, openai
from app import llm, llm_retry
from app.llm_retry import Policy, Failure, classify, next_delay, local_delay, retry_after_ms, EmptyResponse
from app.config import settings
from app.agent import loop, runner
from app.agent.tools import ToolContext, ToolResult, tool, load_builtin
from app.db import SessionLocal
from app.models import Conversation, Message

# —— 一、单元 ——
p = Policy()
assert (p.max_retries, p.initial_ms, p.max_ms, p.jitter) == (5, 500, 10_000, 0.1)
assert p.codes == {"EMPTY_RESPONSE", "RATE_LIMIT", "SERVER", "TIMEOUT", "TRANSPORT"}
for bad in (dict(max_retries=-1), dict(max_retries=1.5), dict(initial_ms=0), dict(initial_ms=20, max_ms=10),
            dict(jitter=1.1), dict(jitter=-0.1), dict(codes=frozenset())):
    try:
        Policy(**bad)
        raise AssertionError(bad)
    except ValueError:
        pass
half = lambda: 0.5
assert local_delay(p, 1, half) == 500 and local_delay(p, 2, half) == 1000 and local_delay(p, 5, half) == 8000
assert local_delay(p, 6, half) == 10_000 and local_delay(p, 5000, half) == 10_000  # 指数封顶，不溢出
assert abs(local_delay(p, 1, lambda: 0) - 450) < 1e-9 and local_delay(p, 6, lambda: 1) == 10_000  # 抖动后也不超上限
assert local_delay(Policy(jitter=0), 3, lambda: 0.9) == 2000
rl = Failure("RATE_LIMIT")
assert next_delay(p, rl, 1, half) == 500 and next_delay(p, rl, 5, half) == 8000 and next_delay(p, rl, 6, half) is None
assert next_delay(p, Failure("AUTH"), 1) is None and next_delay(p, Failure("QUOTA"), 1) is None
assert next_delay(p, Failure("RATE_LIMIT", retry_after_ms=3000), 1) == 3000  # 供应商说等多久就等多久
assert next_delay(p, Failure("RATE_LIMIT", retry_after_ms=60_000), 1) is None  # 比上限还久：不等
assert next_delay(p, Failure("RATE_LIMIT", retry_after_ms=3000), 6) is None  # 不因为有 Retry-After 多给次数
assert next_delay(Policy(max_retries=0), rl, 1) is None
assert retry_after_ms("2") == 2000 and retry_after_ms("0.5") == 500 and retry_after_ms("0") is None
assert retry_after_ms("abc") is None and retry_after_ms(None) is None and retry_after_ms("-3") is None
assert abs(retry_after_ms("Wed, 21 Oct 2015 07:28:10 GMT", now=1445412480) - 10_000) < 1
assert retry_after_ms("Wed, 21 Oct 2015 07:28:00 GMT", now=1445412490) is None  # 已经过去
print("ok: policy")

REQ = httpx.Request("POST", "http://x/chat/completions")
def status_err(code, body=None, headers=None):
    resp = httpx.Response(code, request=REQ, headers=headers or {})
    cls = {400: openai.BadRequestError, 401: openai.AuthenticationError, 403: openai.PermissionDeniedError,
           404: openai.NotFoundError, 429: openai.RateLimitError}.get(code, openai.InternalServerError if code >= 500 else openai.APIStatusError)
    msg = (body or {}).get("error", {}).get("message", f"Error code: {code}")
    return cls(msg, response=resp, body=body)
def E(msg, type_="", code=""):
    return {"error": {"message": msg, "type": type_, "code": code}}
table = [
    (status_err(401, E("Incorrect API key")), "AUTH"),
    (status_err(403, E("forbidden")), "AUTH"),
    (status_err(402, E("pay")), "QUOTA"),
    (status_err(429, E("You exceeded your current quota", "insufficient_quota")), "QUOTA"),
    (status_err(429, E("账户余额不足")), "QUOTA"),
    (status_err(429, E("Rate limit reached")), "RATE_LIMIT"),
    (status_err(400, E("This model's maximum context length is 128000 tokens", "invalid_request_error", "context_length_exceeded")), "CONTEXT_WINDOW_EXCEEDED"),
    (status_err(400, E("输入长度超过模型最大上下文")), "CONTEXT_WINDOW_EXCEEDED"),
    (status_err(400, E("bad tool schema", "invalid_request_error")), "INVALID_REQUEST"),
    (status_err(413, E("payload too large")), "INVALID_REQUEST"),
    (status_err(404, E("model not found")), "HTTP_404"),
    (status_err(500, E("boom")), "SERVER"),
    (status_err(503, E("overloaded", "overloaded_error")), "SERVER"),
    (openai.APITimeoutError(request=REQ), "TIMEOUT"),
    (openai.APIConnectionError(request=REQ), "TRANSPORT"),
    (httpx.ReadTimeout("read timed out"), "TIMEOUT"),
    (httpx.RemoteProtocolError("peer closed connection without sending complete message body"), "TRANSPORT"),
    (openai.APIError("upstream error", request=REQ, body=E("upstream error", "server_error")), "SERVER"),
    (EmptyResponse("空"), "EMPTY_RESPONSE"),
    (ValueError("bug"), "UNKNOWN"),
    (KeyError("x"), "UNKNOWN"),
]
for e, want in table:
    assert classify(e).code == want, (e, classify(e), want)
f = classify(status_err(429, E("slow down"), {"retry-after": "7"}))
assert f.retry_after_ms == 7000 and f.status == 429
for text in ("context_length_exceeded", "context window exceeded", "This model's maximum context length is 8192",
             "prompt is too long for this model", "Request too large for the model's context window",
             "input exceeds the model's context length", "上下文长度超出限制"):
    assert llm_retry.is_context_exceeded(text), text
for text in ("rate limit exceeded", "the context of this request", "too many requests"):
    assert not llm_retry.is_context_exceeded(text), text
assert "密钥" in llm_retry.user_text(status_err(401, E("bad key"))) and "额度" in llm_retry.user_text(status_err(402, E("x")))
assert "太长" in llm_retry.user_text(status_err(400, E("maximum context length is 1")))
assert "重试了几次" in llm_retry.user_text(status_err(503, E("x"))) and "Error code" not in llm_retry.user_text(status_err(503, E("x")))
assert llm_retry.user_text(ValueError("oops")) == "模型调用失败：oops"
settings.model_fallbacks = {"smart": "fast", "fast": "fast"}
assert llm_retry.fallback_for("smart") == "fast" and llm_retry.fallback_for("fast") is None
assert llm_retry.fallback_for("smart", {"fast"}) is None and llm_retry.fallback_for(None) is None
settings.model_fallbacks = {}
assert llm.client.max_retries == 0 and llm.client.timeout.read == settings.llm_idle_seconds  # SDK 不再自己悄悄重试
print("ok: classify")

# —— 二、模拟模型整轮 ——
@tool("fake_step", "正在试", "测试用", {"type": "object", "properties": {}})
async def fake_step(ctx) -> ToolResult:
    return ToolResult("好了")
load_builtin()

script: list = []
calls: list[dict] = []
def chunk(text=None, tools=None, u=None):
    if text is None and tools is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tools))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    calls.append({"model": model, "messages": json.loads(json.dumps(messages, ensure_ascii=False)), "stream": stream})
    step = script.pop(0) if script else "收尾"
    if isinstance(step, BaseException):
        raise step
    if not stream:
        return NS(choices=[NS(message=NS(content=step), finish_reason="stop")], usage=None)
    async def gen():
        if isinstance(step, dict) and "break_after" in step:  # 流到一半断开
            for piece in step["break_after"]:
                yield chunk(piece)
            raise httpx.RemoteProtocolError("peer closed connection")
        if step == "TOOL":
            yield chunk(tools=[NS(index=0, id=f"t{len(calls)}", function=NS(name="fake_step", arguments="{}"))])
        elif step != "":
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=1))
    return gen()
llm.client.chat.completions.create = fake_create
n = 0

async def run(*steps, model=None, expect_error=None):
    global n
    n += 1
    script[:] = list(steps)
    calls.clear()
    evs: list = []
    async with SessionLocal() as db:
        db.add(Conversation(id=f"c{n}", title="t")); await db.commit()
        ctx = ToolContext(db=db, conversation_id=f"c{n}")
        try:
            async for e in loop.run("sys", [{"role": "user", "content": "你好"}], ctx, model=model):
                evs.append(e)
        except Exception as e:  # noqa: BLE001
            assert expect_error, e
            return evs, e, ctx
    assert not expect_error, "应当抛出"
    return evs, evs[-1], ctx

def retries(evs):
    return [e for e in evs if isinstance(e, loop.Retry)]
def text_of(done):
    return "".join(b.get("text", "") for b in done.blocks if b["type"] == "text")

async def main():
    # ① 限流两次后成功
    evs, done, _ = await run(status_err(429, E("slow")), status_err(503, E("busy")), "你好呀")
    rs = retries(evs)
    assert [(r.attempt, r.max, r.code) for r in rs] == [(1, 3, "RATE_LIMIT"), (2, 3, "SERVER")] and len(calls) == 3
    assert rs[0].reason == "模型那边限流了" and all(0 <= r.delay_ms <= 20 for r in rs)
    assert text_of(done) == "你好呀"
    print("ok: rate limit then success")

    # ② 流到一半断开：半截撤回（BlockUpdate 清空），重试的文字写进同一块；回复和下一次请求里都没有半截
    evs, done, _ = await run({"break_after": ["这是半", "截回答"]}, "完整回答")
    ups = [e for e in evs if isinstance(e, loop.BlockUpdate)]
    starts = [e for e in evs if isinstance(e, loop.BlockStart)]
    assert len(starts) == 1 and ups and ups[0].block == {"type": "text", "text": ""}
    assert done.blocks == [{"type": "text", "text": "完整回答"}]
    assert "半截" not in json.dumps(calls[1]["messages"], ensure_ascii=False)
    assert retries(evs)[0].code == "TRANSPORT"
    # 半截之后是工具调用：撤回后留下的空块不落库
    evs, done, _ = await run({"break_after": ["先说"]}, "TOOL", "做完了")
    assert [b["type"] for b in done.blocks if b["type"] == "text" and b["text"]] == ["text"] and text_of(done) == "做完了"
    b = loop.MessageBuilder(); b.text("A"); b.text("B")
    assert b.final() == [{"type": "text", "text": "AB"}]
    print("ok: mid-stream break rolled back")

    # builder.rollback：开着的旧块恢复原文；新开的块清空并保持打开
    b = loop.MessageBuilder(); b.text("前文")
    m = b.mark(); b.text("后来")
    evs2 = b.rollback(m)
    assert b.blocks == [{"type": "text", "text": "前文"}] and len(evs2) == 1 and b._text_open
    b.text("续上"); assert b.blocks == [{"type": "text", "text": "前文续上"}]
    b = loop.MessageBuilder(); b.add({"type": "file", "id": "f"})
    m = b.mark(); b.text("新块")
    assert len(b.rollback(m)) == 1 and b.blocks[-1] == {"type": "text", "text": ""} and b._text_open
    b.text("重来"); assert len(b.blocks) == 2 and b.blocks[-1]["text"] == "重来"
    assert loop.MessageBuilder().rollback((0, "", False)) == []
    print("ok: builder rollback")

    # ③ 鉴权错：不重试，原样抛出
    evs, err, _ = await run(status_err(401, E("bad key")), expect_error=True)
    assert isinstance(err, openai.AuthenticationError) and not retries(evs) and len(calls) == 1

    # ④ 一直 503：重试 3 次后抛出（共 4 次调用）
    evs, err, _ = await run(*[status_err(503, E("down"))] * 6, expect_error=True)
    assert isinstance(err, openai.InternalServerError) and len(retries(evs)) == 3 and len(calls) == 4
    # Retry-After 超过上限：不等，直接失败
    evs, err, _ = await run(status_err(429, E("wait"), {"retry-after": "120"}), expect_error=True)
    assert len(calls) == 1 and not retries(evs)
    print("ok: no-retry + exhausted")

    # ⑤ 备用模型：smart 一直 503 → 重试用完换 fast（次数清零），fast 成功；ctx.model 跟着换
    settings.model_fallbacks = {"smart": "fast"}
    evs, done, ctx = await run(*[status_err(503, E("down"))] * 4, "备用模型答的")
    rs = retries(evs)
    assert [r.fallback for r in rs] == [None, None, None, "fast"] and rs[-1].attempt == 0
    assert [c["model"] for c in calls] == ["smart"] * 4 + ["fast"] and text_of(done) == "备用模型答的" and ctx.model == "fast"
    # 备用也挂了：不会来回换，最后抛出
    evs, err, _ = await run(*[status_err(503, E("down"))] * 10, expect_error=True)
    assert [c["model"] for c in calls] == ["smart"] * 4 + ["fast"] * 4
    # 额度用完：不重试，直接换备用
    evs, done, _ = await run(status_err(429, E("insufficient balance", "insufficient_quota")), "换了")
    assert [r.fallback for r in retries(evs)] == ["fast"] and len(calls) == 2
    # 鉴权错不换（换了也一样错）
    evs, err, _ = await run(status_err(401, E("bad")), expect_error=True)
    assert len(calls) == 1
    settings.model_fallbacks = {}
    print("ok: fallback model")

    # ⑥ 空答复：重试后拿到；一直空就照收（不报错，回复为空）
    evs, done, _ = await run("", "终于说话了")
    assert retries(evs)[0].code == "EMPTY_RESPONSE" and text_of(done) == "终于说话了"
    evs, done, _ = await run("", "", "", "", "")
    assert len(retries(evs)) == 3 and done.blocks == [] and len(calls) == 4

    # ⑦ 等待中用户点停止：任务取消立刻生效，不再发请求
    settings.llm_retry_initial_ms, settings.llm_retry_max_ms = 5000, 10_000
    script[:] = [status_err(503, E("x")), "不该到这"]
    calls.clear()
    async def consume():
        async with SessionLocal() as db:
            db.add(Conversation(id="cstop", title="t")); await db.commit()
            async for _ in loop.run("sys", [{"role": "user", "content": "hi"}], ToolContext(db=db, conversation_id="cstop")):
                pass
    task = asyncio.create_task(consume())
    await asyncio.sleep(0.3)
    t0 = time.monotonic(); task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert time.monotonic() - t0 < 1 and len(calls) == 1
    settings.llm_retry_initial_ms, settings.llm_retry_max_ms = 1, 20
    print("ok: empty + stop during wait")

    # ⑧ 收尾那一步失败重试：WRAP_UP 不重复
    old = settings.agent_max_steps
    settings.agent_max_steps = 2
    evs, done, _ = await run("TOOL", status_err(500, E("x")), "交代进度")
    last = calls[-1]["messages"]
    assert sum(1 for m in last if m["role"] == "user" and str(m["content"]).startswith("[系统提示] 这一轮的步数")) == 1
    settings.agent_max_steps = old
    print("ok: wrap-up once")

    # ⑨ llm.complete：503 两次后成功；超长原样抛出不重试
    script[:] = [status_err(503, E("x")), status_err(502, E("x")), "摘要"]
    calls.clear()
    assert await llm.complete([{"role": "user", "content": "x"}]) == "摘要" and len(calls) == 3
    script[:] = [status_err(400, E("maximum context length is 10", code="context_length_exceeded"))]
    calls.clear()
    try:
        await llm.complete([{"role": "user", "content": "x"}])
        raise AssertionError
    except openai.BadRequestError:
        pass
    assert len(calls) == 1
    print("ok: complete retry")

    # ⑩ runner：turn.retry 上线（带备用模型的中文名），失败时说人话
    settings.model_fallbacks = {"smart": "fast"}
    wire: list[dict] = []
    async def emit(ev):
        wire.append(ev)
    async with SessionLocal() as db:
        db.add(Conversation(id="cr", title="t")); await db.commit()
        db.add(Message(conversation_id="cr", role="user", blocks=[{"type": "text", "text": "hi"}])); await db.commit()
        conv = await db.get(Conversation, "cr")
        script[:] = [status_err(429, E("slow")), *[status_err(503, E("x"))] * 3, "好的"]
        calls.clear()
        reply = await runner.run_turn(db, conv, emit)
        assert reply is not None and reply.blocks == [{"type": "text", "text": "好的"}]
        rt = [w for w in wire if w["type"] == "turn.retry"]
        assert rt[0] == {"type": "turn.retry", "attempt": 1, "max": 3, "delay_ms": rt[0]["delay_ms"], "reason": "模型那边限流了", "code": "RATE_LIMIT"}
        assert rt[-1]["fallback"] == "fast" and rt[-1]["fallback_label"] == "快速"
        settings.model_fallbacks = {}
        wire.clear()
        script[:] = [status_err(401, E("Incorrect API key provided"))]
        assert await runner.run_turn(db, conv, emit) is None
        err = [w for w in wire if w["type"] == "error"][0]["message"]
        assert err.startswith("模型密钥无效") and "Incorrect API key" in err
    print("ok: runner wire")
    print("ALL OK")

asyncio.run(main())
