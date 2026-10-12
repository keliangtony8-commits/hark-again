#!/usr/bin/env bash
# 一键部署（Debian 12 / Ubuntu 22.04+，x86_64 或 arm64，建议 ≥2 核 4GB）
#
#   sudo bash deploy/install.sh
#
# 做的事（可重复运行，已有的 .env 值和数据都保留）：
#   1. 小内存机器（<6GB）建 2GB swap、vm.swappiness=10
#   2. 装 Docker + compose 插件（已装跳过）
#   3. 生成 .env：随机密码/密钥；问你域名、阶跃 key、登录账号（直接回车 = 用默认）
#      小内存 = 直连模式（不跑 LiteLLM 网关，省约 500MB）、浏览器同时 1 个会话、沙盒 512MB
#   4. 构建沙盒镜像，启动全部服务，等后端健康后打印访问地址
#
# 无人值守：ASSUME_YES=1 DOMAIN=a.com STEP_API_KEY=... OWNER_PASSWORD=... sudo -E bash deploy/install.sh
# 强制大/小内存档：SMALL=1 或 SMALL=0
# 服务器主机模式（可选，默认不装）：sudo bash deploy/install.sh --host-agent  或  HOST_AGENT=1
#   装一个只听 unix socket 的 root 主机代理（deploy/host-agent），App“我的电脑”里打开后，助手才能在本机跑命令，且每条都要你批准
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
SWAP_FILE="${SWAP_FILE:-/swapfile}"
SWAP_SIZE_MB="${SWAP_SIZE_MB:-2048}"
STEP_DEFAULT_BASE="https://api.stepfun.ai/step_plan/v1"
MODEL_MAP_DEFAULT='{"fast": "step-3.7-flash", "smart": "step-5-preview", "lite": "step-3.5-flash"}'

say()  { printf '\033[1m›\033[0m %s\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

interactive() { [[ "${ASSUME_YES:-0}" != 1 && -t 0 ]]; }

# ---------- .env 读写（只用 awk，值里有 / { " 都安全） ----------
env_get() {  # env_get KEY → 当前生效的值（忽略注释行）
  [[ -f "$ENV_FILE" ]] || return 0
  awk -v k="$1" 'index($0, k "=") == 1 { v = substr($0, length(k) + 2) } END { if (v != "") print v }' "$ENV_FILE"
}

env_set() {  # env_set KEY VALUE → 改已有的 KEY= 行，没有就追加
  local tmp; tmp="$(mktemp)"
  K="$1" V="$2" awk '
    BEGIN { k = ENVIRON["K"]; v = ENVIRON["V"]; done = 0 }
    index($0, k "=") == 1 { if (!done) print k "=" v; done = 1; next }
    { print }
    END { if (!done) print k "=" v }' "$ENV_FILE" > "$tmp"
  cat "$tmp" > "$ENV_FILE"; rm -f "$tmp"
}

placeholder() {  # 空值或示例里的占位符 → 需要生成
  [[ -z "$1" || "$1" == change-me* || "$1" == sk-litellm-change-me || "$1" == "https://your.domain" ]]
}

env_default() {  # env_default KEY VALUE → 只在没填/占位时写入
  placeholder "$(env_get "$1")" && env_set "$1" "$2"
  return 0
}

rand_hex()   { head -c "${1:-24}" /dev/urandom | od -An -tx1 | tr -d ' \n'; }
fernet_key() { head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '\n'; }  # = Fernet.generate_key()

ask() {  # ask 提示 默认值 [secret] → 交互时读一行，回车用默认
  local prompt="$1" def="$2" secret="${3:-}" ans=""
  if interactive; then
    if [[ -n "$secret" ]]; then read -rsp "$prompt: " ans; echo >&2; else read -rp "$prompt [$def]: " ans; fi
  fi
  printf '%s' "${ans:-$def}"
}

mem_mb() { awk '/^MemTotal:/ { print int($2 / 1024) }' /proc/meminfo; }
swap_mb() { awk '/^SwapTotal:/ { print int($2 / 1024) }' /proc/meminfo; }

is_small() {
  [[ -n "${SMALL:-}" ]] && { [[ "$SMALL" == 1 ]]; return; }
  (( $(mem_mb) < 6000 ))
}

public_ip() {
  curl -fsS4 --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I 2>/dev/null | awk '{ print $1 }'
}

# ---------- 1. 系统 ----------
check_system() {
  [[ $EUID -eq 0 ]] || die "请用 root 运行：sudo bash deploy/install.sh"
  if [[ -r /etc/os-release ]]; then
    . /etc/os-release
    case "${ID:-}" in debian|ubuntu) ;; *) warn "没在 ${PRETTY_NAME:-这个系统} 上测过，按 Debian 方式继续" ;; esac
  fi
  local m; m="$(mem_mb)"
  (( m >= 1800 )) || die "内存只有 ${m}MB，至少需要 2GB"
  say "内存 ${m}MB，$(is_small && echo '小内存档（直连模式）' || echo '标准档（含模型网关）')"
}

setup_swap() {
  is_small || return 0
  if (( $(swap_mb) >= 1024 )); then say "已有 $(swap_mb)MB swap，跳过"; else
    say "创建 ${SWAP_SIZE_MB}MB swap：$SWAP_FILE"
    if [[ ! -f "$SWAP_FILE" ]]; then
      fallocate -l "${SWAP_SIZE_MB}M" "$SWAP_FILE" 2>/dev/null || dd if=/dev/zero of="$SWAP_FILE" bs=1M count="$SWAP_SIZE_MB" status=none
      chmod 600 "$SWAP_FILE"; mkswap "$SWAP_FILE" >/dev/null
    fi
    swapon "$SWAP_FILE" 2>/dev/null || true
    grep -q "^$SWAP_FILE " /etc/fstab || echo "$SWAP_FILE none swap sw 0 0" >> /etc/fstab
  fi
  echo "vm.swappiness=10" > /etc/sysctl.d/99-assistant.conf
  sysctl -q -p /etc/sysctl.d/99-assistant.conf || true
}

install_docker() {
  if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
    say "Docker 已安装：$(docker --version)"; return
  fi
  say "安装 Docker…"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq && apt-get install -y -qq ca-certificates curl >/dev/null
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
  docker compose version >/dev/null || die "docker compose 插件没装上"
}

open_firewall() {
  if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
    say "防火墙放行 80/443"; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
  fi
}

# ---------- 2. .env ----------
GENERATED_PASSWORD=""

write_env() {
  if [[ ! -f "$ENV_FILE" ]]; then cp "$ROOT/.env.example" "$ENV_FILE"; say "已从 .env.example 生成 .env"; fi
  chmod 600 "$ENV_FILE"

  # 随机密钥：只补空的/占位的，已有的绝不覆盖（VAULT_KEY 换了就解不开保险箱）
  env_default JWT_SECRET "$(rand_hex 32)"
  env_default POSTGRES_PASSWORD "$(rand_hex 16)"
  env_default LITELLM_MASTER_KEY "sk-$(rand_hex 16)"
  env_default SANDBOX_TOKEN "$(rand_hex 24)"
  env_default BROWSER_TOKEN "$(rand_hex 24)"
  env_default VAULT_KEY "$(fernet_key)"
  env_default HOST_DATA_DIR "/opt/assistant/data"

  # 登录账号
  local user; user="$(env_get OWNER_USERNAME)"
  env_set OWNER_USERNAME "$(ask '登录用户名' "${OWNER_USERNAME:-${user:-me}}")"
  if placeholder "$(env_get OWNER_PASSWORD)"; then
    local pw="${OWNER_PASSWORD:-}"
    [[ -n "$pw" ]] || pw="$(ask '登录密码（回车自动生成）' '' secret)"
    [[ -n "$pw" ]] || { pw="$(rand_hex 8)"; GENERATED_PASSWORD="$pw"; }
    env_set OWNER_PASSWORD "$pw"
  fi

  # 域名：有域名 = 自动 HTTPS；没有 = http://IP
  local cur_domain; cur_domain="$(env_get DOMAIN)"
  [[ "$cur_domain" == ":80" ]] && cur_domain=""
  local domain; domain="$(ask '域名（已解析到本机；没有直接回车）' "${DOMAIN:-$cur_domain}")"
  domain="${domain#http://}"; domain="${domain#https://}"; domain="${domain%%/*}"
  if [[ -n "$domain" && "$domain" != ":80" ]]; then
    env_set DOMAIN "$domain"; env_set PUBLIC_URL "https://$domain"
  else
    env_set DOMAIN ":80"; env_set PUBLIC_URL "http://${PUBLIC_IP:-$(public_ip)}"
  fi

  # 模型 key
  local key; key="$(env_get STEP_API_KEY)"
  if [[ -n "${STEP_API_KEY:-}" ]]; then key="$STEP_API_KEY"
  elif [[ -z "$key" ]]; then key="$(ask '阶跃 Step Plan 的 API key（回车跳过，之后再填 .env）' '' secret)"; fi
  [[ -n "$key" ]] && env_set STEP_API_KEY "$key"
  [[ -n "$key" ]] || warn "还没填模型 key：之后编辑 .env 的 STEP_API_KEY / LLM_API_KEY，再 docker compose up -d"

  # 内存档位：所有开关都是 .env 变量，docker-compose.yml 读它们
  if is_small; then
    env_set COMPOSE_PROFILES ""
    env_set LLM_BASE_URL "$(env_get STEP_BASE_URL | grep . || echo "$STEP_DEFAULT_BASE")"
    [[ -n "$key" ]] && env_set LLM_API_KEY "$key"
    [[ -n "$(env_get MODEL_MAP)" ]] || env_set MODEL_MAP "$MODEL_MAP_DEFAULT"
    env_set BROWSER_MAX_SESSIONS 1
    env_set BROWSER_MEM 1g
    env_set BROWSER_SHM 512mb
    env_set SANDBOX_MEM 512m
    env_set SANDBOX_IDLE_MINUTES 10
    env_set SANDBOX_MAX_RUNNING 2
  else
    env_set COMPOSE_PROFILES gateway
    # 标准档走网关：清空直连变量（key 回落到 LITELLM_MASTER_KEY）
    env_set LLM_BASE_URL "http://litellm:4000"
    env_set LLM_API_KEY ""
    env_set MODEL_MAP "{}"
  fi
}

prepare_data() {
  local dir; dir="$(env_get HOST_DATA_DIR)"
  mkdir -p "$dir/projects" "$dir/browser"
  chown -R 1000:1000 "$dir"   # 后端/沙盒容器里都是 uid 1000
}

# ---------- 3. 启动 ----------
start_stack() {
  cd "$ROOT"
  export COMPOSE_PARALLEL_LIMIT=1   # 小内存逐个构建，避免同时 npm install + pip install 把内存吃满
  say "构建沙盒镜像（第一次要几分钟）…"
  docker compose --profile build-only build sandbox-image
  say "构建并启动服务…"
  docker compose up -d --build
}

wait_healthy() {
  say "等后端就绪…"
  local i
  for i in $(seq 1 60); do
    if docker compose exec -T backend python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3)" >/dev/null 2>&1; then
      return 0
    fi
    sleep 5
  done
  docker compose logs --tail 40 backend >&2 || true
  die "后端 5 分钟内没起来，看上面的日志（docker compose logs backend）"
}

# ---------- 可选：主机代理 ----------
wants_host_agent() {
  [[ "${HOST_AGENT:-0}" == 1 ]] && return 0
  local a; for a in "$@"; do [[ "$a" == --host-agent ]] && return 0; done
  return 1
}

install_host_agent() {
  command -v python3 >/dev/null || apt-get install -y python3 >/dev/null
  install -d -m 0755 /opt/assistant-host
  install -m 0755 "$ROOT/deploy/host-agent/host_agent.py" /opt/assistant-host/host_agent.py
  install -d -m 0700 /etc/assistant-host
  local token; token="$(env_get HOST_AGENT_TOKEN)"
  placeholder "$token" && token="$(rand_hex 32)"
  ( umask 077; printf '%s\n' "$token" > /etc/assistant-host/token )
  env_set HOST_AGENT_TOKEN "$token"
  env_set HOST_AGENT_SOCKET /run/assistant-host/agent.sock
  install -m 0644 "$ROOT/deploy/host-agent/assistant-host.service" /etc/systemd/system/assistant-host.service
  systemctl daemon-reload
  systemctl enable --now assistant-host.service >/dev/null
  systemctl restart assistant-host.service
  say "主机代理已装（默认关）：App → 我的 → 我的电脑 → 服务器主机 里打开"
}

summary() {
  local url; url="$(env_get PUBLIC_URL)"
  echo
  say "部署完成 ✓"
  echo "  打开：$url   （App 里的服务器地址也填它）"
  echo "  用户名：$(env_get OWNER_USERNAME)"
  [[ -n "$GENERATED_PASSWORD" ]] && echo "  密码：$GENERATED_PASSWORD   （只显示这一次，存在 .env 的 OWNER_PASSWORD）"
  echo "  务必备份 .env（尤其 VAULT_KEY，丢了保险箱里的密钥就解不开）"
  echo "  以后更新：sudo bash deploy/update.sh    备份数据：sudo bash deploy/backup.sh"
}

main() {
  check_system
  setup_swap
  install_docker
  open_firewall
  write_env
  prepare_data
  if wants_host_agent "$@"; then install_host_agent; fi
  start_stack
  wait_healthy
  summary
}

# 测试只加载函数：INSTALL_LIB_ONLY=1 source deploy/install.sh
[[ "${INSTALL_LIB_ONLY:-0}" == 1 ]] || main "$@"
