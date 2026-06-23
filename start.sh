#!/usr/bin/env bash
# HostFlow — Start Script
# Usage: ./start.sh [dev|prod]

set -e

MODE="${1:-dev}"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

# Load .env if present
if [ -f .env ]; then
  set -o allexport
  # shellcheck disable=SC1091
  source .env
  set +o allexport
  echo "[hostflow] Loaded .env"
fi

# Create required directories
mkdir -p instance/sessions uploads user_sites backups logs nginx

echo "[hostflow] Mode: $MODE"

if [ "$MODE" = "prod" ]; then
  export FLASK_ENV=production
  exec gunicorn \
    --worker-class eventlet \
    --workers 1 \
    --bind 0.0.0.0:5000 \
    --timeout 180 \
    --keepalive 5 \
    --access-logfile logs/access.log \
    --error-logfile logs/error.log \
    --log-level info \
    "wsgi:application"
else
  export FLASK_ENV=development
  export FLASK_DEBUG=1
  python3 run_dev.py
fi
