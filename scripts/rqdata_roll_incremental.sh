#!/usr/bin/env bash
# Generic incremental roll actual_contract backfill.
# Per product: contract_universe -> trading_params -> roll-segments write.
# Env: PRODUCTS_FILE, START_DATE, END_DATE, TRADE_DATE, PERIODS, LOG_DIR
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

UV=(uv run --project services/quant-api python)
PRODUCTS_FILE="${PRODUCTS_FILE:-data/universe/full_products_90.txt}"
START_DATE="${START_DATE:-2010-01-04}"
END_DATE="${END_DATE:-2026-07-10}"
TRADE_DATE="${TRADE_DATE:-2026-07-10}"
PERIODS="${PERIODS:-1d,1w}"
LOG_DIR="${LOG_DIR:-data/reports/roll_incremental}"
mkdir -p "$LOG_DIR"

run_product() {
  local p="$1"
  local log="$LOG_DIR/${p}.log"
  {
    echo "=== [$p] contract_universe $START_DATE..$END_DATE ==="
    "${UV[@]}" scripts/rqdata_contract_universe_sync.py run \
      --product "$p" --start-date "$START_DATE" --end-date "$END_DATE" --resume \
      || echo "WARN contract_universe failed: $p"

    echo "=== [$p] trading_params $START_DATE..$END_DATE (retry-failed) ==="
    "${UV[@]}" scripts/rqdata_trading_params_sync.py run \
      --product "$p" --start-date "$START_DATE" --end-date "$END_DATE" --retry-failed \
      || echo "WARN trading_params failed: $p"

    echo "=== [$p] roll-segments periods=$PERIODS ==="
    "${UV[@]}" scripts/rqdata_actual_contract_bars_pilot.py \
      --product "$p" --trade-date "$TRADE_DATE" \
      --start-date "$START_DATE" --end-date "$END_DATE" \
      --periods "$PERIODS" --roll-segments --run-write \
      || echo "WARN roll write failed: $p"
  } >>"$log" 2>&1
  echo "done $p -> $log"
}

while IFS= read -r p; do
  [[ -z "$p" || "$p" =~ ^# ]] && continue
  run_product "$p"
done < "$PRODUCTS_FILE"

echo "ALL DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$LOG_DIR/summary.log"
