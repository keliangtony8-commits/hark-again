#!/usr/bin/env bash
# 更新到最新代码并重启：sudo bash deploy/update.sh
# 数据库迁移由后端启动时自动执行（alembic upgrade head）；.env 和数据目录不动。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
[[ -f .env ]] || { echo "没有 .env，先运行 deploy/install.sh" >&2; exit 1; }
if [[ -d .git ]]; then git pull --ff-only; else echo "› 不是 git 仓库：请先把新版本解压覆盖到这里（保留 .env）"; fi
export COMPOSE_PARALLEL_LIMIT=1
docker compose --profile build-only build sandbox-image
docker compose up -d --build --remove-orphans
docker image prune -f >/dev/null
echo "› 已更新 ✓  看日志：docker compose logs -f backend"
