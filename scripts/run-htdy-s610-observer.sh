#!/usr/bin/env bash
set -euo pipefail

runtime_root="${GUIYI_PROJECT_ROOT:-}"
runtime_dir="${GUIYI_RUNTIME_DIR:-$HOME/Library/Application Support/GuiyiQuant}"
runtime_env="${GUIYI_RUNTIME_ENV:-$runtime_dir/project.env}"

if [[ -z "$runtime_root" || ! -d "$runtime_root" ]]; then
  echo '{"status":"blocked","reason":"runtime_root_unavailable"}' >&2
  exit 2
fi
if [[ ! -f "$runtime_env" ]]; then
  echo '{"status":"blocked","reason":"runtime_env_unavailable"}' >&2
  exit 2
fi
set -a
# shellcheck disable=SC1090
source "$runtime_env"
set +a

output_root="${GUIYI_HTDY_S610_OUTPUT_DIR:-}"
parent_packet="${GUIYI_HTDY_S610_PARENT_PACKET:-}"
approval_hash="${GUIYI_HTDY_S610_APPROVAL_HASH:-}"
if [[ -z "$output_root" || -z "$parent_packet" || -z "$approval_hash" ]]; then
  echo '{"status":"blocked","reason":"s610_observer_binding_missing"}' >&2
  exit 2
fi
if [[ ! -f "$parent_packet" ]]; then
  echo '{"status":"blocked","reason":"s610_parent_packet_missing"}' >&2
  exit 2
fi

cd "$runtime_root"
while true; do
  PYTHONPATH="services/quant-api:packages/quant-core:." \
    uv run --project services/quant-api \
    python scripts/jm_htdy_s6_10_stability_gate.py sample \
    --output-dir "$output_root" \
    --parent-packet "$parent_packet" \
    --approval-hash "$approval_hash"
  sleep 60
done
