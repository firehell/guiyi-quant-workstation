#!/usr/bin/env bash
# Master runner for remaining roll gaps: stage1 (1d/1w remaining 81) then stage2 (1m all 90).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

STAGE1_LOG="data/reports/roll_1d_1w_incremental_20260714"
STAGE2_LOG="data/reports/roll_1m_incremental_20260714"
mkdir -p "$STAGE1_LOG" "$STAGE2_LOG"

echo "===== STAGE1 start roll 1d/1w remaining 81 $(date -u +%Y-%m-%dT%H:%M:%SZ) =====" | tee -a "$STAGE1_LOG/runner.log"
PRODUCTS_FILE=data/universe/roll_incremental_remaining_81.txt \
PERIODS=1d,1w \
LOG_DIR="$STAGE1_LOG" \
./scripts/rqdata_roll_incremental.sh 2>&1 | tee -a "$STAGE1_LOG/runner.log"
echo "===== STAGE1 done $(date -u +%Y-%m-%dT%H:%M:%SZ) =====" | tee -a "$STAGE1_LOG/runner.log"

echo "===== STAGE2 start roll 1m all 90 $(date -u +%Y-%m-%dT%H:%M:%SZ) =====" | tee -a "$STAGE2_LOG/runner.log"
PRODUCTS_FILE=data/universe/active_products.txt \
PERIODS=1m \
LOG_DIR="$STAGE2_LOG" \
./scripts/rqdata_roll_incremental.sh 2>&1 | tee -a "$STAGE2_LOG/runner.log"
echo "===== STAGE2 done $(date -u +%Y-%m-%dT%H:%M:%SZ) =====" | tee -a "$STAGE2_LOG/runner.log"

echo "MASTER ALL DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$STAGE1_LOG/runner.log" "$STAGE2_LOG/runner.log"
