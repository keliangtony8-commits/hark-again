#!/usr/bin/env bash
# 更新到最新代码并重启：sudo bash deploy/update.sh
# 数据库迁移由后端启动时自动执行（alembic upgrade head）；.env 和数据目录不动。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
[[ -f .env ]] || { echo "没有 .env，先运行 deploy/install.sh" >&2; exit 1; }
if [[ -d .git ]]; then git pull --ff-only; else echo "› 不是 git 仓库：请先把新版本解压覆盖到这里（保留 .env）"; fi
# 装过主机代理（install.sh --host-agent）就顺手更新它
if [[ -f /etc/systemd/system/assistant-host.service ]]; then
  install -m 0755 deploy/host-agent/host_agent.py /opt/assistant-host/host_agent.py
  install -m 0644 deploy/host-agent/assistant-host.service /etc/systemd/system/assistant-host.service
  systemctl daemon-reload && systemctl restart assistant-host.service
fi
export COMPOSE_PARALLEL_LIMIT=1
# v2.37 沙盒网络改成 internal（只能经出网代理上网）：旧网络不是就删掉重建。先删沙盒容器（装的东西都在工作区，
# 下次用到自动重建）、停 sandbox 服务，网络上没人了才删得掉
if [[ "$(docker network inspect -f '{{.Internal}}' assistant-sandboxes 2>/dev/null || echo none)" == "false" ]]; then
  echo "› 沙盒网络改为只经出网代理上网：重建 assistant-sandboxes"
  ids=$(docker ps -aq --filter label=assistant.sandbox=1); [[ -n "$ids" ]] && docker rm -f $ids >/dev/null
  docker compose stop sandbox >/dev/null 2>&1 || true
  docker compose rm -f sandbox >/dev/null 2>&1 || true
  docker network rm assistant-sandboxes >/dev/null
fi
docker compose --profile build-only build sandbox-image
docker compose up -d --build --remove-orphans
docker image prune -f >/dev/null   # 只删悬空镜像（不带 -a：沙盒镜像没容器在跑时也要留着）
docker builder prune -f >/dev/null
echo "› 已更新 ✓  看日志：docker compose logs -f backend"
