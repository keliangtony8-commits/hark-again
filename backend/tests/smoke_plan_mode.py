# 冒烟：计划模式（app/plan_mode.py + app/readonly_command.py，移植自 Gemini CLI 计划模式 / Codex plan 模板 / deepseek plan-mode）。模拟模型。
# 一、只读命令判定（Gemini commandSafety 用例 + 我们的规则：引号里的括号不误伤、重定向 / $ / 子 shell / 后台 / heredoc 不算）。
# 二、refusal 表：不在计划模式只拦 exit_plan_mode；计划模式放只读工具、拒写入类、run_command 看脚本、update_plan 专门一句；子助手不能交方案。
#    check_plan / heading / notice / lift_prompt / history_text。
# 三、整轮：计划模式下 write_file / 危险命令 / update_plan 被拒（文件没写、时间线 denied）、只读命令照跑、read_file 照读；
#    方案没标题 → 不弹卡；交方案 → 方案卡 → 批准 → 这一轮下一次请求系统提示里没有计划规则、接着 write_file 成功；
#    对话 mode=default、conversation.mode 事件在 message.done 之前；没批准 → 仍是 plan、卡 rejected、模型收到“问他改哪里”；
#    切换提示只说一次；普通模式下 exit_plan_mode 被拒且不弹卡；子助手在计划模式下也只读；历史里带方案原文。
# 四、REST / WebSocket：PATCH mode（非法 422、"" = default）、列表与详情带 mode、user.message 带 mode；迁移 down/up。
# 运行：python tests/smoke_plan_mode.py
import os, sys, asyncio, subprocess, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp,
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]', AUTO_TITLE="false",
  NEXT_SPEAKER_CHECK="off", MODEL_ROUTER="off")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
sys.path.insert(0, os.path.dirname(__file__))
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import llm, plan_mode as P, readonly_command as RC, sandbox_client, workspaces
from app.agent.runner import run_turn
from app.agent.tools import load_builtin, REGISTRY
from app.auth import issue_token, require_user
from app.blocks import blocks_to_text
from app.db import SessionLocal
from app.models import Conversation, Message
from app.routes import conversations as rc, ws as rws
from app.storage import project_dir
from fake_sandbox import streamed

# —— 一、只读命令 ——
ok = ["ls -la", "cat a.txt", "head -n 5 a.txt | wc -l", "grep -rn 'foo(' src", "find . -name '*.py'", "rg pattern src",
      "git status", "git -C repo log --oneline -5", "git diff HEAD~1", "git branch", "git branch -a", "git branch --show-current",
      "sed -n '1,20p' a.txt", "sed -n 5p a.txt", "pwd && ls; wc -c a.txt", "base64 a.bin", "cd sub && ls", "echo hi",
      "tree -L 2", "du -sh .", "sort a.txt | uniq -c", "jq . data.json", "diff a b", "ls\ncat a"]
bad = ["rm -rf x", "echo hi > a.txt", "cat a >> b", "ls $(pwd)", "ls `pwd`", "echo $HOME", "(ls)", "sleep 1 &",
       "cat <<EOF\nx\nEOF", "find . -delete", "find . -exec rm {} ;", "rg --pre=cat x", "rg -z x", "git -c core.pager=sh log",
       "git push", "git commit -m x", "git branch new", "git branch -D old", "git log --output=x", "sed -i s/a/b/ f",
       "sed -n '1,2p;w out' f", "sort -o out a", "sort --output=out a", "tree -o out", "python a.py", "npm test", "FOO=1 ls",
       "/bin/ls", "", "   ", "ls 'unclosed", "base64 -o out a", "base64 --output=x a", "xargs rm", "curl http://x", "ls | sh",
       "ls < a", "a=1", "date -s 2020-01-01"]
for s in ok:
    assert RC.is_read_only(s), s
for s in bad:
    assert not RC.is_read_only(s), s
assert RC.split("ls && cat a | head") == [["ls"], ["cat", "a"], ["head"]]
assert RC.valid_sed_n("10p") and RC.valid_sed_n("1,9p") and not RC.valid_sed_n("p") and not RC.valid_sed_n("1,p") and not RC.valid_sed_n("１p")
assert RC.find_git_subcommand(["git", "--git-dir=x", "-C", "d", "show"], RC.GIT_READ) == (4, "show")
assert RC.find_git_subcommand(["git", "push"], RC.GIT_READ) == (-1, None)
print("ok: readonly commands")

# —— 二、规则 ——
on, off, child = P.State(active=True), P.State(), P.State(active=True, can_exit=False)
assert P.refusal("write_file", {}, None) is None and P.refusal("write_file", {}, off) is None
assert P.refusal(P.TOOL, {}, None) == P.NOT_ACTIVE and P.refusal(P.TOOL, {}, off) == P.NOT_ACTIVE
for name in ("read_file", "grep", "glob", "web_search", "web_fetch", "browser_read", "delegate", "ask_user", "show_table", P.TOOL):
    assert P.refusal(name, {}, on) is None, name
for name in ("write_file", "edit_file", "apply_patch", "browser_click", "browser_type", "schedule_task", "remember", "host_command",
             "publish_page", "confirm_order", "cancel_job", "mcp_call", "api_request"):
    why = P.refusal(name, {}, on)
    assert why and "计划模式" in why and P.TOOL in why, name
assert "update_plan" in P.refusal("update_plan", {}, on)
assert P.refusal("run_command", {"command": "ls -la"}, on) is None
assert "只读命令" in P.refusal("run_command", {"command": "pip install x"}, on)
assert P.refusal(P.TOOL, {}, child) and P.refusal("read_file", {}, child) is None
registered = set(REGISTRY) if REGISTRY else set()
assert P.check_plan("# 迁移方案\n\n- 一步") == ("# 迁移方案\n\n- 一步", "迁移方案")
for badp in ("", None, "没有标题", "## 二级开头", "#没空格", "# " + "x" * P.PLAN_MAX):
    try:
        P.check_plan(badp); raise AssertionError(badp)
    except P.PlanTextError:
        pass
assert P.heading("前言\n### 小节 \n# 大") == "小节" and P.heading("无") is None
assert P.notice(None, "plan") is None and P.notice("plan", "plan") is None
assert "计划模式" in P.notice("default", "plan") and "普通模式" in P.notice("plan", "default")
msgs = [{"role": "system", "content": "A\n\n" + P.PROMPT + "\n\nB"}, {"role": "user", "content": "x"}]
orig = msgs[0]
assert P.lift_prompt(msgs) and P.PROMPT not in msgs[0]["content"] and "A" in msgs[0]["content"] and "B" in msgs[0]["content"]
assert P.PROMPT in orig["content"] and not P.lift_prompt(msgs) and not P.lift_prompt([])
h = P.history_text({"title": "T", "plan": "# T\n内容", "state": "approved"})
assert "用户已批准" in h and "内容" in h
assert "后面略" in P.history_text({"title": "T", "plan": "# T\n" + "y" * 5000, "state": "pending"})
assert P.normalize("x") == "default" and P.valid("plan") and not P.valid("")
print("ok: rules")

# —— 三、整轮 ——
script: list = []
requests: list = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    requests.append([dict(m) for m in messages])
    step = script.pop(0)
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"c{len(script)}-{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
ran: list = []
async def fake_run(project_id, command, timeout=60):
    ran.append(command)
    return {"exit_code": 0, "output": "a.txt\n", "timed_out": False}
sandbox_client.stream = streamed(fake_run)
load_builtin()
assert P.TOOL in REGISTRY and REGISTRY[P.TOOL].quiet

wr = project_dir(workspaces.PERSONAL)
(wr / "a.txt").write_text("原文\n")

async def seed(mode="plan", seen=None, text="帮我把 a.txt 改好"):
    async with SessionLocal() as db:
        conv = Conversation(title="计划", mode=mode, mode_seen=seen); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=[{"type": "text", "text": text}]))
        await db.commit()
        return conv.id
async def turn(cid, approve=True):
    events = []
    async def emit(ev):
        events.append(ev)
    async def appr(_id, _t, _d):
        return approve
    async with SessionLocal() as db:
        reply = await run_turn(db, await db.get(Conversation, cid), emit=emit, approve=appr)
    return reply, events
async def conv_of(cid):
    async with SessionLocal() as db:
        return await db.get(Conversation, cid)
def tool_results(req):
    return [m["content"] for m in req if m["role"] == "tool"]

PLAN = "# 改 a.txt\n\n## 概要\n把原文改成新文\n\n## 验证\ncat a.txt"
cid = asyncio.run(seed())
script.extend([
    [("write_file", {"path": "a.txt", "content": "偷改\n"}), ("run_command", {"command": "rm -rf a.txt"})],
    [("update_plan", {"todos": [{"content": "改", "status": "in_progress"}]}), ("run_command", {"command": "ls && cat a.txt | head -n 3"}),
     ("read_file", {"path": "a.txt"})],
    [(P.TOOL, {"plan": "没有标题的方案"})],
    [(P.TOOL, {"plan": PLAN})],
    [("write_file", {"path": "a.txt", "content": "新文\n"})],
    "改好了。"])
reply, events = asyncio.run(turn(cid))
first = requests[-6]
assert P.PROMPT in first[0]["content"] and "用户刚把" not in first[0]["content"]       # 第一次进来：不说“切换”
r1 = tool_results(requests[-5])
assert "write_file 会改东西" in r1[0] and "只读命令" in r1[1], r1
r2 = tool_results(requests[-4])[2:]
assert "update_plan" in r2[0] and "a.txt" in r2[1] and "原文" in r2[2], r2
assert ran == ["ls && cat a.txt | head -n 3"], ran                                       # 危险命令没跑，只读命令跑了
r3 = tool_results(requests[-3])[-1]
assert "# 标题" in r3, r3
r4 = tool_results(requests[-2])[-1]
assert r4 == P.LIFTED, r4
assert P.PROMPT not in requests[-2][0]["content"] and P.PROMPT in requests[-3][0]["content"]  # 批准后下一次请求就没有计划规则
assert "已写入" in tool_results(requests[-1])[-1] or "a.txt" in tool_results(requests[-1])[-1]
assert (wr / "a.txt").read_text() == "新文\n"
cards = [b for b in reply.blocks if b["type"] == "plan_review"]
assert len(cards) == 1 and cards[0]["state"] == "approved" and cards[0]["title"] == "改 a.txt" and cards[0]["plan"] == PLAN, cards
denied = [s for s in reply.steps if s.get("state") == "denied"]
assert len(denied) >= 3 and all("计划模式" in (s.get("note") or "") for s in denied), denied
types = [e["type"] for e in events]
assert "conversation.mode" in types and types.index("conversation.mode") < types.index("message.done"), types
assert next(e for e in events if e["type"] == "conversation.mode") == {"type": "conversation.mode", "conversation_id": cid, "mode": "default"}
cv = asyncio.run(conv_of(cid))
assert cv.mode == "default" and cv.mode_seen == "default"
assert "改 a.txt" in blocks_to_text(reply.blocks) and "把原文改成新文" in blocks_to_text(reply.blocks)
print("ok: approved turn")

# 没批准：留在计划模式
cid = asyncio.run(seed())
script.extend([[(P.TOOL, {"plan": PLAN})], "你想改哪里？"])
reply, events = asyncio.run(turn(cid, approve=False))
assert tool_results(requests[-1])[-1] == P.REJECTED
assert P.PROMPT in requests[-1][0]["content"]
card = next(b for b in reply.blocks if b["type"] == "plan_review")
assert card["state"] == "rejected" and "conversation.mode" not in [e["type"] for e in events]
assert asyncio.run(conv_of(cid)).mode == "plan"
assert "用户没批准" in blocks_to_text(reply.blocks)
print("ok: rejected")

# 切换提示：只说一次
cid = asyncio.run(seed(mode="plan", seen="default"))
script.append("好的，我先看看。")
asyncio.run(turn(cid))
assert "用户刚把这个对话切到了计划模式" in requests[-1][0]["content"]
assert asyncio.run(conv_of(cid)).mode_seen == "plan"
async def add_user(cid, text):
    async with SessionLocal() as db:
        db.add(Message(conversation_id=cid, role="user", blocks=[{"type": "text", "text": text}])); await db.commit()
asyncio.run(add_user(cid, "继续"))
script.append("嗯。")
asyncio.run(turn(cid))
assert "用户刚把" not in requests[-1][0]["content"] and P.PROMPT in requests[-1][0]["content"]
async def set_mode(cid, mode):
    async with SessionLocal() as db:
        c = await db.get(Conversation, cid); c.mode = mode; await db.commit()
asyncio.run(set_mode(cid, "default")); asyncio.run(add_user(cid, "动手吧"))
script.append("好。")
asyncio.run(turn(cid))
assert "切回了普通模式" in requests[-1][0]["content"] and P.PROMPT not in requests[-1][0]["content"]
print("ok: notice")

# 普通模式下 exit_plan_mode：拒，不弹卡
cid = asyncio.run(seed(mode="default"))
script.extend([[(P.TOOL, {"plan": PLAN})], "好。"])
reply, _ = asyncio.run(turn(cid))
assert tool_results(requests[-1])[-1] == P.NOT_ACTIVE and not any(b["type"] == "plan_review" for b in reply.blocks)
print("ok: not active")

# 子助手在计划模式下也只读
(wr / "b.txt").write_text("b\n")
cid = asyncio.run(seed())
script.extend([
    [("delegate", {"tasks": [{"title": "查 b", "prompt": "看看 b.txt，顺手改成 c"}]})],
    [("write_file", {"path": "b.txt", "content": "c\n"})],
    "查完了，没改。",
    "子助手查完了。"])
reply, _ = asyncio.run(turn(cid))
child_req = requests[-3]
assert P.CHILD_NOTE in child_req[0]["content"] and P.PROMPT not in child_req[0]["content"]
assert "计划模式" in tool_results(requests[-2])[-1]
assert (wr / "b.txt").read_text() == "b\n"
print("ok: subagent read-only")

# —— 四、REST / WebSocket ——
app = FastAPI()
for rt in (rws.router, rc.router):
    app.include_router(rt)
app.dependency_overrides[require_user] = lambda: "u"
c = TestClient(app)
assert c.patch(f"/api/conversations/{cid}", json={"mode": "x"}).status_code == 422
assert c.patch(f"/api/conversations/{cid}", json={"mode": "plan"}).status_code == 200
assert c.get(f"/api/conversations/{cid}").json()["mode"] == "plan"
assert next(x for x in c.get("/api/conversations").json() if x["id"] == cid)["mode"] == "plan"
assert c.patch(f"/api/conversations/{cid}", json={"mode": ""}).json()["mode"] == "default"
token = issue_token()
with c.websocket_connect(f"/ws?token={token}") as ws:
    script.append("先规划一下。")
    ws.send_json({"type": "user.message", "text": "规划一下", "mode": "plan"})
    got = []
    while True:
        e = ws.receive_json(); got.append(e)
        if e["type"] in ("message.done", "error"):
            break
    assert got[-1]["type"] == "message.done", got
    new = got[0]["conversation_id"]
    assert P.PROMPT in requests[-1][0]["content"]
assert asyncio.run(conv_of(new)).mode == "plan"
print("ok: rest + ws")

for step in ("downgrade", "upgrade"):
    rv = subprocess.run([sys.executable, "-m", "alembic", step, "-1" if step == "downgrade" else "head"], cwd=root,
                        capture_output=True, text=True)
    assert rv.returncode == 0, rv.stderr
print("ok: migration")
print("all ok")
