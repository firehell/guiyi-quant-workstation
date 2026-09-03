#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${GUIYI_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
SERVICE="${1:-}"
preflight_unavailable() {
  printf '%s\n' '{"schema_version":1,"command":"runtime.market-promotion-preflight","status":"blocked","reason":"MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE","trading_day":null,"operational_count":0,"snapshot_count":0}'
}
if [[ ! -d "$PROJECT_ROOT" ]]; then
  if [[ "$SERVICE" == "market-runtime-preflight" ]]; then
    preflight_unavailable
    exit 1
  fi
  printf '[run-local-service] project root unavailable: %s\n' "$PROJECT_ROOT" >&2
  exit 78
fi
RUNTIME_DIR="${GUIYI_RUNTIME_DIR:-$HOME/Library/Application Support/GuiyiQuant}"
RUNTIME_ENV="${GUIYI_RUNTIME_ENV:-$RUNTIME_DIR/project.env}"
PYTHON_BIN="$PROJECT_ROOT/services/quant-api/.venv/bin/python"
LAUNCHER_ALERT_NOTIFICATION_CONFIG_PATH="${GUIYI_ALERT_NOTIFICATION_CONFIG_PATH:-}"

if [[ "$SERVICE" == "market-runtime-preflight" ]]; then
  if [[ ! -x "$PYTHON_BIN" ]]; then
    preflight_unavailable
    exit 1
  fi
  set -a
  if [[ -f "$RUNTIME_ENV" ]]; then
    if ! source "$RUNTIME_ENV" >/dev/null 2>&1; then
      set +a
      preflight_unavailable
      exit 1
    fi
  elif [[ -f "$PROJECT_ROOT/.env" ]]; then
    if ! source "$PROJECT_ROOT/.env" >/dev/null 2>&1; then
      set +a
      preflight_unavailable
      exit 1
    fi
  fi
  set +a
  if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
    preflight_unavailable
    exit 1
  fi
  export REDIS_PASSWORD="${REDIS_PASSWORD:-$POSTGRES_PASSWORD}"
  if [[ -z "${REDIS_URL:-}" || "$REDIS_URL" == "redis://127.0.0.1:6379/0" ]]; then
    export REDIS_URL="redis://:${REDIS_PASSWORD}@127.0.0.1:6379/0"
  fi
  exec "$PYTHON_BIN" -m app.market_data.runtime_promotion
fi

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

[[ -z "$LAUNCHER_ALERT_NOTIFICATION_CONFIG_PATH" ]] || export GUIYI_ALERT_NOTIFICATION_CONFIG_PATH="$LAUNCHER_ALERT_NOTIFICATION_CONFIG_PATH"

[[ -n "${POSTGRES_PASSWORD:-}" ]] || { printf '[run-local-service] POSTGRES_PASSWORD missing\n' >&2; exit 2; }
export REDIS_PASSWORD="${REDIS_PASSWORD:-$POSTGRES_PASSWORD}"
if [[ -z "${REDIS_URL:-}" || "$REDIS_URL" == "redis://127.0.0.1:6379/0" ]]; then
  export REDIS_URL="redis://:${REDIS_PASSWORD}@127.0.0.1:6379/0"
fi
case "$SERVICE" in
  api)
    [[ -x "$PYTHON_BIN" ]] || { printf '[run-local-service] runtime python unavailable: %s\n' "$PYTHON_BIN" >&2; exit 78; }
    exec "$PYTHON_BIN" -m uvicorn app.main:app --app-dir "$PROJECT_ROOT/services/quant-api" --host 127.0.0.1 --port 8000 --workers 2 --no-access-log
    ;;
  live)
    [[ -x "$PYTHON_BIN" ]] || { printf '[run-local-service] runtime python unavailable: %s\n' "$PYTHON_BIN" >&2; exit 78; }
    exec "$PYTHON_BIN" -m app.runtime_entry live
    ;;
  alert)
    [[ -x "$PYTHON_BIN" ]] || { printf '[run-local-service] runtime python unavailable: %s\n' "$PYTHON_BIN" >&2; exit 78; }
    exec "$PYTHON_BIN" -m app.runtime_entry alert
    ;;
  after-market)
    [[ -x "$PYTHON_BIN" ]] || { printf '[run-local-service] runtime python unavailable: %s\n' "$PYTHON_BIN" >&2; exit 78; }
    exec "$PYTHON_BIN" -m app.runtime_entry after-market
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
