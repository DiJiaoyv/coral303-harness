#!/bin/sh
# 从备份文件恢复 SQLite 数据库
set -e

if [ -z "$1" ]; then
  echo "用法: restore_db.sh <备份文件路径>"
  exit 1
fi

DATA_DIR="${HARNESS_DATA_DIR:-/app/data}"
DB_FILE="${DATABASE_PATH:-${DATA_DIR}/harness.db}"
BACKUP="$1"

if [ ! -f "$BACKUP" ]; then
  echo "备份文件不存在: $BACKUP"
  exit 1
fi

cp "$BACKUP" "$DB_FILE"
chmod 600 "$DB_FILE"
echo "已从 $BACKUP 恢复到 $DB_FILE"
