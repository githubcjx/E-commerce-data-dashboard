#!/usr/bin/env bash
#
# Daily PostgreSQL backup. Keeps the last $RETAIN_DAYS dumps.
#
# Run manually:
#   bash /opt/ec-dashboard/deploy/backup.sh
#
# Or via cron (sudo crontab -e):
#   0 3 * * * /opt/ec-dashboard/deploy/backup.sh >> /opt/ec-dashboard/backups/backup.log 2>&1
#
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/ec-dashboard}"
BACKUP_DIR="${BACKUP_DIR:-$INSTALL_DIR/backups}"
RETAIN_DAYS="${RETAIN_DAYS:-14}"

cd "$INSTALL_DIR"
mkdir -p "$BACKUP_DIR"

TS=$(date +%Y%m%d-%H%M%S)
FILE="$BACKUP_DIR/ec_dashboard_$TS.sql.gz"

docker compose exec -T db pg_dump -U postgres -d ec_dashboard --clean --if-exists \
    | gzip -9 > "$FILE"

SIZE=$(du -h "$FILE" | cut -f1)
echo "[$(date -u +%FT%TZ)] backup: $FILE ($SIZE)"

# Prune old dumps
DELETED=$(find "$BACKUP_DIR" -maxdepth 1 -name 'ec_dashboard_*.sql.gz' -mtime "+$RETAIN_DAYS" -print -delete | wc -l)
[ "$DELETED" -gt 0 ] && echo "[$(date -u +%FT%TZ)] pruned $DELETED dumps older than $RETAIN_DAYS days"
exit 0
