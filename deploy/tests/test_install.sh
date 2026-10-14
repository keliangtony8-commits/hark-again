#!/usr/bin/env bash
# install.sh 的离线测试：只测 .env 生成（不碰 swap/Docker）。bash deploy/tests/test_install.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
fail() { echo "✗ $*" >&2; exit 1; }
eq() { [[ "$1" == "$2" ]] || fail "$3：期望 [$2] 实际 [$1]"; }

unset STEP_API_KEY DOMAIN OWNER_USERNAME OWNER_PASSWORD SMALL ENV_FILE  # 宿主环境变量会被当成输入
export INSTALL_LIB_ONLY=1 ASSUME_YES=1 PUBLIC_IP=203.0.113.7
# shellcheck source=../install.sh
source "$HERE/../install.sh"

# 1. 小内存 + 无域名 + 有 key
ENV_FILE="$TMP/a.env" SMALL=1 STEP_API_KEY=sk-test write_env
ENV_FILE="$TMP/a.env"
eq "$(env_get DOMAIN)" ":80" "无域名"
eq "$(env_get PUBLIC_URL)" "http://203.0.113.7" "无域名用 IP"
eq "$(env_get COMPOSE_PROFILES)" "" "小内存不跑网关"
eq "$(env_get LLM_BASE_URL)" "https://api.stepfun.ai/step_plan/v1" "直连地址"
eq "$(env_get LLM_API_KEY)" "sk-test" "直连 key"
eq "$(env_get MODEL_MAP)" "$MODEL_MAP_DEFAULT" "别名映射（JSON 原样）"
eq "$(env_get BROWSER_MAX_SESSIONS)" "1" "浏览器 1 个会话"
eq "$(env_get SANDBOX_MEM)" "512m" "沙盒内存"
eq "$(env_get OWNER_USERNAME)" "me" "默认用户名"
[[ -n "$GENERATED_PASSWORD" ]] || fail "没给密码时应自动生成"
eq "$(env_get OWNER_PASSWORD)" "$GENERATED_PASSWORD" "密码写入"
vk="$(env_get VAULT_KEY)"; [[ ${#vk} -eq 44 && "$vk" =~ ^[A-Za-z0-9_-]{43}=$ ]] || fail "VAULT_KEY 不是 Fernet 格式：$vk"
[[ "$(env_get JWT_SECRET)" =~ ^[0-9a-f]{64}$ ]] || fail "JWT_SECRET"
[[ "$(env_get SANDBOX_TOKEN)" != "$(env_get BROWSER_TOKEN)" ]] || fail "两个 token 不应相同"
[[ "$(stat -c %a "$ENV_FILE")" == 600 ]] || fail ".env 权限应为 600"
for k in DOMAIN LLM_BASE_URL VAULT_KEY COMPOSE_PROFILES; do
  eq "$(grep -c "^$k=" "$ENV_FILE")" "1" "$k 只出现一次"
done

# 2. 重跑：已有密钥/密码不变，换成有域名
before_vault="$(env_get VAULT_KEY)"; before_pw="$(env_get OWNER_PASSWORD)"
SMALL=1 DOMAIN="https://chat.example.com/" write_env
eq "$(env_get VAULT_KEY)" "$before_vault" "VAULT_KEY 绝不覆盖"
eq "$(env_get OWNER_PASSWORD)" "$before_pw" "密码不覆盖"
eq "$(env_get DOMAIN)" "chat.example.com" "域名去掉协议和斜杠"
eq "$(env_get PUBLIC_URL)" "https://chat.example.com" "有域名走 https"
eq "$(env_get LLM_API_KEY)" "sk-test" "重跑保留 key"

# 3. 切到标准档：开网关、清直连
SMALL=0 write_env
eq "$(env_get COMPOSE_PROFILES)" "gateway" "标准档开网关"
eq "$(env_get LLM_BASE_URL)" "http://litellm:4000" "标准档走网关"
eq "$(env_get LLM_API_KEY)" "" "标准档清直连 key"

# 4. 指定密码 + 用户名
ENV_FILE="$TMP/b.env" SMALL=1 OWNER_USERNAME=keliang OWNER_PASSWORD='p@ss w/"x' write_env
ENV_FILE="$TMP/b.env"
eq "$(env_get OWNER_USERNAME)" "keliang" "用户名"
eq "$(env_get OWNER_PASSWORD)" 'p@ss w/"x' "特殊字符密码原样"
eq "$(env_get STEP_API_KEY)" "" "没 key 不写"

# 5. compose 文件：小内存档插值后合法、litellm 只在 gateway profile、后端不依赖它
python3 - "$HERE/../../docker-compose.yml" <<'PY'
import sys, yaml
c = yaml.safe_load(open(sys.argv[1]))["services"]
assert c["litellm"].get("profiles") == ["gateway"], "litellm 应只在 gateway profile"
for s in ("backend", "worker"):
    dep = c[s]["depends_on"]
    assert "litellm" not in dep, f"{s} 不能依赖 litellm（小内存档不启动它）"
assert "${BROWSER_MAX_SESSIONS:-2}" in str(c["browser"]["environment"])
assert "SANDBOX_MEM" in c["sandbox"]["environment"]
assert "redis" not in c, "不引入 Redis"
PY
echo "✓ install.sh 测试通过"
