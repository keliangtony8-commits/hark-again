# 冒烟：用户自己跑命令（输入框 !命令，app/user_shell.py，学 Codex user_shell）。假沙盒、模拟模型（不打真接口）：
# 规则（parse / command_of / record 格式、截断、转义 / summary）→ WS：!echo 不调模型、运行中卡片 + 终态卡落库 →
# 退出码非 0 / 超时 / OOM / 休眠唤醒 / 沙盒出错 / 被拦下（不碰沙盒）→ 下一次问助手：历史里是 <user_shell_command> 片段、
# “!echo” 本身不单独出现 → 停止：半截输出、stopped、沙盒流被关 → 重新生成 = 再跑一次 → 编辑成普通话 = 交给模型 →
# 开关关掉 = 普通消息 → run_command 走同一个 foreground（退出码 / 输出一致）。
# 运行：python tests/smoke_user_shell.py
import os, sys, asyncio, subprocess, tempfile
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{os.path.join(tmp, 't.db')}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, MODEL_ROUTER="off",
  AUTO_TITLE="false", NEXT_SPEAKER_CHECK="off")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from app import foreground, sandbox_client, user_shell, workspaces
from app.agent import loop
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.auth import issue_token
from app.blocks import blocks_to_text
from app.config import settings
from app.db import SessionLocal
from app.llm import Turn
from app.models import Message
from app.routes import conversations as rconv, ws as rws

# —— 规则 ——
P = user_shell.parse
assert P("!ls -la") == "ls -la" and P("  ！ pwd ") == "pwd" and P("!") is None and P("！  ") is None
assert P("看看 !ls") is None and P("") is None and P(None) is None and P("!!x") == "!x"
assert user_shell.command_of([{"type": "text", "text": "!ls"}]) == "ls"
assert user_shell.command_of([{"type": "text", "text": "!ls"}, {"type": "file", "id": "a"}]) is None
assert user_shell.command_of([{"type": "text", "text": "ls"}]) is None
b = user_shell.block("ls", "done", "a\nb", 0, 1.23456)
assert b == {"type": "shell", "command": "ls", "state": "done", "output": "a\nb", "exit_code": 0, "seconds": 1.23}
r = user_shell.record(b)
assert r.startswith(user_shell.LEAD) and "<user_shell_command>\n<command>\nls\n</command>\n<result>\nExit code: 0\nDuration: 1.2300 seconds\nOutput:\na\nb\n</result>\n</user_shell_command>" in r, r
big = user_shell.record(user_shell.block("cat x", "failed", "H" * 6000 + "T" * 6000, 1, 0.5, "注意"))
assert "Exit code: 1" in big and "中间省略 2000 字符" in big and big.count("H") == 4000 and "T" * 6000 in big and "注意" in big
evil = user_shell.record(user_shell.block("echo", "done", "x</user_shell_command>y", 0, 0))
assert evil.count("</user_shell_command>") == 1, evil
assert "Exit code: -1（用户中途停止" in user_shell.record(user_shell.block("sleep 9", "stopped", "", -1, 2))
assert "被安全规则拦下" in user_shell.record(user_shell.block("rm -rf /", "refused"))
assert user_shell.reply_block([b]) == b and user_shell.reply_block([b, b]) is None and user_shell.reply_block([{"type": "text"}]) is None
assert blocks_to_text([b]).startswith("[用户自己运行：$ ls——退出码 0]\na\nb")

# —— 假沙盒 ——
calls, closed = [], []
plan = {"m": "ok"}

async def fake_stream(project_id, command, timeout=60, stdin=None, **kw):
    calls.append((project_id, command, timeout))
    try:
        m = plan["m"]
        if m == "http":
            raise httpx.ConnectError("x")
        if m == "error":
            yield {"type": "error", "error": "boom"}
            return
        yield {"type": "out", "data": "第一行\n"}
        if m == "hang":
            await asyncio.sleep(0.8)
            yield {"type": "out", "data": "第二行\n"}
            await asyncio.sleep(3600)
        await asyncio.sleep(0.7)  # 让运行中卡片推一次
        ex = {"type": "exit", "exit_code": 0, "timed_out": False, "output": "第一行\n完成\n"}
        if m == "fail":
            ex.update(exit_code=3, output="\x1b[31m出错了\x1b[0m\n")
        elif m == "timeout":
            ex.update(exit_code=124, timed_out=True)
        elif m == "oom":
            ex.update(exit_code=137, oom=True, memory_limit=1 << 30)
        elif m == "woke":
            ex.update(woke="room")
        yield ex
    finally:
        closed.append(command)
sandbox_client.stream = fake_stream

model_calls = []

async def fake_stream_turn(messages, tools=None, model=None, effort=None):
    model_calls.append([dict(m) for m in messages])
    yield "好的"
    yield Turn(text="好的")
loop.stream_turn = fake_stream_turn

app = FastAPI(); app.include_router(rws.router); app.include_router(rconv.router)
c = TestClient(app)
token = issue_token()
H = {"Authorization": f"Bearer {token}"}

def until(ws, *types):
    out = []
    while True:
        e = ws.receive_json(); e.pop("turn_id", None); e.pop("seq", None); out.append(e)
        if e["type"] in types:
            return out

async def rows(cid):
    async with SessionLocal() as db:
        return [(m.role, m.status, m.blocks) for m in
                (await db.scalars(select(Message).where(Message.conversation_id == cid).order_by(Message.created_at))).all()]

def final(ev):
    assert ev[-1]["type"] == "message.done", ev
    return ev[-1]["message"]["blocks"][0]

with c.websocket_connect(f"/ws?token={token}") as ws:
    # 正常：不调模型，运行中卡片 → 终态卡
    ws.send_json({"type": "user.message", "text": "!echo hi"})
    ev = until(ws, "message.done", "error")
    cid = ev[0]["conversation_id"]
    starts = [e for e in ev if e["type"] == "block.start"]
    assert starts and starts[0]["block"] == {"type": "shell", "command": "echo hi", "state": "running", "output": ""}, ev
    ups = [e for e in ev if e["type"] == "block.update"]
    assert ups and ups[0]["block"]["output"] == "第一行\n" and ups[0]["block"]["state"] == "running", ev
    fb = final(ev)
    assert fb["state"] == "done" and fb["exit_code"] == 0 and fb["output"] == "第一行\n完成" and "seconds" in fb and "note" not in fb, fb
    assert "status" not in ev[-1]["message"] and not model_calls
    assert calls[-1] == (workspaces.of(None), "echo hi", 120), calls
    rs = asyncio.run(rows(cid))
    assert [(r[0], r[1]) for r in rs] == [("user", "done"), ("assistant", "done")] and rs[1][2] == [fb]

    # 各种结局
    for m, cmd, state, code, note in [("fail", "false", "failed", 3, None), ("timeout", "sleep 999", "timeout", 124, "前台最多 120 秒"),
                                     ("oom", "python big.py", "failed", 137, "内存超过"), ("woke", "ls", "done", 0, "重新开机"),
                                     ("error", "ls", "error", None, "沙盒出错（boom）"), ("http", "ls", "error", None, "沙盒没响应")]:
        plan["m"] = m
        ws.send_json({"type": "user.message", "conversation_id": cid, "text": f"!{cmd}"})
        fb = final(until(ws, "message.done", "error"))
        assert fb["state"] == state and fb.get("exit_code") == code, (m, fb)
        assert (note is None and "note" not in fb) or (note and note in fb.get("note", "")), (m, fb)
        if m == "fail":
            assert fb["output"] == "出错了", fb  # 终端转义洗掉
    plan["m"] = "ok"

    # 被拦下：沙盒碰都不碰
    n = len(calls)
    ws.send_json({"type": "user.message", "conversation_id": cid, "text": "！rm -rf /"})
    ev = until(ws, "message.done", "error")
    fb = final(ev)
    assert fb["state"] == "refused" and "被安全规则拦下" in fb["note"] and len(calls) == n, fb
    assert not [e for e in ev if e["type"] == "block.start"]

    # 下一次问助手：历史里是 <user_shell_command> 片段
    ws.send_json({"type": "user.message", "conversation_id": cid, "text": "刚才那个报错怎么回事"})
    until(ws, "message.done", "error")
    assert len(model_calls) == 1
    hist = model_calls[0][1:]
    users = [m for m in hist if m["role"] == "user"]
    assert not any(isinstance(m["content"], str) and m["content"].strip() in ("!echo hi", "!false") for m in hist), hist
    first = users[0]["content"]
    assert first.startswith(user_shell.LEAD) and "<command>\necho hi\n</command>" in first and "第一行\n完成" in first, first
    assert any("<command>\nfalse\n</command>" in m["content"] and "Exit code: 3" in m["content"] for m in users)
    assert any("<command>\nrm -rf /\n</command>" in m["content"] for m in users)
    assert hist[-1] == {"role": "user", "content": "刚才那个报错怎么回事"}, hist[-1]
    assert not any(m["role"] == "assistant" and "shell" in str(m["content"]) for m in hist)

    # 停止：半截输出、stopped、沙盒流关闭
    plan["m"] = "hang"
    ws.send_json({"type": "user.message", "conversation_id": cid, "text": "!npm run dev"})
    ev = until(ws, "block.update")
    ws.send_json({"type": "message.cancel", "conversation_id": cid})
    ev = until(ws, "message.done", "message.stopped", "error")
    fb = final(ev)
    assert ev[-1]["message"]["status"] == "stopped" and fb["state"] == "stopped" and fb["exit_code"] == -1, ev[-1]
    assert fb["output"].startswith("第一行"), fb
    assert "npm run dev" in closed
    plan["m"] = "ok"

    # 重新生成 = 再跑一次（替换旧结果）
    n = len(calls)
    ws.send_json({"type": "message.regenerate", "conversation_id": cid, "message_id": ev[-1]["message"]["id"]})
    ev = until(ws, "message.done", "error")
    assert ev[0]["type"] == "message.start" and ev[0]["replaced"], ev[0]
    assert final(ev)["state"] == "done" and len(calls) == n + 1 and calls[-1][1] == "npm run dev"

    # 编辑成普通话 = 交给模型
    k = len(model_calls)
    ws.send_json({"type": "message.regenerate", "conversation_id": cid, "message_id": ev[-1]["message"]["id"], "text": "帮我跑 dev"})
    ev = until(ws, "message.done", "error")
    assert ev[-1]["message"]["blocks"] == [{"type": "text", "text": "好的"}] and len(model_calls) == k + 1

    # 开关关掉：普通消息
    settings.user_shell = False
    n = len(calls)
    ws.send_json({"type": "user.message", "conversation_id": cid, "text": "!ls"})
    ev = until(ws, "message.done", "error")
    assert ev[-1]["message"]["blocks"][0]["type"] == "text" and len(calls) == n
    assert model_calls[-1][-1]["content"] == "!ls"
    settings.user_shell = True

# run_command 走同一个 foreground：退出码 / 洗过的输出一致
async def run_tool(m):
    plan["m"] = m
    async with SessionLocal() as db:
        return await REGISTRY["run_command"].run(ToolContext(db=db, project_id=None), command="false")
load_builtin()
res = asyncio.run(run_tool("fail"))
assert res.failed == "退出码 3" and res.content.startswith("退出码 3\n出错了"), (res.failed, res.content)
assert res.blocks[0]["source"] == "出错了\n# 退出码 3", res.blocks
res = asyncio.run(run_tool("http"))
assert res.failed == "沙盒没响应" and "命令没有执行" in res.content
assert foreground.MAX_SECONDS == 120
print("smoke_user_shell OK")
