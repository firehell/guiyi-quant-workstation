#!/usr/bin/env bash
# Codex read-only plan: inspects files and proposes work; must not modify repository files.
# Optional: set TASK_ID to write output under .ai/results/<TASK_ID>/
set -euo pipefail

TASK_FILE="${1:-}"

if [ -z "$TASK_FILE" ]; then
  echo "Usage: scripts/ai/codex_plan.sh <task_file>" >&2
  echo "Optional: TASK_ID=<id> scripts/ai/codex_plan.sh <task_file>" >&2
  exit 1
fi

if [ ! -f "$TASK_FILE" ]; then
  echo "Task file not found: $TASK_FILE" >&2
  exit 1
fi

if ! command -v codex >/dev/null 2>&1; then
  echo "codex CLI not found in PATH" >&2
  exit 1
fi

GIT_ROOT="$(git rev-parse --show-toplevel)"
cd "$GIT_ROOT"

mkdir -p .ai/results .ai/logs

TS="$(date +%Y%m%d-%H%M%S)"
if [ -n "${TASK_ID:-}" ]; then
  RESULT_DIR=".ai/results/${TASK_ID}"
  mkdir -p "$RESULT_DIR"
  OUT_FILE="${RESULT_DIR}/codex_plan_${TS}.md"
  LOG_FILE=".ai/logs/codex_plan_${TASK_ID}_${TS}.log"
else
  OUT_FILE=".ai/results/codex_plan_${TS}.md"
  LOG_FILE=".ai/logs/codex_plan_${TS}.log"
fi

{
  echo "Running Codex read-only plan"
  echo "Repository: $GIT_ROOT"
  echo "Task: $TASK_FILE"
  echo "TASK_ID: ${TASK_ID:-<none>}"
  echo "Output: $OUT_FILE"
  echo "Log: $LOG_FILE"
  echo
  echo "Working tree before plan:"
  git status --short --branch
  echo
} | tee "$LOG_FILE"

codex exec --sandbox read-only --ephemeral --output-last-message "$OUT_FILE" - <"$TASK_FILE" 2>&1 | tee -a "$LOG_FILE"

{
  echo
  echo "Working tree after plan:"
  git status --short --branch
  echo
  echo "Plan output: $OUT_FILE"
  echo "Log output: $LOG_FILE"
} | tee -a "$LOG_FILE"
