# 冒烟：消息带 created_at（客户端画日期分隔用）。模拟模型（不打真接口）：
# message.done 的回复带有时区的 created_at → GET 对话每条都带、且按时间不减 →
# SQLite 读回来无时区的老数据也补成 UTC（不会被客户端当成本地时间差 8 小时）。
# 运行：python tests/smoke_message_time.py
import os, sys, asyncio, subprocess, tempfile
from datetime import datetime, timezone
db_path = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{db_path}", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, check=True, capture_output=True)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.agent import loop
from app.auth import issue_token
from app.llm import Turn
from app.models import Message
from app.routes import conversations as rconv, ws as rws

async def fake_stream_turn(messages, tools=None, model=None, effort=None):
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
        e = ws.receive_json(); out.append(e)
        if e["type"] in types:
            return out

def parse(s):
    t = datetime.fromisoformat(s)
    assert t.tzinfo is not None, s
    return t

with c.websocket_connect(f"/ws?token={token}") as ws:
    ws.send_json({"type": "user.message", "text": "你好"})
    ev = until(ws, "message.done", "error")
    assert ev[-1]["type"] == "message.done", ev
    cid = ev[0]["conversation_id"]
    done_at = parse(ev[-1]["message"]["created_at"])
    assert abs((datetime.now(timezone.utc) - done_at).total_seconds()) < 60, done_at

msgs = c.get(f"/api/conversations/{cid}", headers=H).json()["messages"]
assert [m["role"] for m in msgs] == ["user", "assistant"], msgs
times = [parse(m["created_at"]) for m in msgs]
assert times[0] <= times[1], times

# 无时区（SQLite 读回来的样子）→ 当 UTC
naive = Message(id="m1", role="user", blocks=[], created_at=datetime(2026, 10, 10, 16, 30))
assert naive.to_wire()["created_at"] == "2026-10-10T16:30:00+00:00", naive.to_wire()
# 还没落库（created_at 为空）→ 不带这个字段，老客户端照常
assert "created_at" not in Message(id="m2", role="user", blocks=[]).to_wire()
print("ok: message created_at")
