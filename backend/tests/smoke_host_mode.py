# 冒烟：服务器主机模式（app/host_policy.py 移植自 Codex execpolicy/exec_policy；app/host_mode.py；agent/builtin/host.py；
# deploy/host-agent/host_agent.py）。
# 一、策略：Codex 三档 + 按段取最严 + 前缀规则 + 禁用前缀 + 会话批准键 + 无人值守 → 禁止；command_guard block 一律禁止；
# 二、真主机代理（unix socket，本机 bash 代替 VPS）：health、实时输出、超时杀整组、输出首尾截断、断开即杀、令牌；
# 三、模拟模型整轮：关着不给工具；审批卡带选项；“以后都允许” → 存规则、下一轮不弹卡（定时任务也认）；“这段对话里都允许”只在本对话；
#     拒绝不执行；block 不弹卡；会停掉 Docker 的只给“仅这一次”；子助手拿不到；
# 四、API：状态 / 开关（没装 409）/ 删规则；五、迁移 0030 可降可升。
import os, sys, asyncio, subprocess, tempfile, json, threading, time
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
sock = os.path.join(tmp, "run", "agent.sock")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", HOST_AGENT_SOCKET=sock, HOST_AGENT_TOKEN="t" * 32)
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
sys.path.insert(0, os.path.join(root, "..", "deploy", "host-agent"))
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

import httpx
import host_agent
from app import host_client, host_mode, host_policy, llm
from app.agent import approvals, loop, subagent
from app.agent.tools import ToolContext, deny_all, load_builtin, REGISTRY
from app.blocks import ApprovalBlock
from app.config import settings
from app.db import SessionLocal
from app.models import Conversation, HostRule

ev = host_policy.evaluate

# —— 一、策略 ——
r = ev("rm -rf /", [])
assert r.kind == "forbid" and "安全规则" in r.reason
r = ev("systemctl status nginx", [])
assert r.kind == "ask" and r.rule == ("systemctl", "status", "nginx") and r.session and r.key == ("systemctl", "status", "nginx")
assert ev("systemctl status nginx", [["systemctl", "status"]]).kind == "skip"
assert ev("sudo systemctl status nginx", [["systemctl", "status"]]).kind == "skip"     # sudo 去掉再匹配
assert ev("sudo -u www systemctl status nginx", [["systemctl", "status"]]).kind == "ask"  # 换用户 ≠ 同一条
# 按段取最严（Codex check_multiple）：一段没覆盖就要问
r = ev("systemctl status nginx && journalctl -u nginx -n 50", [["systemctl", "status"]])
assert r.kind == "ask" and r.rule is None and r.key[0] == "__script__"
assert ev("systemctl status nginx && journalctl -u nginx", [["systemctl", "status"], ["journalctl"]]).kind == "skip"
# 模型建议的前缀（Codex prefix_rule）：能覆盖每一段才用；禁用表里的不用 → 退回整条命令
assert ev("apt-get install -y htop", [], proposed=["apt-get", "install"]).rule == ("apt-get", "install")
assert ev("apt-get install -y htop", [], proposed=["apt-get"]).rule == ("apt-get", "install", "-y", "htop")
assert ev("python3 -c 'print(1)'", [], proposed=["python3", "-c"]).rule == ("python3", "-c", "print(1)")
assert ev("bash -lc 'ls'", [], proposed=["bash", "-lc"]).rule == ("bash", "-lc", "ls")
assert ev("ls /etc && df -h", [], proposed=["ls"]).rule is None                         # 盖不住第二段
assert ev("echo $HOME", []).rule is None and ev("echo $HOME", []).key[0] == "__script__"  # 非字面量
assert host_policy.usable_rule(["rm"], [["rm", "x"]]) is None and host_policy.usable_rule(["sudo"], [["sudo"]]) is None
assert host_policy.usable_rule(["a"] * 9, [["a"] * 9]) is None
# 危险（command_guard ask）：能批，不给前缀规则
r = ev("git push --force origin main", [])
assert r.kind == "ask" and r.rule is None and r.session and "强制" in r.reason
# 会停掉助手自己：只给“仅这一次”
r = ev("docker stop assistant-backend-1", [])
assert r.kind == "ask" and not r.session and r.rule is None and "停掉容器" in r.reason
r = ev("systemctl restart docker", [["systemctl"]])  # 规则不该放行（禁用表本来也不会让 systemctl 单词规则存进来）
assert r.kind == "skip"  # 规则就是规则：用户亲手存的照办（禁用表只挡“建议”）
# 会话批准键
k = ev("df -h", []).key
assert ev("df -h", [], {k}).kind == "skip" and ev("df -h /", [], {k}).kind == "ask"
# 无人值守：要问的 → 禁止；规则覆盖的照跑；block 照样禁止
assert ev("df -h", [], unattended=True).kind == "forbid" and "定时任务" in ev("df -h", [], unattended=True).reason
assert ev("df -h", [["df"]], unattended=True).kind == "skip"
assert ev("", []).kind == "forbid"
assert host_mode.options(ev("df -h", [])) == [{"id": "once", "label": "仅这一次"}, {"id": "session", "label": "这段对话里都允许"},
                                              {"id": "rule", "label": "以后都允许 df -h 开头的命令"}]
assert [o["id"] for o in host_mode.options(ev("docker stop x", []))] == ["once"]
print("ok: policy")

# —— 二、真主机代理 ——
host_agent.CWD = tmp
host_agent.ENV["HOME"] = tmp  # 测试机不是 root
srv = host_agent.serve(sock, "t" * 32, gid=None)
threading.Thread(target=srv.serve_forever, daemon=True).start()
assert oct(os.stat(sock).st_mode & 0o777) == "0o660"
ht = host_agent.HeadTail(10)
ht.push("abcdefghij"); ht.push("KLMNOP")
out, omitted = ht.result()
assert out.startswith("abcde") and out.endswith("LMNOP") and omitted == 6 and "省略 6" in out
ht = host_agent.HeadTail(100); ht.push("short")
assert ht.result() == ("short", 0)


async def collect(cmd, timeout=10, stop_after=None):
    evs = []
    async for e in host_client.stream(cmd, timeout):
        evs.append(e)
        if stop_after and len(evs) >= stop_after:
            break
    return evs


async def agent_tests():
    h = await host_client.health()
    assert h["hostname"] and h["timeout_max"] == host_agent.TIMEOUT_MAX and "os" in h
    evs = await collect("echo 你好; sleep 0.7; echo 世界; exit 3")
    outs = [e for e in evs if e["type"] == "out"]
    assert len(outs) >= 2 and "你好" in outs[0]["data"]  # 分批推送
    end = evs[-1]
    assert end["type"] == "exit" and end["exit_code"] == 3 and "你好\n世界" in end["output"] and not end["timed_out"]
    assert (await collect("cat; echo eof"))[-1]["output"].strip() == "eof"  # stdin 是空的，不卡
    assert (await collect("pwd"))[-1]["output"].strip() == tmp
    t0 = time.monotonic()
    end = (await collect(f"echo $$ > {tmp}/pg; sleep 30", timeout=1))[-1]
    assert end["timed_out"] and time.monotonic() - t0 < 6
    end = (await collect("python3 -c \"print('x'*50000)\""))[-1]
    assert end["omitted"] > 0 and end["total"] == 50001 and len(end["output"]) < host_agent.HEAD_TAIL + 100
    # 断开即杀：读到第一段输出就不读了
    pidf = f"{tmp}/pid2"
    await collect(f"echo $$ > {pidf}; echo go; sleep 30", stop_after=1)
    for _ in range(40):
        await asyncio.sleep(0.1)
        pid = int(open(pidf).read())
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
    else:
        raise AssertionError("断开后命令还在跑")
    # 令牌不对 → 401
    settings.host_agent_token = "wrong" * 8
    try:
        await host_client.health()
        raise AssertionError("错令牌应当 401")
    except httpx.HTTPStatusError as e:
        assert e.response.status_code == 401
    finally:
        settings.host_agent_token = "t" * 32
    print("ok: host agent")


# —— 三、整轮 ——
script, saw = [], []


def chunk(text=None, tools=None, u=None):
    if text is None and tools is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tools))], usage=u)


async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    saw.append({"messages": json.loads(json.dumps(messages, ensure_ascii=False)), "tools": [t["function"]["name"] for t in tools or []]})
    step = script.pop(0) if script else "好了"

    async def gen():
        if isinstance(step, list):
            yield chunk(tools=[NS(index=i, id=f"c{len(saw)}_{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                               for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=100, completion_tokens=0))
    return gen()

llm.client.chat.completions.create = fake_create
load_builtin()
cards = []


def approver(option: str | None):
    async def approve(aid, reason, detail):
        cards.append((aid, reason, detail))
        if option is None:
            return False
        approvals._options[aid] = option  # 等同 WS approval.reply {id, approved: true, option}
        return True
    return approve


def host_cmd(cmd, **kw):
    return ("host_command", {"command": cmd, "reason": "看看服务", **kw})


async def turn(cid, *steps, approve=None, host=True):
    script[:] = list(steps); saw.clear(); cards.clear()
    async with SessionLocal() as db:
        if await db.get(Conversation, cid) is None:
            db.add(Conversation(id=cid, title="t")); await db.commit()
        ctx = ToolContext(db=db, conversation_id=cid, approve=approve or deny_all, host=host)
        return [e async for e in loop.run("sys", [{"role": "user", "content": "看下服务器"}], ctx, loop.MessageBuilder())]


def tool_text(i=-1):
    return [m for m in saw[i]["messages"] if m["role"] == "tool"][-1]["content"]


async def turns():
    assert "host_command" not in subagent.CHILD_TOOLS
    await turn("c0", "嗯", host=False)
    assert "host_command" not in saw[0]["tools"]
    async with SessionLocal() as db:
        await host_mode.set_enabled(db, True)
        assert await host_mode.enabled(db)
    # 1) 以后都允许：卡带三个选项 → 选 rule → 存规则 → 执行
    evs = await turn("c1", [host_cmd("echo hi-from-host")], "完事", approve=approver("rule"))
    done = evs[-1]
    card = next(b for b in done.blocks if b["type"] == "approval")
    ApprovalBlock(**card)
    assert card["target"] == "host" and card["host"] and card["state"] == "approved" and card["granted"] == "rule"
    assert [o["id"] for o in card["options"]] == ["once", "session", "rule"] and card["note"] == "看看服务" and not card["warn"]
    code = next(b for b in done.blocks if b["type"] == "code")
    assert "hi-from-host" in code["source"] and "退出码 0" in code["source"] and not code.get("live")
    assert "以后 echo hi-from-host 开头的命令都允许了" in tool_text()
    async with SessionLocal() as db:
        rules = await host_mode.rules(db)
        assert [r.prefix for r in rules] == [["echo", "hi-from-host"]]
    # 2) 规则覆盖 → 不弹卡；uses 记一次
    evs = await turn("c2", [host_cmd("echo hi-from-host again")], "完事", approve=approver("once"))
    assert not cards and not any(b["type"] == "approval" for b in evs[-1].blocks) and "again" in tool_text()
    async with SessionLocal() as db:
        assert (await host_mode.rules(db))[0].uses == 1
    # 3) 定时任务（deny_all）：规则覆盖的照跑，没覆盖的不执行也不弹卡
    await turn("c3", [host_cmd("echo hi-from-host task")], "完事")
    assert "task" in tool_text()
    await turn("c3", [host_cmd("uname -a")], "完事")
    assert not cards and "定时任务" in tool_text()
    # 4) 这段对话里都允许：同对话第二次不弹，别的对话照弹
    await turn("c4", [host_cmd("uname -s")], [host_cmd("uname -s")], "完事", approve=approver("session"))
    assert len(cards) == 1 and "这段对话里这条命令都允许了" in tool_text(1)
    await turn("c5", [host_cmd("uname -s")], "完事", approve=approver("once"))
    assert len(cards) == 1
    # 5) 拒绝：不执行，时间线 denied
    evs = await turn("c6", [host_cmd(f"touch {tmp}/should-not")], "好", approve=approver(None))
    assert not os.path.exists(f"{tmp}/should-not") and "没有批准" in tool_text()
    assert next(b for b in evs[-1].blocks if b["type"] == "approval")["state"] == "rejected"
    # 6) block：不弹卡、不执行
    await turn("c7", [host_cmd("rm -rf /")], "好", approve=approver("once"))
    assert not cards and "安全规则" in tool_text()
    # 7) 停 Docker：卡只给“仅这一次”，warn；即使客户端回 rule 也只当 once（不存规则）
    evs = await turn("c8", [host_cmd("docker stop nothing-here 2>/dev/null; echo tried")], "好", approve=approver("rule"))
    card = next(b for b in evs[-1].blocks if b["type"] == "approval")
    assert [o["id"] for o in card["options"]] == ["once"] and card["warn"] and card["granted"] == "once" and "停掉容器" in card["note"]
    async with SessionLocal() as db:
        assert len(await host_mode.rules(db)) == 1
    # 8) 模型伪造 grant 参数：丢掉，照样弹卡
    await turn("c9", [host_cmd("hostname", grant="rule")], "好", approve=approver(None))
    assert len(cards) == 1 and "没有批准" in tool_text()
    # 9) 退出码非 0 → 时间线 error
    evs = await turn("c10", [host_cmd("exit 4")], "好", approve=approver("once"))
    st = [e for e in evs if isinstance(e, loop.ToolStatus) and e.state != "running"][-1]
    assert st.state == "error" and "退出码 4" in tool_text()
    # 10) 关掉：工具不再出现，会话批准清空
    async with SessionLocal() as db:
        await host_mode.set_enabled(db, False)
    assert host_mode.granted(host_mode.owner_of("c4")) == set()
    print("ok: turns")


async def api():
    from fastapi import FastAPI
    from app.auth import require_user
    from app.routes import host as rh
    app = FastAPI(); app.include_router(rh.router)
    app.dependency_overrides[require_user] = lambda: "u"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        s = (await c.get("/api/host")).json()
        assert s["installed"] and not s["enabled"] and s["reachable"] and s["host"]["hostname"]
        assert s["rules"][0]["text"] == "echo hi-from-host" and s["rules"][0]["uses"] == 2 and s["rules"][0]["last_used_at"]
        s = (await c.put("/api/host", json={"enabled": True})).json()
        assert s["enabled"]
        rid = s["rules"][0]["id"]
        assert (await c.delete(f"/api/host/rules/{rid}")).json()["rules"] == []
        assert (await c.delete(f"/api/host/rules/{rid}")).status_code == 404
        settings.host_agent_socket = ""
        assert (await c.put("/api/host", json={"enabled": True})).status_code == 409
        s = (await c.get("/api/host")).json()
        assert not s["installed"] and not s["enabled"] and not s["reachable"]
        settings.host_agent_socket = sock
        srv.shutdown(); srv.server_close()  # 代理停了：装了但连不上
        s = (await c.get("/api/host")).json()
        assert s["installed"] and not s["reachable"]
    print("ok: api")


async def main():
    await agent_tests()
    await turns()
    await api()

asyncio.run(main())

for args in (["downgrade", "0029"], ["upgrade", "head"]):
    r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
print("smoke_host_mode OK")
