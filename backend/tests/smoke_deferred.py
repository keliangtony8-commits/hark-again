# 冒烟：v2.05 大脑 (ar) 按需加载的工具（agent/deferred.py + deferred_tool）。模拟模型，无迁移。
# - 工具列表：deferred=True 的不进 schemas，deferred_tool 带目录；目录只列当前可用的（无对话 → 没 share_conversation；
#   子助手白名单 → 只剩 analyze_video / search_transcript / restart_service，且 deferred_tool 不用写进白名单）；
#   没有可用的按需工具 → 不出 deferred_tool；开关关掉 → 全部直接给、没有 deferred_tool；同一上下文两次逐字相同；
# - 每次请求少多少 token（打印）；
# - unwrap：call 拆成目标调用（同 id、对象 / 字符串参数、没给参数 = {}）；不是 call / 工具不存在 / 不可用 / 参数类型不对 → 不拆；
# - search：名字命中优先、没命中给全部；summary 截断；
# - 一轮对话：list / describe 不进时间线；call save_skill → 时间线是 save_skill、技能真存了；历史里仍是 deferred_tool 那条、结果 id 对上；
#   参数写错第一次就附完整签名；不存在的工具给目录；arguments 不是对象 → describe；直接按名字调按需工具也执行；
#   计划模式：describe 可以，call publish_page 被拒（时间线 denied）。
# 运行：python tests/smoke_deferred.py
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

from app import llm, plan_mode, skills_store
from app.agent import deferred, runner, subagent, tool_args
from app.agent.compact import approx_tokens
from app.agent.tools import REGISTRY, ToolContext, load_builtin, schemas
from app.blocks import text_to_blocks
from app.config import settings
from app.db import SessionLocal
from app.llm import ToolCall
from app.models import Conversation, Message

load_builtin()
META = deferred.META
DEFERRED = {"save_attachment", "analyze_video", "search_transcript", "offer_on_home", "manage_home", "share_conversation", "request_env",
            "restart_service", "browser_upload", "browser_handoff", "save_skill", "publish_page", "extract_data"}
assert {n for n, t in REGISTRY.items() if t.deferred} == DEFERRED
assert META in plan_mode.READ_TOOLS and REGISTRY[META].quiet and REGISTRY[META].parallel

def names(ctx):
    return [s["function"]["name"] for s in schemas(ctx)]
def meta_desc(ctx):
    return next(s["function"]["description"] for s in schemas(ctx) if s["function"]["name"] == META)

# --- 工具列表 ---
full = ToolContext(db=None, project_id="p", conversation_id="c")
got = names(full)
assert META in got and not DEFERRED & set(got), got
d = meta_desc(full)
for n in DEFERRED:
    assert f"- {n}：" in d, n
assert schemas(full) == schemas(full)                                        # 逐字不变（提示缓存）
bare = ToolContext(db=None)
assert "share_conversation" not in meta_desc(bare) and "- save_skill：" in meta_desc(bare)
child = ToolContext(db=None, allow=subagent.CHILD_TOOLS, depth=1)
cn = names(child)
assert META in cn and META not in subagent.CHILD_TOOLS
cd = meta_desc(child)
assert "- analyze_video：" in cd and "- restart_service：" in cd and "offer_on_home" not in cd and "save_skill" not in cd
none = ToolContext(db=None, allow=frozenset({"read_file"}))
assert names(none) == ["read_file"]                                          # 没有可用的按需工具 → 不出目录
on = approx_tokens(json.dumps(schemas(full), ensure_ascii=False))
settings.defer_tools = False
off_names = names(full)
assert META not in off_names and DEFERRED - {"share_conversation"} <= set(off_names) | {"share_conversation"}
assert "save_skill" in off_names and "share_conversation" in off_names
off = approx_tokens(json.dumps(schemas(full), ensure_ascii=False))
settings.defer_tools = True
print(f"每次请求的工具段：{off} → {on} token（省 {off - on}）")
assert off - on > 1000

# --- unwrap ---
def P(a):
    return tool_args.parse(json.dumps(a, ensure_ascii=False))
c = ToolCall("x1", META, "")
r = deferred.unwrap(c, P({"action": "call", "tool": "save_skill", "arguments": {"name": "a", "description": "b", "body": "c"}}), full)
assert r and r[0].id == "x1" and r[0].name == "save_skill" and r[1].args == {"name": "a", "description": "b", "body": "c"}
r = deferred.unwrap(c, P({"action": "call", "tool": " manage_home ", "arguments": '{"action": "list"}'}), full)
assert r and r[0].name == "manage_home" and r[1].args == {"action": "list"}
r = deferred.unwrap(c, P({"action": "call", "tool": "manage_home"}), full)
assert r and r[1].args == {}
r = deferred.unwrap(c, P({"action": "call", "tool": "manage_home", "arguments": "{oops"}), full)
assert r and r[1].args is None                                               # 拆，由目标工具报解析错
assert deferred.unwrap(c, P({"action": "describe", "tool": "save_skill"}), full) is None
assert deferred.unwrap(c, P({"action": "call", "tool": "nope"}), full) is None
assert deferred.unwrap(c, P({"action": "call", "tool": META}), full) is None
assert deferred.unwrap(c, P({"action": "call", "tool": "save_skill", "arguments": [1]}), full) is None
assert deferred.unwrap(c, P({"action": "call", "tool": "save_skill"}), child) is None   # 子助手不能存技能
assert deferred.unwrap(ToolCall("x2", "read_file", "{}"), P({"action": "call"}), full) is None
assert deferred.unwrap(c, tool_args.Parsed(None, "坏了"), full) is None
r = deferred.unwrap(c, P({"action": "call", "tool": "read_file", "arguments": {"path": "a"}}), full)
assert r and r[0].name == "read_file"                                        # 普通工具也能经它调

# --- search / summary ---
vis = deferred.visible(full)
assert [t.name for t in deferred.search(vis, "video")][:1] == ["analyze_video"]
assert [t.name for t in deferred.search(vis, "字幕")][0] in ("analyze_video", "search_transcript")
assert deferred.search(vis, "zzzz") == vis and deferred.search(vis, "  ") == vis
assert all(len(deferred.summary(t)) <= deferred.SUMMARY_MAX + 1 for t in vis)

# --- 一轮对话 ---
script: list = []
tool_msgs: list[dict] = []
sent_tools: list[list[str]] = []
history: list[list[dict]] = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    messages = [dict(m) for m in messages]
    history.append(messages)
    sent_tools.append([t["function"]["name"] for t in tools or []])
    tool_msgs.extend(m for m in messages if m["role"] == "tool" and m not in tool_msgs)
    step = script.pop(0)
    rnd = len(script)
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"c{len(tool_msgs)}_{rnd}_{i}", function=NS(name=n, arguments=a if isinstance(a, str) else json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create

async def turn(cid, text, steps, mode=None):
    script.extend(steps)
    async with SessionLocal() as db:
        conv = await db.get(Conversation, cid)
        if conv is None:
            conv = Conversation(id=cid, title="t", **({"mode": mode} if mode else {})); db.add(conv); await db.commit()
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks(text)))
        await db.commit()
        return await runner.run_turn(db, conv)

SKILL = {"name": "周报格式", "description": "写周报时用", "body": "1. 先写结论"}
reply = asyncio.run(turn("c1", "记住我的周报格式", [
    [(META, {"action": "list", "query": "技能"}), (META, {"action": "describe", "tool": "save_skill"})],
    [(META, {"action": "call", "tool": "save_skill", "arguments": SKILL})],
    "记好了。"]))
assert META in sent_tools[0] and "save_skill" not in sent_tools[0]
st = reply.steps
assert len(st) == 1 and st[0]["tool"] == "save_skill" and st[0]["state"] == "done", st   # list / describe 不进时间线
assert any(s.name == "周报格式" for s in skills_store.list_skills()), "技能没存上"
assert "- save_skill：" in tool_msgs[0]["content"] and tool_msgs[0]["content"].index("save_skill") < 40, tool_msgs[0]
assert '"required":["name","description","body"]' in tool_msgs[1]["content"]
assert "已保存技能「周报格式」" in tool_msgs[2]["content"]
last = history[-1]
call_msg = [m for m in last if m["role"] == "assistant" and m.get("tool_calls")][-1]
assert call_msg["tool_calls"][0]["function"]["name"] == META                   # 历史里是模型写的那条
assert last[-1]["role"] == "tool" and last[-1]["tool_call_id"] == call_msg["tool_calls"][0]["id"]

tool_msgs.clear()
reply = asyncio.run(turn("c2", "随便", [
    [(META, {"action": "call", "tool": "save_skill", "arguments": {"name": "x"}}),
     (META, {"action": "call", "tool": "fly_kite"}),
     (META, {"action": "call", "tool": "save_skill", "arguments": 5}),
     (META, {"action": "dance"})],
    [("manage_home", {"action": "list"}), ("save_skill", {"id": "weekly"})],   # 阶跃实测：没 describe 就按名字直接调、参数不全
    "好"]))
bad, unknown, notobj, act = (m["content"] for m in tool_msgs[:4])
assert "save_skill 的参数：" in bad and "- body（" in bad, bad                 # 第一次写错就给签名
assert "没有可用的工具 fly_kite" in unknown and "- publish_page：" in unknown
assert "arguments 要是参数对象" in notobj and "参数（JSON Schema）" in notobj
assert "action 只能是" in act
assert reply.steps and reply.steps[-1]["tool"] == "manage_home" and reply.steps[-1]["state"] == "done", reply.steps  # 直接按名字调
assert "save_skill 的参数：" in tool_msgs[5]["content"], tool_msgs[5]          # 直接调写错也第一次就给签名

tool_msgs.clear()
reply = asyncio.run(turn("c3", "计划一下发个网页", [
    [(META, {"action": "describe", "tool": "publish_page"}),
     (META, {"action": "call", "tool": "publish_page", "arguments": {"title": "t", "html": "<p>x</p>"}})],
    "先出方案。"], mode=plan_mode.PLAN))
assert "publish_page（" in tool_msgs[0]["content"]
assert "计划模式" in tool_msgs[1]["content"], tool_msgs[1]
assert reply.steps[0]["tool"] == "publish_page" and reply.steps[0]["state"] == "denied", reply.steps
print("smoke_deferred OK")
