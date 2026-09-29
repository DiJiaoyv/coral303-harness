#!/bin/sh
set -e

DATA_DIR="${HARNESS_DATA_DIR:-/app/data}"
export HARNESS_DATA_DIR="$DATA_DIR"
export DATABASE_URL="${DATABASE_URL:-sqlite:///${DATA_DIR}/harness.db}"

mkdir -p "$DATA_DIR/users" "$DATA_DIR/logs" "$DATA_DIR/characters"
chmod 700 "$DATA_DIR" 2>/dev/null || true

if [ ! -e /app/harness.db ] && [ -f "$DATA_DIR/harness.db" ]; then
  ln -sf "$DATA_DIR/harness.db" /app/harness.db
fi
if [ ! -e /app/users ] && [ -d "$DATA_DIR/users" ]; then
  ln -sf "$DATA_DIR/users" /app/users
fi

_run_as_harness() {
  if [ "$(id -u)" = "0" ] && command -v gosu >/dev/null 2>&1; then
    gosu harness "$@"
  else
    "$@"
  fi
}

if [ "$(id -u)" = "0" ]; then
  chown -R harness:harness /app "$DATA_DIR"
fi

echo "[entrypoint] 初始化数据库..."
_run_as_harness python /app/deploy/scripts/init_db.py

if [ -n "$ADMIN_USERNAME" ] && [ -n "$ADMIN_PASSWORD" ]; then
  echo "[entrypoint] 初始化管理员..."
  _run_as_harness python /app/deploy/scripts/init_admin.py || true
fi

SERVICE="${1:-web}"
shift || true

case "$SERVICE" in
  web)
    echo "[entrypoint] 启动 Flask Web (gunicorn)..."
    if [ "$(id -u)" = "0" ] && command -v gosu >/dev/null 2>&1; then
      exec gosu harness gunicorn \
        --bind "0.0.0.0:${WEB_PORT:-7860}" \
        --workers "${GUNICORN_WORKERS:-2}" \
        --timeout 120 \
        --access-logfile - \
        --error-logfile - \
        "web_ui:create_flask_app()"
    else
      exec gunicorn \
        --bind "0.0.0.0:${WEB_PORT:-7860}" \
        --workers "${GUNICORN_WORKERS:-2}" \
        --timeout 120 \
        --access-logfile - \
        --error-logfile - \
        "web_ui:create_flask_app()"
    fi
    ;;
  api)
    echo "[entrypoint] 启动 FastAPI (uvicorn)..."
    if [ "$(id -u)" = "0" ] && command -v gosu >/dev/null 2>&1; then
      exec gosu harness uvicorn api.main:app \
        --host "0.0.0.0" \
        --port "${API_PORT:-8000}" \
        --workers "${UVICORN_WORKERS:-1}"
    else
      exec uvicorn api.main:app \
        --host "0.0.0.0" \
        --port "${API_PORT:-8000}" \
        --workers "${UVICORN_WORKERS:-1}"
    fi
    ;;
  *)
    echo "未知服务: $SERVICE (可用: web, api)"
    exit 1
    ;;
esac
