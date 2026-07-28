#!/usr/bin/env bash
set -euo pipefail

runtime_root="${GUIYI_PROJECT_ROOT:-}"
runtime_dir="${GUIYI_RUNTIME_DIR:-$HOME/Library/Application Support/GuiyiQuant}"
runtime_env="${GUIYI_RUNTIME_ENV:-$runtime_dir/project.env}"
[[ -d "$runtime_root" && -f "$runtime_env" ]] || exit 2
set -a
# shellcheck disable=SC1090
source "$runtime_env"
set +a
[[ -n "${POSTGRES_PASSWORD:-}" ]] || exit 2
export REDIS_PASSWORD="${REDIS_PASSWORD:-$POSTGRES_PASSWORD}"
if [[ -z "${REDIS_URL:-}" || "$REDIS_URL" == "redis://127.0.0.1:6379/0" ]]; then
  export REDIS_URL="redis://:${REDIS_PASSWORD}@127.0.0.1:6379/0"
fi
[[ "${GUIYI_LIVE_SIGNAL_EVENTS_ENABLED:-false}" == "true" ]] || exit 2
[[ "${GUIYI_WECHAT_AUTOSEND_ENABLED:-false}" == "false" ]] || exit 2

cd "$runtime_root"
while true; do
  PYTHONPATH="services/quant-api:packages/quant-core:." \
    uv run --project services/quant-api python \
    scripts/jm_htdy_s6_10_one_day_gate.py sample \
    --parent "${GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET:?}" \
    --approval-hash "${GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH:?}" \
    --output-dir "${GUIYI_HTDY_S610_OUTPUT_DIR:?}" \
    --runtime-log "$HOME/Library/Logs/GuiyiQuant/runtime-scheduler.log"
  sleep 60
done
