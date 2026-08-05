#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

UV=(uv run --project services/quant-api python)
PRODUCTS_FILE="${PRODUCTS_FILE:-data/universe/active_products.txt}"
STARTS_FILE="${STARTS_FILE:-data/universe/product_1d_start_from_2020.csv}"
START_DATE="${START_DATE:-2020-01-02}"
GAP_END_DATE="${GAP_END_DATE:-2023-01-02}"
GLOBAL_END="${GLOBAL_END:-2026-07-10}"
TRADE_DATE="${TRADE_DATE:-2026-07-10}"
LAYER="${LAYER:-all}"
PERIODS="${PERIODS:-1d,1w}"
REPORT_PATH="${REPORT_PATH:-data/reports/full_universe_backfill_1d_1w_report.csv}"
BACKFILL_EXTRA_ARGS=()
if [[ "${ALLOW_QUALITY_FAILED:-0}" == "1" ]]; then
  BACKFILL_EXTRA_ARGS+=(--allow-quality-failed)
fi

run_layer0_product() {
  local p="$1"
  echo "=== layer0 metadata: $p ($START_DATE..$GAP_END_DATE) ==="
  "${UV[@]}" scripts/rqdata_main_mapping_sync.py run \
    --product "$p" --start-date "$START_DATE" --end-date "$GAP_END_DATE" --ranks 1 2 --resume || echo "WARN layer0 main_mapping failed: $p"
  local tp_args=(--product "$p" --start-date "$START_DATE" --end-date "$GAP_END_DATE")
  if [[ "${TRADING_PARAMS_RESUME:-0}" == "1" ]]; then
    tp_args+=(--resume)
  fi
  "${UV[@]}" scripts/rqdata_trading_params_sync.py run \
    "${tp_args[@]}" || echo "WARN layer0 trading_params failed: $p"
}

run_layer1_product() {
  local p="$1"
  echo "=== layer1 dominant backfill: $p periods=${PERIODS} ==="
  "${UV[@]}" scripts/rqdata_dominant_v2_backfill.py \
    --product "$p" \
    --starts-file "$STARTS_FILE" \
    --periods "$PERIODS" \
    --global-end "$GLOBAL_END" \
    --report-path "$REPORT_PATH" \
    --run-write --register "${BACKFILL_EXTRA_ARGS[@]}" || echo "WARN layer1 backfill failed: $p"
}

run_layer2_product() {
  local p="$1"
  echo "=== layer2 actual_contract roll backfill: $p periods=${PERIODS} ==="
  "${UV[@]}" scripts/rqdata_actual_contract_bars_pilot.py \
    --product "$p" \
    --trade-date "$TRADE_DATE" \
    --start-date "$START_DATE" \
    --end-date "$GAP_END_DATE" \
    --periods "$PERIODS" \
    --roll-segments --run-write || echo "WARN layer2 actual_contract failed: $p"
}

case "$LAYER" in
  dry-run)
    "${UV[@]}" scripts/rqdata_dominant_v2_backfill.py \
      --products-file "$PRODUCTS_FILE" \
      --starts-file "$STARTS_FILE" \
      --periods "$PERIODS" \
      --global-end "$GLOBAL_END" \
      --report-path "$REPORT_PATH" \
      --dry-run
    ;;
  layer0)
    while IFS= read -r p; do
      [[ -z "$p" || "$p" =~ ^# ]] && continue
      run_layer0_product "$p"
    done < "$PRODUCTS_FILE"
    ;;
  layer1)
    "${UV[@]}" scripts/rqdata_dominant_v2_backfill.py \
      --products-file "$PRODUCTS_FILE" \
      --starts-file "$STARTS_FILE" \
      --periods "$PERIODS" \
      --global-end "$GLOBAL_END" \
      --report-path "$REPORT_PATH" \
      --run-write --register "${BACKFILL_EXTRA_ARGS[@]}" || echo "WARN layer1 backfill completed with failures"
    ;;
  layer2)
    while IFS= read -r p; do
      [[ -z "$p" || "$p" =~ ^# ]] && continue
      run_layer2_product "$p"
    done < "$PRODUCTS_FILE"
    ;;
  all)
    while IFS= read -r p; do
      [[ -z "$p" || "$p" =~ ^# ]] && continue
      run_layer0_product "$p"
    done < "$PRODUCTS_FILE"
    "${UV[@]}" scripts/rqdata_dominant_v2_backfill.py \
      --products-file "$PRODUCTS_FILE" \
      --starts-file "$STARTS_FILE" \
      --periods "$PERIODS" \
      --global-end "$GLOBAL_END" \
      --report-path "$REPORT_PATH" \
      --run-write --register "${BACKFILL_EXTRA_ARGS[@]}"
    while IFS= read -r p; do
      [[ -z "$p" || "$p" =~ ^# ]] && continue
      run_layer2_product "$p"
    done < "$PRODUCTS_FILE"
    ;;
  *)
    echo "Unknown LAYER=$LAYER (dry-run|layer0|layer1|layer2|all)" >&2
    exit 1
    ;;
esac

echo "done layer=$LAYER report=$REPORT_PATH"
