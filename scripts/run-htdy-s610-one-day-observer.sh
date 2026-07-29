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
  phase="$(python3 - "${GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET:?}" <<'PY'
from datetime import datetime, time, timedelta
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

parent = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if (
    parent.get("schema_version") == 1
    and parent.get("request_type")
    == "htdy_s6_10_approval_d_no_code_promotion"
):
    print("long")
    raise SystemExit(0)
zone = ZoneInfo("Asia/Shanghai")
window_end = (
    datetime.fromisoformat(parent["window_end"])
    if parent.get("window_end")
    else datetime.combine(
        datetime.fromisoformat(parent["trading_days"][0]).date(),
        time(16),
        tzinfo=zone,
    )
)
now = datetime.now(zone)
if now < window_end:
    print("observe")
elif now <= window_end + timedelta(hours=3):
    print("finalize")
else:
    print("stop")
PY
)"
  if [[ "$phase" == "stop" ]]; then
    exit 0
  fi
  if [[ "$phase" == "long" ]]; then
    PYTHONPATH="services/quant-api:packages/quant-core:." \
      uv run --project services/quant-api python \
      scripts/jm_htdy_s6_10_one_day_gate.py long-running-heartbeat \
      --parent "${GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET:?}" \
      --approval-hash "${GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH:?}"
    sleep 60
    continue
  fi
  if [[ -f "${GUIYI_HTDY_S610_OUTPUT_DIR:?}/remaining_window/final_acceptance.json" ]]; then
    exit 0
  fi
  sample_args=(
    --parent "${GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET:?}"
    --approval-hash "${GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH:?}"
    --output-dir "${GUIYI_HTDY_S610_OUTPUT_DIR:?}"
    --runtime-log "$HOME/Library/Logs/GuiyiQuant/runtime-scheduler.log"
  )
  if [[ "$phase" == "finalize" ]]; then
    sample_args+=(--post-window-finalize)
  fi
  PYTHONPATH="services/quant-api:packages/quant-core:." \
    uv run --project services/quant-api python \
    scripts/jm_htdy_s6_10_one_day_gate.py sample \
    "${sample_args[@]}"
  sleep 60
done
