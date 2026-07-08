#!/usr/bin/env bash
# Regenerate JM aggregated intraday bars from existing 1m canonical/raw assets.
# Does NOT re-download 1d/1w. Requires RQData quota only if local 1m raw is missing.
#
# Usage (after RQData quota resets):
#   FORCE_AGGREGATE=1 bash scripts/regenerate_jm_aggregated_bars.sh
#
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

UV=(uv run --project services/quant-api python)
START_DATE="${START_DATE:-2023-01-03}"
END_DATE="${END_DATE:-2026-07-07}"
TRADE_DATE="${TRADE_DATE:-2026-07-07}"
PRODUCT="${PRODUCT:-jm}"

echo "=== dominant MAIN: ${PRODUCT} aggregate 5m/15m/30m/60m from 1m ==="
"${UV[@]}" scripts/rqdata_dominant_v2_parquet.py \
  --product "$PRODUCT" \
  --start-date "$START_DATE" \
  --end-date "$END_DATE" \
  --period 1m \
  --period 5m \
  --period 15m \
  --period 30m \
  --period 60m \
  --force

echo "=== register dominant quality ==="
"${UV[@]}" scripts/rqdata_dominant_v2_register_quality.py \
  --product "$PRODUCT" \
  --start-date "$START_DATE" \
  --end-date "$END_DATE"

echo "=== actual-contract roll minute bundle (no 1d) ==="
"${UV[@]}" scripts/rqdata_actual_contract_bars_pilot.py \
  --product "$PRODUCT" \
  --trade-date "$TRADE_DATE" \
  --start-date "$START_DATE" \
  --end-date "$END_DATE" \
  --periods "1m,5m,15m,30m,60m" \
  --roll-segments \
  --run-write

echo "=== Stage 8.6 jm six-period reference audit ==="
"${UV[@]}" scripts/rqdata_full_universe_active_gate_audit.py \
  --products-file data/universe/full_products_90.txt \
  --profile jm_six_period_reference \
  --output-dir data/reports

echo "done regenerate_jm_aggregated_bars product=${PRODUCT}"
