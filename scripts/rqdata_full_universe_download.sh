#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

UV=(uv run --project services/quant-api python)
PRODUCTS_FILE="${PRODUCTS_FILE:-data/universe/full_products_90.txt}"
START_DATE="${START_DATE:-2023-01-03}"
END_DATE="${END_DATE:-2026-07-07}"
TRADE_DATE="${TRADE_DATE:-2026-07-07}"
UNIVERSE_START="${UNIVERSE_START:-2024-01-01}"
BASELINE_START="${BASELINE_START:-2010-01-04}"
LAYER="${LAYER:-all}"

run_layer0_product() {
  local p="$1"
  echo "=== metadata: $p ==="
  "${UV[@]}" scripts/rqdata_main_mapping_sync.py run \
    --product "$p" --start-date "$START_DATE" --end-date "$END_DATE" --ranks 1 2 --resume || echo "WARN layer0 main_mapping failed: $p"
  "${UV[@]}" scripts/rqdata_contract_universe_sync.py run \
    --product "$p" --start-date "$UNIVERSE_START" --end-date "$END_DATE" --resume || echo "WARN layer0 contract_universe failed: $p"
  "${UV[@]}" scripts/rqdata_continuous_contracts_sync.py run \
    --product "$p" --start-date "$UNIVERSE_START" --end-date "$END_DATE" --resume || echo "WARN layer0 continuous_contracts failed: $p"
  "${UV[@]}" scripts/rqdata_trading_params_sync.py run \
    --product "$p" --start-date "$START_DATE" --end-date "$END_DATE" --resume || echo "WARN layer0 trading_params failed: $p"
  "${UV[@]}" scripts/rqdata_ex_factor_sync.py run \
    --product "$p" --start-date "$START_DATE" --end-date "$END_DATE" --resume || echo "WARN layer0 ex_factor failed: $p"
  "${UV[@]}" scripts/rqdata_dominant_daily_baseline_sync.py run \
    --product "$p" --start-date "$BASELINE_START" --end-date "$END_DATE" --resume || echo "WARN layer0 dominant_daily_baseline failed: $p"
}

run_layer1_product() {
  local p="$1"
  if [[ "$p" == "jm" ]]; then
    echo "=== skip dominant MAIN: jm (existing v2) ==="
    return 0
  fi
  echo "=== dominant MAIN: $p ==="
  "${UV[@]}" scripts/rqdata_dominant_v2_parquet.py \
    --product "$p" --start-date "$START_DATE" --end-date "$END_DATE" || echo "WARN layer1 parquet failed: $p"
  "${UV[@]}" scripts/rqdata_dominant_v2_register_quality.py \
    --product "$p" --start-date "$START_DATE" --end-date "$END_DATE" || echo "WARN layer1 register failed: $p"
}

run_layer2_product() {
  local p="$1"
  echo "=== actual_contract roll: $p ==="
  "${UV[@]}" scripts/rqdata_actual_contract_bars_pilot.py \
    --product "$p" --trade-date "$TRADE_DATE" \
    --start-date "$START_DATE" --end-date "$END_DATE" \
    --roll-segments --run-write || echo "WARN layer2 actual_contract failed: $p"
}

run_layer4_product() {
  local p="$1"
  echo "=== research: $p ==="
  "${UV[@]}" scripts/rqdata_research_enhancers_sync.py run \
    --product "$p" --start-date "$START_DATE" --end-date "$END_DATE" --resume || echo "WARN layer4 research_enhancers failed: $p"
  "${UV[@]}" scripts/rqdata_market_samples_sync.py run \
    --product "$p" --start-date "$BASELINE_START" --end-date "$END_DATE" --resume || echo "WARN layer4 market_samples failed: $p"
}

case "$LAYER" in
  step1)
    "${UV[@]}" scripts/rqdata_catalog_sync.py run --start-date "$START_DATE" --end-date "$END_DATE"
    "${UV[@]}" scripts/rqdata_coverage_audit.py run
    ;;
  layer0)
    while IFS= read -r p; do
      [[ -z "$p" || "$p" =~ ^# ]] && continue
      run_layer0_product "$p"
    done < "$PRODUCTS_FILE"
    ;;
  layer1)
    while IFS= read -r p; do
      [[ -z "$p" || "$p" =~ ^# ]] && continue
      run_layer1_product "$p"
    done < "$PRODUCTS_FILE"
    ;;
  layer2)
    while IFS= read -r p; do
      [[ -z "$p" || "$p" =~ ^# ]] && continue
      run_layer2_product "$p"
    done < "$PRODUCTS_FILE"
    ;;
  layer4)
    while IFS= read -r p; do
      [[ -z "$p" || "$p" =~ ^# ]] && continue
      run_layer4_product "$p"
    done < "$PRODUCTS_FILE"
    ;;
  audit)
    "${UV[@]}" scripts/rqdata_coverage_audit.py run
    uv run --project services/quant-api pytest -q \
      services/quant-api/tests/test_rqdata_jm_v2_parquet.py \
      services/quant-api/tests/test_actual_contract_bars_pilot.py \
      services/quant-api/tests/test_market_data_reader.py \
      services/quant-api/tests/test_rqdata_structured_ingest.py
    ;;
  all)
    "${UV[@]}" scripts/rqdata_catalog_sync.py run --start-date "$START_DATE" --end-date "$END_DATE"
    while IFS= read -r p; do
      [[ -z "$p" || "$p" =~ ^# ]] && continue
      run_layer0_product "$p"
    done < "$PRODUCTS_FILE"
    while IFS= read -r p; do
      [[ -z "$p" || "$p" =~ ^# ]] && continue
      run_layer1_product "$p"
    done < "$PRODUCTS_FILE"
    while IFS= read -r p; do
      [[ -z "$p" || "$p" =~ ^# ]] && continue
      run_layer2_product "$p"
    done < "$PRODUCTS_FILE"
    while IFS= read -r p; do
      [[ -z "$p" || "$p" =~ ^# ]] && continue
      run_layer4_product "$p"
    done < "$PRODUCTS_FILE"
    "${UV[@]}" scripts/rqdata_coverage_audit.py run
    uv run --project services/quant-api pytest -q \
      services/quant-api/tests/test_rqdata_jm_v2_parquet.py \
      services/quant-api/tests/test_actual_contract_bars_pilot.py \
      services/quant-api/tests/test_market_data_reader.py \
      services/quant-api/tests/test_rqdata_structured_ingest.py
    ;;
  pipeline)
    while IFS= read -r p; do
      [[ -z "$p" || "$p" =~ ^# ]] && continue
      run_layer0_product "$p"
    done < "$PRODUCTS_FILE"
    while IFS= read -r p; do
      [[ -z "$p" || "$p" =~ ^# ]] && continue
      run_layer1_product "$p"
    done < "$PRODUCTS_FILE"
    while IFS= read -r p; do
      [[ -z "$p" || "$p" =~ ^# ]] && continue
      run_layer2_product "$p"
    done < "$PRODUCTS_FILE"
    while IFS= read -r p; do
      [[ -z "$p" || "$p" =~ ^# ]] && continue
      run_layer4_product "$p"
    done < "$PRODUCTS_FILE"
    "${UV[@]}" scripts/rqdata_coverage_audit.py run
    uv run --project services/quant-api pytest -q \
      services/quant-api/tests/test_rqdata_jm_v2_parquet.py \
      services/quant-api/tests/test_actual_contract_bars_pilot.py \
      services/quant-api/tests/test_market_data_reader.py \
      services/quant-api/tests/test_rqdata_structured_ingest.py
    ;;
  *)
    echo "Unknown LAYER=$LAYER (step1|layer0|layer1|layer2|layer4|audit|all|pipeline)" >&2
    exit 1
    ;;
esac

echo "done layer=$LAYER"
