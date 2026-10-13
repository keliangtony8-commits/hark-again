# 冒烟：v2.57 E2E 第十一轮三处修复（无迁移）。
# B28 jobs.FIX_SCOPE：接着说（notice）与压下的结论（held_notice）都限定“自己修”只限环境问题、不删改用户代码 / 报错；
# B29 api_request 非 https → failed，并指向 run_command curl；常驻任务启动结果提示 curl 自检；
# B27 panel_log 说明：一样的内容也照记，不自判“已经记过了”。
# 运行：python tests/smoke_round11.py
import os, sys, asyncio, tempfile, json
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, TIMEZONE="Asia/Shanghai",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone
from app import jobs
from app.models import Job
from app.agent.tools import load_builtin, REGISTRY

now = datetime.now(timezone.utc)
j = Job(id="j1", project_id="me", conversation_id="c", title="运行 crunch.py", command="python3 crunch.py", timeout=3600,
        state="failed", exit_code=1, tail="MemoryError: Unable to allocate 6.40 GiB\n", created_at=now, finished_at=now,
        followup="pending", read_offset=0)
n = jobs.notice(j)
assert jobs.FIX_SCOPE in n and "引用关键报错原话" in n and "能自己修好就直接修了再跑" not in n, n
assert "删改用户代码" in jobs.FIX_SCOPE and "环境问题" in jobs.FIX_SCOPE
assert jobs.FIX_SCOPE in jobs.held_notice([j])

load_builtin()
api = REGISTRY["api_request"]
r = asyncio.run(api.run(NS(db=None), url="http://127.0.0.1:8091/time"))
assert r.failed and "curl -s http://127.0.0.1" in r.content, r
src = open(os.path.join(os.path.dirname(__file__), "..", "app", "agent", "builtin", "workspace.py"), encoding="utf-8").read()
assert "自己验证就用 run_command 跑 curl" in src
desc = REGISTRY["panel_log"].description
assert "一模一样也照记" in desc and "已经记过了" in desc
print("smoke_round11 ok")
