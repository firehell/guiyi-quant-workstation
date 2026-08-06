#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${GUIYI_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
[[ -d "$PROJECT_ROOT" ]] || { printf '[run-local-service] project root unavailable: %s\n' "$PROJECT_ROOT" >&2; exit 78; }
SERVICE="${1:-}"
RUNTIME_DIR="${GUIYI_RUNTIME_DIR:-$HOME/Library/Application Support/GuiyiQuant}"
RUNTIME_ENV="${GUIYI_RUNTIME_ENV:-$RUNTIME_DIR/project.env}"
PYTHON_BIN="$PROJECT_ROOT/services/quant-api/.venv/bin/python"

if [[ -f "$RUNTIME_ENV" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$RUNTIME_ENV"
  set +a
elif [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.env"
  set +a
fi

[[ -n "${POSTGRES_PASSWORD:-}" ]] || { printf '[run-local-service] POSTGRES_PASSWORD missing\n' >&2; exit 2; }
export REDIS_PASSWORD="${REDIS_PASSWORD:-$POSTGRES_PASSWORD}"
if [[ -z "${REDIS_URL:-}" || "$REDIS_URL" == "redis://127.0.0.1:6379/0" ]]; then
  export REDIS_URL="redis://:${REDIS_PASSWORD}@127.0.0.1:6379/0"
fi
export PYTHONPATH="$PROJECT_ROOT/services/quant-api:$PROJECT_ROOT/packages/quant-core${PYTHONPATH:+:$PYTHONPATH}"

case "$SERVICE" in
  api|worker-backtests|worker-signals|worker-notifications)
    [[ -x "$PYTHON_BIN" ]] || { printf '[run-local-service] runtime python unavailable: %s\n' "$PYTHON_BIN" >&2; exit 78; }
    ;;
esac

case "$SERVICE" in
  api)
    exec "$PYTHON_BIN" -m uvicorn app.main:app --app-dir "$PROJECT_ROOT/services/quant-api" --host 127.0.0.1 --port 8000 --workers 2 --no-access-log
    ;;
  worker-backtests)
    cd "$PROJECT_ROOT/services/quant-api"
    exec "$PYTHON_BIN" -m app.worker backtests
    ;;
  worker-signals)
    cd "$PROJECT_ROOT/services/quant-api"
    exec "$PYTHON_BIN" -m app.worker signals
    ;;
  worker-notifications)
    [[ "${GUIYI_WECHAT_AUTOSEND_ENABLED:-0}" =~ ^(1|true|yes|on)$ ]] || { printf '[run-local-service] notification autosend is disabled\n' >&2; exit 78; }
    cd "$PROJECT_ROOT/services/quant-api"
    exec "$PYTHON_BIN" -m app.worker notifications
    ;;
  web)
    [[ -f "$PROJECT_ROOT/apps/quant-web/dist/index.html" ]] || { printf '[run-local-service] frontend dist missing; run pnpm --dir apps/quant-web build\n' >&2; exit 2; }
    [[ -f "$PROJECT_ROOT/apps/quant-web/node_modules/vite/bin/vite.js" ]] || { printf '[run-local-service] frontend vite entrypoint missing; run pnpm --dir apps/quant-web install\n' >&2; exit 2; }
    exec node "$PROJECT_ROOT/apps/quant-web/node_modules/vite/bin/vite.js" preview "$PROJECT_ROOT/apps/quant-web" --host 127.0.0.1 --port 5173
    ;;
  *)
    printf '[run-local-service] unknown service: %s\n' "$SERVICE" >&2
    exit 2
    ;;
esac
