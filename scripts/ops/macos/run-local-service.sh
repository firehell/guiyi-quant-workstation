#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${GUIYI_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
SERVICE="${1:-}"
preflight_unavailable() {
  printf '%s\n' '{"schema_version":1,"command":"runtime.market-promotion-preflight","status":"blocked","reason":"MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE","trading_day":null,"operational_count":0,"snapshot_count":0}'
}
is_safe_absolute_path() {
  local path="$1" component
  local -a components
  [[ "$path" == /* && "$path" != *$'\n'* && "$path" != *$'\r'* && "$path" != *$'\t'* ]] || return 1
  IFS='/' read -r -a components <<<"${path#/}"
  for component in "${components[@]}"; do
    [[ "$component" != ".." ]] || return 1
  done
}
market_runtime_status_path() {
  local plist="$HOME/Library/LaunchAgents/com.guiyi.quant-after-market.plist"
  local configured_root="" loaded_root="" launch_output="" root domain_output=""
  local label_absent=false
  domain_output="$(launchctl print "gui/$UID" 2>&1)" || return 1
  if [[ -e "$plist" || -L "$plist" ]]; then
    [[ -f "$plist" && ! -L "$plist" ]] || return 1
    configured_root="$(plutil -extract EnvironmentVariables.GUIYI_PROJECT_ROOT raw -o - "$plist" 2>/dev/null)" || return 1
    is_safe_absolute_path "$configured_root" && [[ -d "$configured_root" && ! -L "$configured_root" ]] || return 1
  fi
  if launch_output="$(launchctl print "gui/$UID/com.guiyi.quant-after-market" 2>&1)"; then
    loaded_root="$(printf '%s\n' "$launch_output" | sed -n 's/^[[:space:]]*GUIYI_PROJECT_ROOT => //p' | head -1)"
    is_safe_absolute_path "$loaded_root" && [[ -d "$loaded_root" && ! -L "$loaded_root" ]] || return 1
  elif [[ "$launch_output" == *"Could not find service"* ]]; then
    label_absent=true
  else
    return 1
  fi
  if [[ "$label_absent" == true && -n "$configured_root" ]]; then
    return 1
  fi
  if [[ -n "$configured_root" && -n "$loaded_root" && "$configured_root" != "$loaded_root" ]]; then
    return 1
  fi
  root="${loaded_root:-$configured_root}"
  if [[ -z "$root" ]]; then
    # Only domain-readable, label-absent, no-installed-plist first installation.
    [[ "$label_absent" == true ]] || return 1
    root="$PROJECT_ROOT"
  fi
  is_safe_absolute_path "$root" && [[ -d "$root" && ! -L "$root" ]] || return 1
  printf '%s/.run/after-market-status.json\n' "$root"
}
is_passed_preflight_payload() {
  local payload="$1"
  local pattern='^\{"schema_version":1,"command":"runtime.market-promotion-preflight","status":"passed","reason":"(snapshot_ready|before_first_session|after_market_complete|non_trading_interval)","trading_day":(null|"[0-9]{4}-[0-9]{2}-[0-9]{2}"),"operational_count":[0-9]+,"snapshot_count":[0-9]+\}$'
  [[ "$payload" =~ $pattern ]]
}
is_blocked_preflight_payload() {
  local payload="$1"
  local pattern='^\{"schema_version":1,"command":"runtime.market-promotion-preflight","status":"blocked","reason":"(MARKET_RUNTIME_PROMOTION_LIVE_SNAPSHOT_REQUIRED|MARKET_RUNTIME_PROMOTION_LIVE_SNAPSHOT_INVALID|MARKET_RUNTIME_PROMOTION_STATE_UNAVAILABLE)","trading_day":(null|"[0-9]{4}-[0-9]{2}-[0-9]{2}"),"operational_count":[0-9]+,"snapshot_count":[0-9]+\}$'
  [[ "$payload" =~ $pattern ]]
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
  preflight_env=""
  controlled_status_path="${GUIYI_AFTER_MARKET_STATUS_PATH:-}"
  if [[ -z "$controlled_status_path" ]]; then
    if ! controlled_status_path="$(market_runtime_status_path)"; then
      preflight_unavailable
      exit 1
    fi
  fi
  if [[ -n "$controlled_status_path" ]] && { ! is_safe_absolute_path "$controlled_status_path" || [[ "${controlled_status_path##*/}" != "after-market-status.json" ]]; }; then
    preflight_unavailable
    exit 1
  fi
  if [[ -f "$RUNTIME_ENV" ]]; then
    preflight_env="$RUNTIME_ENV"
  elif [[ -f "$PROJECT_ROOT/.env" ]]; then
    preflight_env="$PROJECT_ROOT/.env"
  fi
  if preflight_output="$(
    /bin/bash -euo pipefail -c '
      readonly runtime_env="$1"
      readonly python_bin="$2"
      readonly controlled_status_path="$3"
      readonly GUIYI_AFTER_MARKET_STATUS_PATH="$controlled_status_path"
      export GUIYI_AFTER_MARKET_STATUS_PATH
      if [[ -n "$runtime_env" ]]; then
        set -a
        source "$runtime_env" >/dev/null 2>&1
        set +a
      fi
      [[ -n "${POSTGRES_PASSWORD:-}" ]] || exit 64
      export REDIS_PASSWORD="${REDIS_PASSWORD:-$POSTGRES_PASSWORD}"
      if [[ -z "${REDIS_URL:-}" || "$REDIS_URL" == "redis://127.0.0.1:6379/0" ]]; then
        export REDIS_URL="redis://:${REDIS_PASSWORD}@127.0.0.1:6379/0"
      fi
      exec "$python_bin" -m app.market_data.runtime_promotion
    ' bash "$preflight_env" "$PYTHON_BIN" "$controlled_status_path" 2>/dev/null
  )"; then
    preflight_result=0
  else
    preflight_result=$?
  fi
  if [[ "$preflight_result" == "0" ]] && is_passed_preflight_payload "$preflight_output"; then
    printf '%s\n' "$preflight_output"
    exit 0
  fi
  if [[ "$preflight_result" != "0" ]] && is_blocked_preflight_payload "$preflight_output"; then
    printf '%s\n' "$preflight_output"
    exit 1
  fi
  if [[ -z "${preflight_output:-}" ]]; then
    preflight_unavailable
    exit 1
  fi
  preflight_unavailable
  exit 1
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
