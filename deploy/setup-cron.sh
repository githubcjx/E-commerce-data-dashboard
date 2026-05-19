#!/usr/bin/env bash
#
# Register a daily Postgres backup cron job. Idempotent — re-running is safe.
#
# Usage:
#   sudo bash /opt/ec-dashboard/deploy/setup-cron.sh
#
# What it does:
#   - Drops a file at /etc/cron.d/ec-dashboard-backup that runs
#     deploy/backup.sh every day at 03:00 server-local time.
#   - Ensures /opt/ec-dashboard/backups exists with sane permissions.
#   - Verifies the cron service is running.
#
# Removal:
#   sudo rm /etc/cron.d/ec-dashboard-backup
#
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/ec-dashboard}"
CRON_FILE=/etc/cron.d/ec-dashboard-backup

[ "$EUID" -eq 0 ] || { echo "请用 sudo 运行：sudo bash $0" >&2; exit 1; }
[ -d "$INSTALL_DIR" ] || { echo "未找到 $INSTALL_DIR" >&2; exit 1; }
[ -x "$INSTALL_DIR/deploy/backup.sh" ] || chmod +x "$INSTALL_DIR/deploy/backup.sh"

mkdir -p "$INSTALL_DIR/backups"
chmod 750 "$INSTALL_DIR/backups"

# Install/replace the cron snippet. /etc/cron.d files need a username column
# and a trailing newline; both included.
cat > "$CRON_FILE" <<EOF
# Daily Postgres backup for ec-dashboard. Managed by deploy/setup-cron.sh.
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# m  h  dom mon dow user  command
  0  3  *   *   *   root  $INSTALL_DIR/deploy/backup.sh >> $INSTALL_DIR/backups/backup.log 2>&1
EOF
chmod 644 "$CRON_FILE"
echo "✓ 写入 $CRON_FILE"

# Make sure cron is actually running.
CRON_SVC=""
for svc in crond cron; do
    if systemctl list-unit-files 2>/dev/null | grep -q "^${svc}\\.service"; then
        CRON_SVC="$svc"
        break
    fi
done
if [ -n "$CRON_SVC" ]; then
    systemctl enable --now "$CRON_SVC" >/dev/null 2>&1 || true
    if systemctl is-active --quiet "$CRON_SVC"; then
        echo "✓ $CRON_SVC 服务运行中"
    else
        echo "! $CRON_SVC 不是 active 状态，请手动检查"
    fi
else
    echo "! 没找到 cron / crond 服务，可能需要先安装：dnf install -y cronie 或 apt install -y cron"
fi

echo
echo "下一次备份：今天/明天 03:00（服务器本地时间 $(date +%Z)）"
echo "立即测试一次："
echo "  sudo bash $INSTALL_DIR/deploy/backup.sh"
echo "查看历史日志："
echo "  tail -f $INSTALL_DIR/backups/backup.log"
