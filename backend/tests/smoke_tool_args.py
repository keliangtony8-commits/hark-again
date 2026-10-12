# 冒烟：工具调用参数解析/修补/校验（app/agent/tool_args.py，移植自 deepseek-harness json-schema.ts checkValue，
# 嫁接 Gemini schemaValidator 宽松策略 + getToolSuggestion、Codex 把解析原因还给模型）。
# 一、deepseek validateJsonSchemaValue 用例（翻译成我们的中文文案）；二、宽松与嫁接关键字；三、parse 修补；
# 四、coerce / check；五、suggest / wire；六、模拟模型整轮：坏参数不执行、不审批、不进时间线，原因回给模型；
#     修补/修正/丢弃未知参数后照常执行并附提醒；历史里的坏 JSON 换成 {}；截断直说；工具名写错给建议；所有内置工具 schema 自检。
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from app import llm
from app.agent import loop, tool_args as ta
from app.agent.tools import ToolContext, ToolResult, tool, load_builtin, REGISTRY
from app.db import SessionLocal
from app.models import Conversation

V = ta.validate

# —— 一、deepseek 用例 ——
assert V({"type": "string"}, "x") == [] and V({"type": "number"}, 1.5) == [] and V({"type": "integer"}, 2) == []
assert V({"type": "boolean"}, True) == [] and V({"type": "null"}, None) == []
assert V({"type": "array", "items": {"type": "string"}}, ["x"]) == [] and V({"type": "object"}, {"x": 1}) == []
assert V({"type": "string"}, 1) == ["“arguments”应为字符串"]
assert V({"type": "number"}, "1") == ["“arguments”应为数字"]
assert V({"type": "number"}, float("nan")) == ["“arguments”应为数字"]
assert V({"type": "integer"}, 1.5) == ["“arguments”应为整数"]
assert V({"type": "integer"}, 2.0) == []  # Python 侧 2.0 是整数值（JSON 里 2.0 == 2）
assert V({"type": "boolean"}, "true") == ["“arguments”应为布尔值（true/false）"]
assert V({"type": "boolean"}, 1) == ["“arguments”应为布尔值（true/false）"] and V({"type": "integer"}, True) == ["“arguments”应为整数"]
assert V({"type": "null"}, 0) == ["“arguments”应为null"]
s = {"type": "string", "enum": ["a", "b"], "const": "a"}
assert V(s, "a") == [] and V(s, "c") == ['“arguments”只能是 ["a", "b"] 之一'] and V(s, "b") == ['“arguments”必须是 "a"']
open_ = {"type": "object", "required": ["file"], "properties": {
    "file": {"type": "string"},
    "nested": {"type": "object", "required": ["line"], "additionalProperties": False, "properties": {"line": {"type": "integer"}}}}}
assert V(open_, {"file": "a", "extra": [1], "nested": {"line": 2}}) == []
assert V(open_, {"nested": {"line": 1}}) == ["缺少必填参数“file”"]
assert V(open_, {"file": 1, "nested": {}}) == ["“file”应为字符串", "缺少必填参数“nested.line”"]
assert V(open_, {"file": "a", "nested": {"line": 1, "extra": True}}) == ["“nested.extra”不是可用的参数"]
assert V(open_, "x") == ["“arguments”应为对象"]
arr = {"type": "object", "properties": {"xs": {"type": "array", "items": {"type": "integer"}}}}
assert V(arr, {"xs": [1, 1.5]}) == ["“xs[1]”应为整数"] and V(arr, {"xs": "x"}) == ["“xs”应为数组"]
dis = {"oneOf": [{"type": "string"}, {"type": "integer"}]}
assert V(dis, "x") == [] and V(dis, None) == ["“arguments”要恰好符合 oneOf 里的一种写法（现在符合 0 种）"]
ov = {"oneOf": [{"type": "number"}, {"type": "integer"}]}
assert V(ov, 1) == ["“arguments”要恰好符合 oneOf 里的一种写法（现在符合 2 种）"] and V(ov, 1.5) == []
assert V({"type": "object", "properties": {"toString": {"type": "string"}}, "required": ["toString"]}, {}) == ["缺少必填参数“toString”"]
print("ok: deepseek validateJsonSchemaValue cases")

# —— 二、宽松 + 嫁接 ——
assert V({"type": "weird"}, 1) == [] and V({"format": "uri", "x-foo": 1}, 5) == [] and V("not a schema", 1) == []
assert V({"type": ["string", "null"]}, None) == [] and V({"type": ["string", "null"]}, 1) == ["“arguments”应为字符串或null"]
assert V({"anyOf": [{"type": "string"}, {"type": "integer"}]}, 1) == []
assert V({"anyOf": [{"type": "string"}]}, 1) == ["“arguments”不符合 anyOf 里的任何一种写法"]
assert V({"allOf": [{"type": "integer"}, {"minimum": 3}]}, 1) == ["“arguments”不能小于 3"]
assert V({"type": "integer", "minimum": 1, "maximum": 5}, 9) == ["“arguments”不能大于 5"]
assert V({"type": "array", "minItems": 1, "maxItems": 2}, []) == ["“arguments”至少要 1 项"]
assert V({"type": "array", "maxItems": 2}, [1, 2, 3]) == ["“arguments”最多 2 项"]
assert V({"type": "string", "maxLength": 2}, "abc") == ["“arguments”最多 2 个字"]
deep = {"type": "string"}
for _ in range(100):
    deep = {"type": "object", "properties": {"a": deep}}
v = "x"
for _ in range(100):
    v = {"a": v}
assert V(deep, v) == []  # 超过 MAX_DEPTH 不再往下查，也不爆栈
# 必填项给 null = 缺；可选项给 null 不查
assert V({"type": "object", "required": ["q"], "properties": {"q": {"type": "string"}}}, {"q": None}) == ["缺少必填参数“q”"]
assert V({"type": "object", "required": ["q"], "properties": {"q": {"type": ["string", "null"]}}}, {"q": None}) == []
assert V({"type": "object", "properties": {"n": {"type": "integer"}}}, {"n": None}) == []
print("ok: lenient + grafted keywords")

# —— 三、parse ——
p = ta.parse('{"a": 1}'); assert p.args == {"a": 1} and not p.repaired and not p.error
assert ta.parse("").args == {} and ta.parse(None).args == {} and ta.parse("  ").args == {}
p = ta.parse('```json\n{"a": 1}\n```'); assert p.args == {"a": 1} and p.repaired == "去掉了代码围栏"
p = ta.parse('{"a": 1} 好的，开始'); assert p.args == {"a": 1} and "多余的文字" in p.repaired
p = ta.parse('{"a": 1}{"a": 2}'); assert p.args == {"a": 1}
p = ta.parse(json.dumps(json.dumps({"path": "x"}))); assert p.args == {"path": "x"} and "编码成了字符串" in p.repaired
p = ta.parse("[1, 2]"); assert p.args is None and "JSON 对象" in p.error
p = ta.parse('"hello"'); assert p.args is None and "JSON 对象" in p.error
p = ta.parse("{'a': 1}"); assert p.args is None and "属性名要用双引号" in p.error and "第 2 个字符" in p.error
p = ta.parse('{"a": 1,\n "b" 2}'); assert p.args is None and "第 2 行" in p.error and "缺少冒号" in p.error
p = ta.parse('{"content": "很长很长'); assert p.args is None and "字符串没有结束引号" in p.error and "截断" in p.error
p = ta.parse('{"content": "很长很长', cut=True); assert p.args is None and p.error.startswith("参数被输出长度上限截断了")
assert ta.parse('{"a": 1}', cut=True).args == {"a": 1}  # 截断但 JSON 完整：照常
p = ta.parse('{"a": "x\ny"}'); assert p.args is None and "控制字符" in p.error
print("ok: parse + repairs")

# —— 四、coerce / check ——
S = {"type": "object", "required": ["path"], "properties": {
    "path": {"type": "string"}, "limit": {"type": "integer", "maximum": 50}, "ratio": {"type": "number"},
    "fixed": {"type": "boolean"}, "tags": {"type": "array", "items": {"type": "integer"}},
    "opts": {"type": "object", "properties": {"deep": {"type": "boolean"}}}}}
c = ta.check(S, {"path": "a", "limit": "5", "ratio": "0.5", "fixed": "TRUE", "tags": ["1", 2.0], "opts": '{"deep": "false"}'})
assert not c.error and c.args == {"path": "a", "limit": 5, "ratio": 0.5, "fixed": True, "tags": [1, 2], "opts": {"deep": False}}, c.args
assert c.notes and "修正了 7 处" in c.notes[0], c.notes
c = ta.check(S, {"path": 5}); assert "“path”应为字符串" in c.error  # 不把数字硬转成字符串
c = ta.check(S, {"path": "a", "limit": "五"}); assert "“limit”应为整数" in c.error
c = ta.check(S, {"path": "a", "limit": 2.5}); assert "“limit”应为整数" in c.error
c = ta.check(S, {"path": "a", "limit": "99"}); assert not c.error and c.args["limit"] == 99  # 软约束交给工具（截到上限）
c = ta.check({"type": "object", "properties": {"k": {"type": "string", "enum": ["a"]}, "xs": {"type": "array", "maxItems": 1}}},
             {"k": "z", "xs": [1, 2]}); assert not c.error  # enum/条数不在执行前拦
assert ta.validate({"type": "string", "enum": ["a"]}, "z", strict=False) == [] and ta.validate({"type": "string"}, 1, strict=False)
c = ta.check(S, {}); assert c.error.startswith("参数不对：缺少必填参数“path”") and c.error.endswith("请按这个工具的参数说明改好再调用。")
c = ta.check(S, {"path": "a", "bogus": 1, "x": 2}, accepts={"path", "limit"})
assert not c.error and c.args == {"path": "a"} and c.notes == ["忽略了不认识的参数：bogus、x"]
c = ta.check(S, {"path": "a", "bogus": 1}, accepts=None); assert c.args == {"path": "a", "bogus": 1} and not c.notes
c = ta.check(S, {"path": "a", "limit": None}); assert c.args == {"path": "a"} and not c.error  # 可选给 null = 没给
many = {"type": "object", "required": [f"k{i}" for i in range(12)], "properties": {}}
c = ta.check(many, {}); assert "还有 4 处" in c.error and c.error.count("缺少必填参数") == ta.VIOLATIONS_MAX
print("ok: coerce + check")

# —— 五、suggest / wire ——
names = ["read_file", "write_file", "edit_file", "list_files", "web_search", "run_command"]
assert ta.distance("kitten", "sitting") == 3 and ta.distance("", "abc") == 3
s = ta.suggest("readfile", names); assert s.startswith(' 是不是想用 "read_file"'), s
assert '"run_command"' in ta.suggest("run_commnad", names)
assert ta.suggest("zzzzzzzzzzzz", names) == ""
assert len(ta.suggest("file", ["a_file", "b_file", "c_file", "d_file"]).split("、")) == ta.SUGGEST_MAX
assert ta.wire(ta.parse('{"a":1}')) is None and ta.wire(ta.parse("{bad")) == "{}"
assert json.loads(ta.wire(ta.parse('```\n{"a": 1}\n```'))) == {"a": 1}
print("ok: suggest + wire")

# —— 六、整轮 ——
ran = []
@tool("fake_read", "正在读", "测试用", {"type": "object", "required": ["path"], "properties": {
    "path": {"type": "string"}, "limit": {"type": "integer"}}})
async def fake_read(ctx, path: str, limit: int = 10) -> ToolResult:
    ran.append(("read", path, limit, type(limit)))
    return ToolResult(f"读了 {path}（{limit} 行）")

@tool("fake_rm", "正在删", "测试用", {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}},
      risk=lambda a, ctx: f"删除 {a['path']}")  # 缺 path 时这里会 KeyError：校验必须在审批之前
async def fake_rm(ctx, path: str) -> ToolResult:
    ran.append(("rm", path))
    return ToolResult("删了")

script, saw = [], []
def chunk(text=None, tools=None, u=None, finish=None):
    if text is None and tools is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tools), finish_reason=finish)], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    saw.append(json.loads(json.dumps(messages, ensure_ascii=False)))
    step = script.pop(0) if script else "好了"
    async def gen():
        if isinstance(step, tuple) and step[0] == "cut":
            yield chunk(tools=[NS(index=0, id="cut1", function=NS(name=step[1], arguments=step[2]))], finish="length")
        elif isinstance(step, list):
            yield chunk(tools=[NS(index=i, id=f"c{len(saw)}_{i}", function=NS(name=n, arguments=a if isinstance(a, str) else json.dumps(a, ensure_ascii=False)))
                               for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=100, completion_tokens=0))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()
n = 0
asked = []

async def approve(i, title, detail):
    asked.append(title)
    return True

async def run(*steps):
    global n
    n += 1
    script[:] = list(steps); saw.clear(); ran.clear(); asked.clear()
    async with SessionLocal() as db:
        db.add(Conversation(id=f"c{n}", title="t")); await db.commit()
        evs = [e async for e in loop.run("sys", [{"role": "user", "content": "x"}],
                                         ToolContext(db=db, conversation_id=f"c{n}", approve=approve))]
    return evs

def tool_msgs(i=-1):
    return [m["content"] for m in saw[i] if m["role"] == "tool"]

def steps(evs):
    return [e for e in evs if isinstance(e, loop.ToolStatus)]

async def main():
    # 1) 缺必填 → 不执行、不进时间线；模型改好 → 执行
    evs = await run([("fake_read", {"limit": 3})], [("fake_read", {"path": "a.txt", "limit": 3})], "好")
    assert ran == [("read", "a.txt", 3, int)], ran
    assert tool_msgs()[0].startswith("参数不对：缺少必填参数“path”")
    assert {s.name for s in steps(evs)} == {"fake_read"}
    assert len([s for s in steps(evs) if s.state == "running"]) == 1  # 只有改好的那次进了时间线
    print("ok: missing required → back to model, not run")

    # 2) 围栏 + 字符串数字 + 未知参数：修好执行，附提醒；历史里写修后的 JSON
    evs = await run([("fake_read", '```json\n{"path": "b", "limit": "7", "encoding": "utf8"}\n```')], "好")
    assert ran == [("read", "b", 7, int)], ran
    t = tool_msgs()[0]
    assert t.startswith("读了 b（7 行）") and "去掉了代码围栏" in t and "忽略了不认识的参数：encoding" in t and "修正了 1 处" in t, t
    call = [m for m in saw[-1] if m["role"] == "assistant" and m.get("tool_calls")][0]["tool_calls"][0]
    assert json.loads(call["function"]["arguments"]) == {"path": "b", "limit": "7", "encoding": "utf8"}  # wire = 解析结果（未改写类型）
    print("ok: repaired + coerced + unknown dropped, notes appended")

    # 3) 坏 JSON：历史里换成 {}（下一轮请求必须是合法 JSON），原因带位置
    evs = await run([("fake_read", "{path: 'c'}")], "好")
    assert not ran and "属性名要用双引号" in tool_msgs()[0]
    call = [m for m in saw[-1] if m["role"] == "assistant" and m.get("tool_calls")][0]["tool_calls"][0]
    assert call["function"]["arguments"] == "{}"
    for req in saw:
        for m in req:
            for c in m.get("tool_calls") or []:
                json.loads(c["function"]["arguments"])
    print("ok: broken JSON → {} in history, reason with position")

    # 4) 截断
    evs = await run(("cut", "fake_read", '{"path": "d", "limit": 1, "content": "很长'), "好")
    assert not ran and tool_msgs()[0].startswith("参数被输出长度上限截断了")
    print("ok: cut → told to split")

    # 5) 写错工具名 → 建议
    evs = await run([("fake_raed", {"path": "e"})], "好")
    assert not ran and '是不是想用 "fake_read"' in tool_msgs()[0], tool_msgs()[0]
    print("ok: unknown tool → suggestion")

    # 6) 带审批的工具：参数坏了不弹审批卡、不 KeyError
    evs = await run([("fake_rm", {})], [("fake_rm", {"path": "f"})], "好")
    assert asked == ["删除 f"] and ran == [("rm", "f")], (asked, ran)
    assert tool_msgs()[0].startswith("参数不对")
    print("ok: invalid args never reach approval")

    # 7) 模型自带 grant/form 会被丢掉，不算“未知参数”提醒以外的错误
    evs = await run([("fake_read", {"path": "g", "grant": "rule"})], "好")
    assert ran == [("read", "g", 10, int)] and "忽略" not in tool_msgs()[0]
    print("ok: grant stripped silently")

    # 8) 所有内置工具：schema 都是对象、能被 validate 处理；schema 里的参数函数都收得下
    for t in REGISTRY.values():
        assert t.parameters.get("type") == "object", t.name
        assert ta.validate(t.parameters, {}) is not None
        if t.accepts is not None:
            assert set(t.parameters.get("properties", {})) <= t.accepts, t.name
    print(f"ok: {len(REGISTRY)} registered schemas")

asyncio.run(main())
print("smoke_tool_args: all ok")
