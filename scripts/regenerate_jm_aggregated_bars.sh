#!/usr/bin/env bash
# Regenerate JM 5m/15m/30m/60m/1d from an existing passed 1m canonical asset.
# This script never calls RQData and never writes actual-contract assets.
#
# Usage:
#   END_DATE=2026-07-10 bash scripts/regenerate_jm_aggregated_bars.sh
#
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

UV=(uv run --project services/quant-api python)
START_DATE="${START_DATE:-2023-01-03}"
END_DATE="${END_DATE:-2026-07-10}"
PRODUCT="${PRODUCT:-jm}"

echo "=== dominant MAIN: ${PRODUCT} aggregate 5m/15m/30m/60m/1d from local passed 1m ==="
"${UV[@]}" scripts/rqdata_dominant_v2_parquet.py \
  --product "$PRODUCT" \
  --start-date "$START_DATE" \
  --end-date "$END_DATE" \
  --period 5m \
  --period 15m \
  --period 30m \
  --period 60m \
  --period 1d \
  --force

echo "=== register dominant quality ==="
"${UV[@]}" scripts/rqdata_dominant_v2_register_quality.py \
  --product "$PRODUCT" \
  --start-date "$START_DATE" \
  --end-date "$END_DATE"

echo "=== Stage 8.6 full-universe 1d audit ==="
"${UV[@]}" scripts/rqdata_full_universe_active_gate_audit.py \
  --products-file data/universe/full_products_90.txt \
  --profile stage8_6_1d_first \
  --output-dir data/reports

echo "=== JM latest main six-period audit ==="
"${UV[@]}" scripts/rqdata_full_universe_active_gate_audit.py \
  --product "$PRODUCT" \
  --profile jm_main_six_period_latest \
  --output-dir data/reports/jm_main_six_period_latest

echo "done regenerate_jm_aggregated_bars product=${PRODUCT}"
