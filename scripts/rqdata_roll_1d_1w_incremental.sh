#!/usr/bin/env bash
# Backward-compatible wrapper: roll 1d/1w incremental.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PERIODS="${PERIODS:-1d,1w}"
export LOG_DIR="${LOG_DIR:-data/reports/roll_1d_1w_incremental_20260713}"
exec "$ROOT/scripts/rqdata_roll_incremental.sh"
