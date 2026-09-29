#!/bin/sh
# 备份 SQLite 数据库到带时间戳的文件
set -e

DATA_DIR="${HARNESS_DATA_DIR:-/app/data}"
DB_FILE="${DATABASE_PATH:-${DATA_DIR}/harness.db}"
BACKUP_DIR="${BACKUP_DIR:-${DATA_DIR}/backups}"
STAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"
if [ ! -f "$DB_FILE" ]; then
  echo "数据库文件不存在: $DB_FILE"
  exit 1
fi

DEST="${BACKUP_DIR}/harness_${STAMP}.db"
cp "$DB_FILE" "$DEST"
chmod 600 "$DEST"
echo "已备份至 $DEST"
