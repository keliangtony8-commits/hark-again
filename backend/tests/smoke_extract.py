# 冒烟：v2.07 大脑 (as) 结构化提取 extract_data（app/extract.py + agent/builtin/extract.py）。模拟模型，无迁移。
# - 规则：schema 检查（坏 JSON / 根类型 / 不合法 / 太大 / 2020-12 选校验器）、clean（围栏、前后闲话）、parse 错误、
#   校验错误路径、切块（空行处切、拼回原文、超 SOURCE_MAX 标 partial）、合并（数组拼接去重、对象取第一个非空）、count/detail；
# - run：第一次带围栏且类型不对 → 带错误修一次就过；一直不合法 → 交回 None + 原因；保留错误最少的一次；多段并发合并；
# - web_page limit：长正文按 limit 给全、普通 web_fetch 仍截断、缓存里的短版满足不了长 limit 时现读；
# - 一轮对话：deferred_tool call extract_data(path, save_to) → 便宜模型读到原文、主模型没读到、结果符合 schema、落盘、
#   时间线 detail、用量记成 extract；对话来源；HTML 文件；两个来源 / 内网网址 / 覆盖没读过的文件 → 说清楚。
# 运行：python tests/smoke_extract.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai")
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from sqlalchemy import select
from app import extract as ex, llm, web_page, workspaces
from app.agent import deferred, runner, subagent
from app.agent.tools import REGISTRY, load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message, UsageRecord
from app.storage import project_dir

load_builtin()
T = REGISTRY["extract_data"]
assert T.deferred and "extract_data" in subagent.CHILD_TOOLS
assert T.parallel({}) and not T.parallel({"save_to": "a.json"})

ITEMS = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object", "properties": {"name": {"type": "string"}, "price": {"type": "number"}},
    "required": ["name", "price"]}}}, "required": ["items"]}

# --- 规则 ---
def refused(schema, part):
    try:
        ex.check_schema(schema)
    except ex.ExtractError as e:
        assert part in str(e), (part, str(e))
        return
    raise AssertionError(f"应拒绝 {schema!r}")
refused("{bad", "不是合法 JSON")
refused([1], "JSON 对象")
refused({"type": "string"}, "根 type")
refused({"type": "object", "properties": {"a": {"type": "strng"}}}, "schema 不合法")
refused({"type": "object", "description": "x" * (ex.SCHEMA_MAX + 1)}, "太大")
assert type(ex.check_schema(json.dumps(ITEMS))).__name__ == "Draft7Validator"
assert type(ex.check_schema({**ITEMS, "$schema": ex.DRAFT_2020})).__name__ == "Draft202012Validator"

assert ex.clean('```json\n{"a":1}\n```') == '{"a":1}'
assert ex.clean('好的，结果如下：\n{"a":[1]}\n希望有帮助') == '{"a":[1]}'
assert ex.clean('[{"a":1}] 完') == '[{"a":1}]'
v, err = ex.parse("没有")
assert v is None and "不是合法 JSON" in err
assert ex.parse("")[1] == "回复是空的"
V = ex.check_schema(ITEMS)
errs = ex.errors(V, {"items": [{"name": "a", "price": 1}, {"name": "b", "price": "12元"}, {"price": 3}]})
assert errs[0].startswith("$.items[1].price：") and "'12元' is not of type 'number'" in errs[0], errs
assert any(e.startswith("$.items[2]：") and "'name' is a required property" in e for e in errs), errs
many = ex.errors(V, {"items": [{"x": i} for i in range(10)]})
assert len(many) == ex.ERRORS_MAX + 1 and many[-1].startswith("……还有"), many

short, partial = ex.split("abc")
assert short == ["abc"] and not partial
para = ("一段文字。" * 400 + "\n\n")
long = para * 30
parts, partial = ex.split(long)
assert len(parts) > 1 and not partial and "".join(parts) == long
assert all(len(p) <= ex.CHUNK_CHARS for p in parts) and all(p.endswith("\n\n") for p in parts[:-1])
huge, partial = ex.split("x\n" * (ex.SOURCE_MAX // 2 + 100))
assert partial and len(huge) == ex.CHUNKS_MAX

assert ex.merge([[{"a": 1}], [{"a": 1}, {"a": 2}]], {"type": "array"}) == [{"a": 1}, {"a": 2}]
m = ex.merge([{"title": "", "items": [1, 2]}, {"title": "T", "items": [2, 3], "n": None}, {"n": 5}], {"type": "object"})
assert m == {"title": "T", "items": [1, 2, 3], "n": 5}, m
assert ex.merge([None, {"a": 1}], {"type": "object"}) == {"a": 1} and ex.merge([None], {"type": "object"}) is None
assert ex.count([1, 2]) == 2 and ex.count({"items": [1], "t": "x"}) == 1 and ex.count({"a": 1}) is None
r = ex.Result(value={"items": [1, 2]}, chunks=3)
assert ex.detail(r, "网页") == "网页 · 2 条 · 3 段"

# --- run ---
calls: list[list[dict]] = []
def fake(replies):
    async def call(msgs):
        calls.append(msgs)
        return replies.pop(0)
    return call
calls.clear()
res = asyncio.run(ex.run("苹果 12元，梨 5 元", "商品和价格", ITEMS, fake([
    '```json\n{"items":[{"name":"苹果","price":"12元"},{"name":"梨","price":5}]}\n```',
    '{"items":[{"name":"苹果","price":12},{"name":"梨","price":5}]}'])))
assert res.ok and res.attempts == 2 and res.value["items"][0]["price"] == 12, res
assert "苹果 12元" in calls[0][1]["content"] and calls[0][0]["content"] == ex.SYSTEM
fix = calls[1]
assert fix[-2]["role"] == "assistant" and "$.items[0].price：" in fix[-1]["content"], fix[-1]
assert ex.for_model(res).startswith("已提取，结果符合 schema。\n{")

calls.clear()
res = asyncio.run(ex.run("x", "y", ITEMS, fake(["抱歉", "还是不行", "不知道"])))
assert res.value is None and res.attempts == ex.ATTEMPTS and res.failed_chunks == 1 and not res.ok
assert ex.for_model(res).startswith("没提取成")
res = asyncio.run(ex.run("x", "y", ITEMS, fake([
    '{"items":[{"price":"a"},{"price":"b"}]}', '{"items":[{"name":"a","price":"1"}]}', "坏了"])))
assert res.value == {"items": [{"name": "a", "price": "1"}]} and len(res.errors) == 1 and "不符合" in ex.for_model(res)
for bad in ("", "x" * (ex.INSTRUCTION_MAX + 1)):
    try:
        asyncio.run(ex.run("x", bad, ITEMS, fake([])))
        raise AssertionError("应拒绝")
    except ex.ExtractError:
        pass
try:
    asyncio.run(ex.run("  ", "y", ITEMS, fake([])))
    raise AssertionError("空原文应拒绝")
except ex.ExtractError as e:
    assert "原文是空的" in str(e)

# 多段：每段只抽自己那段里的，合并去重
names = ["甲", "乙", "丙"]
src = "".join(f"商品{n} 价格 {i + 1}\n" + "填充。" * 7000 + "\n\n" for i, n in enumerate(names))
running, peak = 0, 0
async def by_chunk(msgs):
    global running, peak
    running += 1; peak = max(peak, running)
    await asyncio.sleep(0.01)
    running -= 1
    body = msgs[1]["content"]
    found = [{"name": n, "price": i + 1} for i, n in enumerate(names) if f"商品{n}" in body]
    return json.dumps({"items": found + [{"name": "甲", "price": 1}]}, ensure_ascii=False)
res = asyncio.run(ex.run(src, "商品", ITEMS, by_chunk))
assert res.ok and res.chunks >= 3 and [i["name"] for i in res.value["items"]] == names, res.value
assert 1 < peak <= ex.PARALLEL, peak
print("规则 / run ok：", res.chunks, "段，并发", peak)

# --- web_page limit ---
downloads = []
BODY = ("第一行\n" + "长正文。" * 30000).encode()
async def fake_download(url, transport):
    downloads.append(url)
    return BODY, "text/plain; charset=utf-8", url, 200, False
web_page._download = fake_download
async def resolve_public(host):
    return ["93.184.216.34"]
import app.web_guard as wg
wg.resolve = resolve_public
async def pages():
    a = await web_page.fetch("https://example.com/a")
    b = await web_page.fetch("https://example.com/a", limit=ex.SOURCE_MAX)
    c = await web_page.fetch("https://example.com/a")
    d = await web_page.fetch("https://example.com/a", limit=ex.SOURCE_MAX)
    return a, b, c, d
a, b, c, d = asyncio.run(pages())
assert len(a.text) == web_page.MAX_CHARS and a.truncated
assert len(b.text) == len(BODY.decode()) and not b.truncated and not b.cached   # 短版不够 → 现读
assert c.cached and len(c.text) == web_page.MAX_CHARS and c.truncated          # 长版缓存给普通读取仍截断
assert d.cached and len(d.text) == len(BODY.decode())
assert len(downloads) == 2, downloads

# --- 一轮对话 ---
script: list = []
history: list[list[dict]] = []
tool_msgs: list[dict] = []
helper: list[list[dict]] = []
helper_replies: list[str] = []
helper_by: list[tuple[str, str]] = []   # 并行调用时按原文内容回（顺序不定）
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    messages = [dict(m) for m in messages]
    if not stream:
        if messages and messages[0].get("content") == ex.SYSTEM:
            helper.append(messages)
            body = messages[1]["content"]
            text = next((r for k, r in helper_by if k in body), None) or helper_replies.pop(0)
        else:
            text = "标题"
        return NS(choices=[NS(message=NS(content=text), finish_reason="stop")],
                  usage=NS(prompt_tokens=100, completion_tokens=20))
    history.append(messages)
    tool_msgs.extend(m for m in messages if m["role"] == "tool" and m not in tool_msgs)
    step = script.pop(0)
    rnd = len(script)
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"t{len(history)}_{rnd}_{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create

async def turn(cid, text, steps):
    script.extend(steps)
    async with SessionLocal() as db:
        conv = await db.get(Conversation, cid)
        if conv is None:
            conv = Conversation(id=cid, title="t"); db.add(conv); await db.commit()
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks(text)))
        await db.commit()
        return await runner.run_turn(db, conv)

ws = project_dir(workspaces.of(None))
ws.mkdir(parents=True, exist_ok=True)
(ws / "orders.txt").write_text("订单 A-1 苹果 12 元\n订单 A-2 梨 5 元\n", encoding="utf-8")
META = deferred.META
def call(args):
    return (META, {"action": "call", "tool": "extract_data", "arguments": args})

helper_replies[:] = ['{"items":[{"name":"苹果","price":"12"},{"name":"梨","price":5}]}',
                     '{"items":[{"name":"苹果","price":12},{"name":"梨","price":5}]}']
reply = asyncio.run(turn("c1", "把订单整理成 JSON", [
    [call({"instruction": "每个商品和价格", "schema": ITEMS, "path": "orders.txt", "save_to": "out/orders.json"})],
    "整理好了。"]))
st = reply.steps
assert len(st) == 1 and st[0]["tool"] == "extract_data" and st[0]["state"] == "done", st
assert st[0].get("detail") == "文件 · 2 条", st[0]
assert "订单 A-1 苹果 12 元" in helper[0][1]["content"] and len(helper) == 2
assert not any("订单 A-1" in json.dumps(m, ensure_ascii=False) for m in history[0])   # 原文没进主模型
out = tool_msgs[0]["content"]
assert out.startswith("已提取，结果符合 schema。") and "已存到 out/orders.json" in out, out
saved = json.loads((ws / "out/orders.json").read_text(encoding="utf-8"))
assert saved == {"items": [{"name": "苹果", "price": 12}, {"name": "梨", "price": 5}]}
async def kinds():
    async with SessionLocal() as db:
        return [k for (k,) in (await db.execute(select(UsageRecord.kind))).all()]
assert asyncio.run(kinds()).count("extract") == 2

# 对话来源 + HTML 文件 + 错误来源 + 覆盖没读过的文件
(ws / "page.html").write_text("<html><head><title>价目</title></head><body><article><h1>价目表</h1>"
                              "<p>西瓜每斤三块钱，今天特价，欢迎选购新鲜水果。</p><p>香蕉每斤四块钱，产地海南，口感香甜。</p>"
                              "</article></body></html>", encoding="utf-8")
(ws / "keep.json").write_text("{}", encoding="utf-8")
helper.clear(); tool_msgs.clear()
helper_by[:] = [("芒果", '{"items":[{"name":"芒果","price":8}]}'), ("西瓜", '{"items":[{"name":"西瓜","price":3}]}'),
                ("x 1 元", '{"items":[{"name":"x","price":1}]}')]
reply = asyncio.run(turn("c1", "我还想买芒果，8 块一个", [
    [call({"instruction": "提到的商品", "schema": ITEMS, "conversation": True}),
     call({"instruction": "价目", "schema": ITEMS, "path": "page.html"}),
     call({"instruction": "x", "schema": ITEMS, "text": "a", "url": "https://example.com"}),
     call({"instruction": "x", "schema": ITEMS, "url": "http://127.0.0.1:8000/admin"}),
     call({"instruction": "x", "schema": {"type": "string"}, "text": "a"})],
    [call({"instruction": "x", "schema": ITEMS, "text": "x 1 元", "save_to": "keep.json"})],
    "好"]))
conv_src = next(h for h in helper if "芒果" in h[1]["content"])[1]["content"]
assert "用户：把订单整理成 JSON" in conv_src and "助手：整理好了。" in conv_src and "用户：我还想买芒果" in conv_src
assert any("西瓜每斤三块钱" in h[1]["content"] for h in helper)
conv_out, html_out, two, inner, bad_schema, over = (m["content"] for m in tool_msgs[-6:])   # 前面是上一轮的工具轨迹
assert conv_out.startswith("已提取") and "芒果" in conv_out
assert html_out.startswith("已提取") and "西瓜" in html_out
assert "只能给一个" in two and "（现在给了 2 个）" in two
assert inner.startswith("没提取：") and "内网" in inner, inner
assert "根 type" in bad_schema
assert "没存成：" in over and json.loads((ws / "keep.json").read_text()) == {}, over   # 没读过不许覆盖
assert sum(1 for s in reply.steps if s["state"] == "error") == 3, [(s["tool"], s["state"]) for s in reply.steps]
print("smoke_extract ok")
