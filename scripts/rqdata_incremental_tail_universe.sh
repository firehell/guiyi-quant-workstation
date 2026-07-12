#!/usr/bin/env bash
# Incrementally append MAIN 1m/1d/1w bars to END_DATE (default: today).
# Does NOT full-refresh history; only downloads delta tail from RQData.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

END_DATE="${END_DATE:-$(date +%F)}"
PERIODS="${PERIODS:-1m,1d,1w}"
PRODUCTS_FILE="${PRODUCTS_FILE:-data/universe/full_products_90.txt}"
ALLOW_QUALITY_FAILED="${ALLOW_QUALITY_FAILED:-0}"
DRY_RUN="${DRY_RUN:-0}"

IFS=',' read -ra period_list <<< "$PERIODS"
period_args=()
for period in "${period_list[@]}"; do
  period="${period// /}"
  [[ -z "$period" ]] && continue
  period_args+=(--period "$period")
done

register_args=()
if [[ "$ALLOW_QUALITY_FAILED" == "1" ]]; then
  register_args+=(--allow-quality-failed)
else
  register_args+=(--no-allow-quality-failed)
fi

dry_run_args=()
if [[ "$DRY_RUN" == "1" ]]; then
  dry_run_args+=(--dry-run)
fi

uv run --project services/quant-api python scripts/rqdata_dominant_v2_incremental_tail.py run \
  --end-date "$END_DATE" \
  --products-file "$PRODUCTS_FILE" \
  "${period_args[@]}" \
  ${register_args[@]+"${register_args[@]}"} \
  ${dry_run_args[@]+"${dry_run_args[@]}"}
