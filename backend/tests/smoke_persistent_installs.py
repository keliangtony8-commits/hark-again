# 冒烟：v1.23 装的软件留得住——沙盒家目录在工作区 .home（镜像 workspace-env.sh），pip/npm 用户级安装跨容器保留；
# sudo/apt 这类沙盒里做不到的命令不执行、直接告诉模型怎么装（command_guard unsupported）；系统提示带环境说明。
# 运行：python tests/smoke_persistent_installs.py
import os, sys, asyncio, subprocess, tempfile, json, signal, time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY="", DATA_DIR=tmp, JOB_MAX_RUNNING="4",
  CHAT_MODELS=json.dumps({"fast": "快速"}), DEFAULT_MODEL="fast", VISION_MODELS='[]')
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from sqlalchemy import select
from app import jobs, llm, sandbox_client, storage
from app.agent.runner import run_turn
from app.agent.tools import REGISTRY, ToolContext, load_builtin
from app.auth import require_user, require_query_token
from app.blocks import Block, blocks_to_text, text_to_blocks
from app.db import SessionLocal
from app.models import Conversation, Job, Message, Project
from app.routes import files as rf, jobs as rj

# ---- 本机顶替沙盒服务 ----
procs: dict[str, subprocess.Popen] = {}
async def start_job(pid, jid):
    procs[jid] = subprocess.Popen(["bash", f".jobs/{jid}/run.sh"], cwd=storage.project_dir(pid), start_new_session=True)
def _pid(pid, jid):
    try:
        return int((storage.project_dir(pid) / ".jobs" / jid / "pid").read_text())
    except (FileNotFoundError, ValueError):
        return None
async def cancel_job(pid, jid):
    if (p := _pid(pid, jid)) is not None:
        try:
            os.killpg(p, signal.SIGTERM)
        except ProcessLookupError:
            pass
    procs[jid].wait(10)  # run.sh 写完 exit 才算
async def job_alive(pid, jid):
    p = _pid(pid, jid)
    if p is None:
        return False
    try:
        os.kill(p, 0)
        return True
    except ProcessLookupError:
        return False
sandbox_client.start_job, sandbox_client.cancel_job, sandbox_client.job_alive = start_job, cancel_job, job_alive
jobs.LOST_GRACE = 0

# ---- 模拟模型 ----
script: list = []
seen: list[list] = []
def chunk(text=None, tool=None, u=None):
    if text is None and tool is None:
        return NS(choices=[], usage=u)
    return NS(choices=[NS(delta=NS(content=text, tool_calls=tool))], usage=u)
async def fake_create(model, messages, stream=False, stream_options=None, tools=None, **kw):
    seen.append(messages)
    step = script.pop(0)
    async def gen():
        if isinstance(step, tuple):
            yield chunk(tool=[NS(index=0, id=f"c{len(script)}", function=NS(name=step[0], arguments=json.dumps(step[1], ensure_ascii=False)))])
        else:
            yield chunk(step)
        yield chunk(u=NS(prompt_tokens=10, completion_tokens=5))
    return gen()
llm.client.chat.completions.create = fake_create
load_builtin()

app = FastAPI()
app.include_router(rj.router); app.include_router(rf.router)
app.dependency_overrides[require_user] = lambda: "u"
app.dependency_overrides[require_query_token] = lambda: "u"
c = TestClient(app)
import httpx
from app import command_guard, spill
from app.config import settings
from app.agent.builtin import workspace

def run(coro):
    return asyncio.run(coro)


from app import workspaces
from app.agent.context import build_system_prompt

async def seed():
    async with SessionLocal() as db:
        p = Project(name="数据分析", emoji="📊"); db.add(p); await db.flush()
        conv = Conversation(title="装包", project_id=p.id); db.add(conv); await db.flush()
        db.add(Message(conversation_id=conv.id, role="user", blocks=text_to_blocks("帮我把 ffmpeg 装上")))
        await db.commit()
        return p.id, conv.id
pid, cid = run(seed())
root_dir = storage.project_dir(pid)

async def turn():
    async with SessionLocal() as db:
        return await run_turn(db, await db.get(Conversation, cid))

async def tool(name, **args):
    async with SessionLocal() as db:
        return await REGISTRY[name].run(ToolContext(db=db, project_id=pid, conversation_id=cid), **args)

# ---- 1. 规则：沙盒做不到的（sudo / apt）→ unsupported；毁系统的照样 block；查询放行 ----
V = command_guard.verdict
for cmd in ["sudo apt-get install -y ffmpeg", "apt install ffmpeg", "apt-get update && apt-get install -y jq",
            "cd x && sudo make install", "FOO=1 sudo ls", "su -c whoami", "/usr/bin/sudo pip install x",
            "git push && sudo reboot-later", "yum install gcc", "apk add curl", "dpkg -i x.deb", "env apt remove vim"]:
    assert V(cmd) and V(cmd).level == "unsupported", (cmd, V(cmd))
assert "root" in V("sudo ls").why and "系统软件包" in V("apt install x").why
for cmd in ["sudo rm -rf /", "sudo shutdown now", "sudo mkfs.ext4 /dev/sdb"]:
    assert V(cmd).level == "block", (cmd, V(cmd))
for cmd in ["apt list --installed", "dpkg -l", "apt show ffmpeg", "pip install pandas", "npm i -g pnpm",
            "echo sudo apt install", "pip install --user requests", "python -m venv .venv && . .venv/bin/activate && pip install x"]:
    assert V(cmd) is None, (cmd, V(cmd))
assert V("git push && sudo x").level == "unsupported"  # 做不到 > 要审批：别让用户批一条跑不了的命令
assert workspace._command_risk({"command": "sudo git push"}) is None

# ---- 2. 模型发 sudo apt：不执行、不弹卡，告诉它怎么装 ----
ran = []
async def fake_run(p, command, timeout=60):
    ran.append((p, command))
    return {"exit_code": 0, "timed_out": False, "output": "ok\n"}
sandbox_client.run = fake_run
script.extend([("run_command", {"command": "sudo apt-get install -y ffmpeg"}), ("run_command", {"command": "pip install imageio-ffmpeg"}), "装好了。"])
reply = run(turn())
assert ran == [(pid, "pip install imageio-ffmpeg")], ran
assert not any(b["type"] == "approval" for b in reply.blocks), reply.blocks
tool_msgs = [m["content"] for m in seen[-1] if m["role"] == "tool"]
assert "没有执行" in tool_msgs[0] and "pip install" in tool_msgs[0] and "~/.local" in tool_msgs[0], tool_msgs[0]
out = run(tool("run_command", command="sudo apt install htop", background=True)).content
assert "没有执行" in out and not (root_dir / ".jobs").exists(), out
desc = REGISTRY["run_command"].description
assert "非 root" in desc and "留在工作区" in desc, desc

# ---- 3. 系统提示：项目和个人工作区都告诉模型环境 ----
async def prompts():
    async with SessionLocal() as db:
        return await build_system_prompt(db, pid), await build_system_prompt(db, None)
proj, me = run(prompts())
for ptxt in (proj, me):
    assert workspaces.ENVIRONMENT in ptxt and "没有 sudo/apt" in ptxt, ptxt[-500:]

# ---- 4. 镜像环境脚本：家在工作区，pip/npm 用户级安装落到 .home，“新容器”里接着能用 ----
here = os.path.dirname(os.path.abspath(__file__))
env_sh = os.path.join(here, "..", "..", "sandbox", "image", "workspace-env.sh")
dockerfile = open(os.path.join(here, "..", "..", "sandbox", "image", "Dockerfile")).read()
assert "COPY workspace-env.sh /etc/profile.d/workspace.sh" in dockerfile
for pkg, word in [("jq", "jq"), ("ripgrep", "ripgrep"), ("poppler-utils", "poppler"), ("imagemagick", "ImageMagick"),
                  ("sqlite3", "sqlite3"), ("fonts-noto-cjk", "中文字体")]:
    assert pkg in dockerfile and word in workspaces.PREINSTALLED, pkg  # 预装清单两边同步
ws = storage.project_dir(workspaces.PERSONAL)
ws.mkdir(parents=True, exist_ok=True)
def sh(cmd):
    """模拟沙盒里的一条命令：bash -l 读 profile.d → 这里直接 source 同一个脚本（PATH 先被重置成 Debian 默认）。"""
    full = f'export PATH=/usr/local/bin:/usr/bin:/bin; export HOME=/home/dev; . "{env_sh}"; {cmd}'
    r = subprocess.run(["bash", "-c", full], capture_output=True, text=True, env={"WORKSPACE": str(ws), "PATH": "/usr/bin:/bin"})
    assert r.returncode == 0, (cmd, r.stderr)
    return r.stdout.strip()
home = ws / workspaces.HOME_DIR
assert sh('echo "$HOME"') == str(home)
assert sh('echo "$PYTHONUSERBASE|$NPM_CONFIG_PREFIX"') == f"{home}/.local|{home}/.local"
assert sh('echo "$PATH"').startswith(f"{home}/.local/bin:")
assert sh('echo "$XDG_CACHE_HOME"').startswith("/tmp/")  # 缓存不吃工作区磁盘
assert (home / ".local" / "bin").is_dir()
assert sh('echo "$PATH"').count(".home/.local/bin") == 1 and sh('. "%s"; echo "$PATH"' % env_sh).count(".home/.local/bin") == 1
site = sh('python3 -c "import site; print(site.getusersitepackages())"')
assert site.startswith(f"{home}/.local/lib/python"), site
os.makedirs(site, exist_ok=True)
open(os.path.join(site, "persisted_pkg.py"), "w").write("VALUE = 42\n")  # 等于 pip 装进了用户目录
assert sh('python3 -c "import persisted_pkg; print(persisted_pkg.VALUE)"') == "42"  # 另一条命令（新容器）照样能 import
tool_bin = home / ".local" / "bin" / "mytool"
tool_bin.write_text("#!/bin/sh\necho from-npm-global\n"); tool_bin.chmod(0o755)
assert sh("mytool") == "from-npm-global"  # npm i -g 装的命令在 PATH 里
(home / ".profile").write_text("export MY_SETTING=kept\n")
assert sh('. "$HOME/.profile"; echo $MY_SETTING') == "kept"
assert sh('cd /tmp && echo "$HOME"') == str(home)
r = subprocess.run(["bash", "-c", f'. "{env_sh}"; echo "$HOME"'], capture_output=True, text=True,
                   env={"WORKSPACE": "/nonexistent-ws", "HOME": "/home/dev", "PATH": "/usr/bin:/bin"})
assert r.stdout.strip() == "/home/dev"  # 没挂工作区（镜像单独起）时不乱改

# ---- 5. .home 是隐藏目录：文件列表、文件接口、打包都不显示，但完整日志一样的隐藏文件仍可读 ----
(root_dir / ".home" / ".local" / "lib").mkdir(parents=True)
(root_dir / ".home" / ".local" / "lib" / "big.py").write_text("x = 1\n")
(root_dir / "main.py").write_text("print(1)\n")
listed = run(tool("list_files")).content
assert "main.py" in listed and ".home" not in listed, listed
names = [f["path"] for f in c.get(f"/api/projects/{pid}/files").json()]
assert "main.py" in names and not any(".home" in n for n in names), names
assert c.get(f"/api/projects/{pid}/files/main.py").status_code == 200
assert c.get(f"/api/projects/{pid}/files/.home/.local/lib/big.py").status_code == 404
assert storage.hidden((".home", "x")) and not storage.hidden(("home", "x"))
print("persistent installs smoke ok")
