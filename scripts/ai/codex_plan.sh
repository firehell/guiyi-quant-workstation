#!/usr/bin/env bash
set -euo pipefail

TASK_FILE="${1:-}"

if [ -z "$TASK_FILE" ]; then
  echo "Usage: scripts/ai/codex_plan.sh <task_file>" >&2
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
OUT_FILE=".ai/results/codex_plan_${TS}.md"
LOG_FILE=".ai/logs/codex_plan_${TS}.log"

{
  echo "Running Codex read-only plan"
  echo "Repository: $GIT_ROOT"
  echo "Task: $TASK_FILE"
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
