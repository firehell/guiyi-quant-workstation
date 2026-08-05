#!/usr/bin/env bash
# Aggregate MAIN 5m/15m/30m/60m from local passed 1m for full universe.
# Never calls RQData.
#
# Usage:
#   bash scripts/rqdata_aggregate_tail_universe.sh
#   DRY_RUN=1 bash scripts/rqdata_aggregate_tail_universe.sh
#   END_DATE=2026-07-11 bash scripts/rqdata_aggregate_tail_universe.sh
#
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PRODUCTS_FILE="${PRODUCTS_FILE:-data/universe/active_products.txt}"
PERIODS="${PERIODS:-5m,15m,30m,60m}"
DRY_RUN="${DRY_RUN:-0}"
FORCE="${FORCE:-0}"
NO_REGISTER="${NO_REGISTER:-0}"

IFS=',' read -ra period_list <<< "$PERIODS"
period_args=()
for period in "${period_list[@]}"; do
  period="${period// /}"
  [[ -z "$period" ]] && continue
  period_args+=(--period "$period")
done

extra_args=()
if [[ -n "${END_DATE:-}" ]]; then
  extra_args+=(--end-date "$END_DATE")
fi
if [[ "$DRY_RUN" == "1" ]]; then
  extra_args+=(--dry-run)
fi
if [[ "$FORCE" == "1" ]]; then
  extra_args+=(--force)
fi
if [[ "$NO_REGISTER" == "1" ]]; then
  extra_args+=(--no-register)
fi

echo "=== aggregate MAIN ${PERIODS} from local 1m (products=${PRODUCTS_FILE}) ==="
uv run --project services/quant-api python scripts/rqdata_aggregate_main_universe.py run \
  --products-file "$PRODUCTS_FILE" \
  "${period_args[@]}" \
  ${extra_args[@]+"${extra_args[@]}"}
