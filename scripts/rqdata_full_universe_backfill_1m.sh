#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

UV=(uv run --project services/quant-api python)
BATCH="${BATCH:-today}"
STARTS_FILE="${STARTS_FILE:-data/universe/product_1d_start_from_2020.csv}"
GAP_END_DATE="${GAP_END_DATE:-2023-01-02}"
GLOBAL_END="${GLOBAL_END:-2026-07-10}"
LAYER="${LAYER:-today}"
PERIODS="${PERIODS:-1m}"
AGGREGATE_PERIODS="${AGGREGATE_PERIODS:-5m,15m,30m,60m}"
REPORT_PATH="${REPORT_PATH:-data/reports/full_universe_backfill_1m_report.csv}"
PROGRESS_PATH="${PROGRESS_PATH:-data/reports/full_universe_backfill_1m_progress.md}"

BACKFILL_EXTRA_ARGS=()
REGISTER_EXTRA_ARGS=()
if [[ "${ALLOW_QUALITY_FAILED:-0}" == "1" ]]; then
  BACKFILL_EXTRA_ARGS+=(--allow-quality-failed)
  REGISTER_EXTRA_ARGS+=(--allow-quality-failed)
fi

_resolve_products_file() {
  local batch="$1"
  case "$batch" in
    today)
      echo "${ROOT}/data/universe/products_backfill_1m_today.txt"
      ;;
    remainder)
      echo "${ROOT}/data/universe/products_backfill_1m_remainder.txt"
      ;;
    all)
      echo "${ROOT}/data/universe/active_products.txt"
      ;;
    0*)
      echo "${ROOT}/data/universe/products_backfill_1m_batch${batch}.txt"
      ;;
    *)
      if [[ -f "$batch" ]]; then
        echo "$batch"
      else
        echo "${ROOT}/data/universe/products_backfill_1m_${batch}.txt"
      fi
      ;;
  esac
}

PRODUCTS_FILE="${PRODUCTS_FILE:-$(_resolve_products_file "$BATCH")}"

_layer1_period_args() {
  echo "${PERIODS:-1m}"
}

_aggregate_period_list() {
  local period
  IFS=',' read -ra period_list <<< "${AGGREGATE_PERIODS:-5m,15m,30m,60m}"
  for period in "${period_list[@]}"; do
    period="${period// /}"
    [[ -z "$period" ]] && continue
    echo "$period"
  done
}

_read_summary_window() {
  local product="$1"
  "${UV[@]}" - <<'PY' "$product"
import json
import re
import sys
from datetime import date
from pathlib import Path

product = sys.argv[1].strip().lower()
root = Path("data/processed/v1b") / product
pattern = re.compile(rf"^{re.escape(product)}_v2_parquet_(\d{{8}})_(\d{{8}})\.json$")
candidates: list[tuple[date, date, Path]] = []
for path in sorted(root.glob(f"{product}_v2_parquet_*.json")):
    match = pattern.match(path.name)
    if match is None:
        continue
    start = date.fromisoformat(f"{match.group(1)[:4]}-{match.group(1)[4:6]}-{match.group(1)[6:8]}")
    end = date.fromisoformat(f"{match.group(2)[:4]}-{match.group(2)[4:6]}-{match.group(2)[6:8]}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    periods = payload.get("periods") or {}
    if payload.get("mode") == "dominant-v2-backfill" or "1m" in periods:
        candidates.append((start, end, path))
if not candidates:
    raise SystemExit(1)
start, end, _ = sorted(candidates, key=lambda item: (item[0].toordinal(), -item[1].toordinal()))[0]
print(start.isoformat())
print(end.isoformat())
PY
}

run_layer1() {
  "${UV[@]}" scripts/rqdata_dominant_v2_backfill.py \
    --products-file "$PRODUCTS_FILE" \
    --starts-file "$STARTS_FILE" \
    --periods "$(_layer1_period_args)" \
    --global-end "$GLOBAL_END" \
    --report-path "$REPORT_PATH" \
    --run-write --register "${BACKFILL_EXTRA_ARGS[@]}" || echo "WARN layer1 1m backfill completed with failures"
}

run_aggregate_product() {
  local p="$1"
  local window
  if ! window="$(_read_summary_window "$p")"; then
    echo "WARN aggregate skip ${p}: backfill summary not found"
    return 0
  fi
  local out_start out_end period aggregate_args=()
  out_start="$(echo "$window" | sed -n '1p')"
  out_end="$(echo "$window" | sed -n '2p')"
  while IFS= read -r period; do
    [[ -z "$period" ]] && continue
    aggregate_args+=(--period "$period")
  done < <(_aggregate_period_list)
  echo "=== aggregate from extended 1m: ${p} ${out_start}..${out_end} periods=${AGGREGATE_PERIODS} ==="
  "${UV[@]}" scripts/rqdata_dominant_v2_parquet.py \
    --product "$p" \
    --start-date "$out_start" \
    --end-date "$out_end" \
    "${aggregate_args[@]}" \
    --force || echo "WARN aggregate parquet failed: $p"
  "${UV[@]}" scripts/rqdata_dominant_v2_register_quality.py \
    --product "$p" \
    --start-date "$out_start" \
    --end-date "$out_end" \
    "${REGISTER_EXTRA_ARGS[@]}" || echo "WARN aggregate register failed: $p"
}

run_aggregate_batch() {
  while IFS= read -r p; do
    [[ -z "$p" || "$p" =~ ^# ]] && continue
    run_aggregate_product "$p"
  done < "$PRODUCTS_FILE"
}

run_dry_run() {
  "${UV[@]}" scripts/rqdata_dominant_v2_backfill.py \
    --products-file "$PRODUCTS_FILE" \
    --starts-file "$STARTS_FILE" \
    --periods "$(_layer1_period_args)" \
    --global-end "$GLOBAL_END" \
    --report-path "$REPORT_PATH" \
    --dry-run
}

case "$LAYER" in
  dry-run)
    run_dry_run
    ;;
  layer1)
    run_layer1
    ;;
  aggregate)
    run_aggregate_batch
    ;;
  today)
    run_layer1
    run_aggregate_batch
    ;;
  all)
    PRODUCTS_FILE="${ROOT}/data/universe/active_products.txt"
    run_layer1
    run_aggregate_batch
    ;;
  *)
    echo "Unknown LAYER=$LAYER (dry-run|layer1|aggregate|today|all)" >&2
    exit 1
    ;;
esac

echo "done layer=$LAYER batch=$BATCH products_file=$PRODUCTS_FILE report=$REPORT_PATH progress=$PROGRESS_PATH"
