#!/usr/bin/env bash
# 备份数据库 + .env 到 $HOST_DATA_DIR/backups（保留最近 7 份）：sudo bash deploy/backup.sh
# 可加进 crontab：0 4 * * * bash /opt/assistant/deploy/backup.sh >/dev/null
# 恢复：gunzip -c db-*.sql.gz | docker compose exec -T postgres psql -U assistant assistant
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
data="$(awk -F= '$1=="HOST_DATA_DIR"{v=substr($0,index($0,"=")+1)} END{print v}' .env)"
out="${data:-/opt/assistant/data}/backups"; mkdir -p "$out"; chmod 700 "$out"
stamp="$(date +%Y%m%d-%H%M)"
docker compose exec -T postgres pg_dump -U assistant assistant | gzip > "$out/db-$stamp.sql.gz"
install -m 600 .env "$out/env-$stamp"
ls -1t "$out"/db-*.sql.gz | tail -n +8 | xargs -r rm -f
ls -1t "$out"/env-* | tail -n +8 | xargs -r rm -f
echo "› 已备份到 $out/db-$stamp.sql.gz（项目文件在 $data/projects，按需另行同步）"
