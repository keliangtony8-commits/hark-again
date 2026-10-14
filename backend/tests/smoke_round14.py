# 冒烟：v2.66 第十四轮真测修复 B35——工作区命令的时钟 = 用户时区（以前容器是 UTC，“写当前时间”晚 8 小时）。
# 规则在 sandbox/runner.py clock_zone/TZ（行为由 smoke_command_env 测）；这里查配置链和给模型的话是否一致：
# TIMEZONE（.env）→ compose SANDBOX_TZ → 容器 TZ；镜像装 tzdata；workspaces.ENVIRONMENT 告诉模型别再换算。无迁移。
# 运行：python tests/smoke_round14.py
import base64, os, sys, tempfile
tmp = tempfile.mkdtemp()
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/t.db", LLM_BASE_URL="http://x", LITELLM_MASTER_KEY="k",
  OWNER_USERNAME="u", OWNER_PASSWORD="p", JWT_SECRET="s"*32, VAULT_KEY=base64.urlsafe_b64encode(os.urandom(32)).decode(),
  DATA_DIR=tmp, PUBLIC_URL="https://me.example", TIMEZONE="Europe/Berlin")
root = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, root)
from app import workspaces
assert "Europe/Berlin" in workspaces.ENVIRONMENT and "TZ" in workspaces.ENVIRONMENT, workspaces.ENVIRONMENT
top = os.path.join(root, "..")
compose = open(os.path.join(top, "docker-compose.yml")).read()
assert "SANDBOX_TZ: ${TIMEZONE:-Asia/Shanghai}" in compose
assert "tzdata" in open(os.path.join(top, "sandbox/image/Dockerfile")).read()
assert "\nTIMEZONE=Asia/Shanghai\n" in open(os.path.join(top, ".env.example")).read()
src = open(os.path.join(top, "sandbox/runner.py")).read()
assert 'environment={"TZ": TZ}' in src and 'os.environ.get("SANDBOX_TZ") or os.environ.get("TIMEZONE")' in src
print("smoke_round14 OK")
