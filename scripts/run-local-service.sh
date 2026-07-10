#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${GUIYI_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
[[ -d "$PROJECT_ROOT" ]] || { printf '[run-local-service] project root unavailable: %s\n' "$PROJECT_ROOT" >&2; exit 78; }
SERVICE="${1:-}"

if [[ -f "$PROJECT_ROOT/.env" ]]; then
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

case "$SERVICE" in
  api)
    exec uv run --project "$PROJECT_ROOT/services/quant-api" uvicorn app.main:app --app-dir "$PROJECT_ROOT/services/quant-api" --host 127.0.0.1 --port 8000 --workers 2 --no-access-log
    ;;
  worker-backtests)
    cd "$PROJECT_ROOT/services/quant-api"
    exec uv run python -m app.worker backtests
    ;;
  worker-signals)
    cd "$PROJECT_ROOT/services/quant-api"
    exec uv run python -m app.worker signals
    ;;
  web)
    [[ -f "$PROJECT_ROOT/apps/quant-web/dist/index.html" ]] || { printf '[run-local-service] frontend dist missing; run pnpm --dir apps/quant-web build\n' >&2; exit 2; }
    exec pnpm --dir "$PROJECT_ROOT/apps/quant-web" preview --host 127.0.0.1 --port 5173
    ;;
  *)
    printf '[run-local-service] unknown service: %s\n' "$SERVICE" >&2
    exit 2
    ;;
esac
