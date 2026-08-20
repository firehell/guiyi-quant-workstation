#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${GUIYI_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
[[ -d "$PROJECT_ROOT" ]] || { printf '[run-local-service] project root unavailable: %s\n' "$PROJECT_ROOT" >&2; exit 78; }
SERVICE="${1:-}"
RUNTIME_DIR="${GUIYI_RUNTIME_DIR:-$HOME/Library/Application Support/GuiyiQuant}"
RUNTIME_ENV="${GUIYI_RUNTIME_ENV:-$RUNTIME_DIR/project.env}"
PYTHON_BIN="$PROJECT_ROOT/services/quant-api/.venv/bin/python"
LAUNCHER_OPENCLAW_BIN="${GUIYI_OPENCLAW_BIN:-}"
LAUNCHER_OPENCLAW_NODE_BIN="${GUIYI_OPENCLAW_NODE_BIN:-}"
LAUNCHER_OPENCLAW_WEIXIN_PLUGIN_ROOT="${GUIYI_OPENCLAW_WEIXIN_PLUGIN_ROOT:-}"
LAUNCHER_OPENCLAW_STATE_DIR="${GUIYI_OPENCLAW_STATE_DIR:-}"
LAUNCHER_OPENCLAW_CONFIG_PATH="${GUIYI_OPENCLAW_CONFIG_PATH:-}"
LAUNCHER_ALERT_CLAWBOT_RECIPIENTS_PATH="${GUIYI_ALERT_CLAWBOT_RECIPIENTS_PATH:-}"

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

[[ -z "$LAUNCHER_OPENCLAW_BIN" ]] || export GUIYI_OPENCLAW_BIN="$LAUNCHER_OPENCLAW_BIN"
[[ -z "$LAUNCHER_OPENCLAW_NODE_BIN" ]] || export GUIYI_OPENCLAW_NODE_BIN="$LAUNCHER_OPENCLAW_NODE_BIN"
[[ -z "$LAUNCHER_OPENCLAW_WEIXIN_PLUGIN_ROOT" ]] || export GUIYI_OPENCLAW_WEIXIN_PLUGIN_ROOT="$LAUNCHER_OPENCLAW_WEIXIN_PLUGIN_ROOT"
[[ -z "$LAUNCHER_OPENCLAW_STATE_DIR" ]] || export GUIYI_OPENCLAW_STATE_DIR="$LAUNCHER_OPENCLAW_STATE_DIR"
[[ -z "$LAUNCHER_OPENCLAW_CONFIG_PATH" ]] || export GUIYI_OPENCLAW_CONFIG_PATH="$LAUNCHER_OPENCLAW_CONFIG_PATH"
[[ -z "$LAUNCHER_ALERT_CLAWBOT_RECIPIENTS_PATH" ]] || export GUIYI_ALERT_CLAWBOT_RECIPIENTS_PATH="$LAUNCHER_ALERT_CLAWBOT_RECIPIENTS_PATH"

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
    exec "$PYTHON_BIN" -m app.guiyi_cli.main runtime live
    ;;
  alert)
    [[ -x "$PYTHON_BIN" ]] || { printf '[run-local-service] runtime python unavailable: %s\n' "$PYTHON_BIN" >&2; exit 78; }
    exec "$PYTHON_BIN" -m app.guiyi_cli.main runtime alert
    ;;
  after-market)
    [[ -x "$PYTHON_BIN" ]] || { printf '[run-local-service] runtime python unavailable: %s\n' "$PYTHON_BIN" >&2; exit 78; }
    exec "$PYTHON_BIN" -m app.guiyi_cli.main data after-market
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
