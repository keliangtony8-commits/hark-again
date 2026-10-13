# 冒烟：v2.02 CORE 24 云浏览器出网关卡（browser/egress.py）——模拟模型，无迁移。
# 1) 一致性：浏览器的 is_private_address 与后端 app/web_guard.is_private_address 对一张大表逐条同结论
#    （两个容器各一份，改一边必须改另一边）；
# 2) blocked_note：没被拦 → 空；被拦 → 说清是内网被拦、别绕、OUTBOUND_ALLOW_HOSTS；超过 3 个只列 3 个 + “等 N 个”；坏数据忽略；
# 3) 一轮对话：模型 browser_open 公网页面，服务回的快照带 blocked → 工具结果最前面是 ⚠ 提示，交回模型；
#    打开的地址本身 302 进内网（服务回 403 “被拦下”）→ 时间线 error 带原因。
# 运行：python tests/smoke_browser_egress.py
import os, sys, asyncio, subprocess, tempfile, json, ipaddress, random
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
sys.path.insert(0, os.path.join(root, "..", "browser"))
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

import egress
from app import llm, web_guard
from app.agent import runner
from app.agent.builtin import browser as browser_tool
from app.agent.tools import load_builtin
from app.blocks import text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Message

# ---- 1. 一致性 ----
table = ["127.0.0.1", "10.1.2.3", "172.16.0.1", "172.32.0.1", "192.168.0.1", "169.254.169.254", "100.64.0.1",
         "100.128.0.1", "198.18.0.1", "198.20.0.1", "0.0.0.0", "224.0.0.1", "240.0.0.1", "255.255.255.255",
         "::1", "::", "fe80::1", "fe80::1%eth0", "fc00::1", "ff02::1", "2001:db8::1", "::ffff:127.0.0.1",
         "::ffff:10.0.0.1", "::ffff:8.8.8.8", "[::1]", "8.8.8.8", "93.184.216.34", "2606:4700::1111", "1.1.1.1",
         "localhost", "LOCALHOST.", "db.internal", "printer.local", "x.localhost", "example.com", "", "not an ip",
         "192.0.2.1", "203.0.113.5", "64:ff9b::808:808"]
rng = random.Random(7)
table += [str(ipaddress.IPv4Address(rng.getrandbits(32))) for _ in range(3000)]
table += [str(ipaddress.IPv6Address(rng.getrandbits(128))) for _ in range(500)]
diff = [a for a in table if web_guard.is_private_address(a) != egress.is_private_address(a)]
assert not diff, diff[:10]
assert egress.INTERNAL_SUFFIXES == web_guard.INTERNAL_SUFFIXES
assert egress.sanitize_host("[::1]") == web_guard.sanitize_host("[::1]") == "::1"
print("ok: parity", len(table))

# ---- 2. blocked_note ----
N = browser_tool.blocked_note
assert N({}) == "" and N({"blocked": []}) == "" and N({"blocked": ["x", {"reason": "无主机"}]}) == ""
one = N({"blocked": [{"host": "10.0.0.5", "reason": "evil.example 指向内网地址 10.0.0.5"}]})
assert one.startswith("⚠") and "evil.example 指向内网地址 10.0.0.5" in one and "别换地址" in one and "OUTBOUND_ALLOW_HOSTS" in one
many = N({"blocked": [{"host": f"10.0.0.{i}", "reason": f"10.0.0.{i} 是内网 / 本机地址"} for i in range(5)]})
assert "10.0.0.2" in many and "10.0.0.3" not in many and "等 5 个地址" in many, many
assert N({"blocked": [{"host": "h"}]}).count("h") >= 1
print("ok: note")

# ---- 3. 一轮对话 ----
load_builtin()
calls = []
async def fake_snapshot(session, method, path, body=None):
    calls.append((session, path, body))
    if body and "/go" in body.get("url", ""):
        raise RuntimeError("被拦下：127.0.0.1 是内网 / 本机地址。助手的浏览器不能访问内网 / 本机地址。")
    return {"url": "https://news.example/", "title": "新闻", "text": "正文", "elements": [{"ref": "1", "tag": "a", "type": "", "name": "更多"}],
            "restored": False, "login": {"signed_in": None, "expired": None},
            "blocked": [{"host": "169.254.169.254", "reason": "169.254.169.254 是内网 / 本机地址"}]}
browser_tool.browser_client.snapshot_call = fake_snapshot
async def no_files(ws, session):
    return NS(note="", files=[])
browser_tool.browser_files.collect = no_files
async def public(host):
    return ["93.184.216.34"]
web_guard.resolve = public

script: list = []
tool_msgs: list[dict] = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    messages = [dict(m) for m in messages]
    tool_msgs.extend(m for m in messages if m["role"] == "tool" and m not in tool_msgs)
    step = script.pop(0)
    async def gen():
        if isinstance(step, list):
            yield chunk(tool=[NS(index=i, id=f"c{i}", function=NS(name=n, arguments=json.dumps(a, ensure_ascii=False)))
                              for i, (n, a) in enumerate(step)])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create

async def turn(cid, steps):
    script.extend(steps)
    async with SessionLocal() as db:
        conv = Conversation(id=cid, title="t"); db.add(conv); await db.commit()
        db.add(Message(conversation_id=cid, role="user", blocks=text_to_blocks("看看")))
        await db.commit()
        return await runner.run_turn(db, conv)

reply = asyncio.run(turn("c1", [[("browser_open", {"url": "https://news.example/"})], "好。"]))
step = next(s for s in reply.steps if s["tool"] == "browser_open")
assert step["state"] == "done", step
content = tool_msgs[-1]["content"]
assert content.startswith("会话：news-example") and "⚠ 页面里有请求被拦下（169.254.169.254 是内网 / 本机地址）" in content, content
assert content.index("⚠") < content.index("页面：新闻")
reply = asyncio.run(turn("c2", [[("browser_open", {"url": "https://news.example/go"})], "那个链接进了内网，打不开。"]))
step = next(s for s in reply.steps if s["tool"] == "browser_open")
assert step["state"] == "error" and "被拦下" in (step.get("note") or ""), step
assert "被拦下" in tool_msgs[-1]["content"]
print("smoke_browser_egress OK")
