#!/usr/bin/env bash
set -euo pipefail

GIT_ROOT="$(git rev-parse --show-toplevel)"
cd "$GIT_ROOT"

mkdir -p .ai/results .ai/logs

TS="$(date +%Y%m%d-%H%M%S)"
LOG_FILE=".ai/logs/tests_${TS}.log"

run_cmd() {
  echo
  echo "+ $*"
  "$@"
}

{
  echo "Running AI workflow checks"
  echo "Repository: $GIT_ROOT"
  echo "Log: $LOG_FILE"
  echo
  git status --short --branch
} | tee "$LOG_FILE"

{
  run_cmd bash -n scripts/ai/codex_plan.sh scripts/ai/codex_dev.sh scripts/ai/run_tests.sh
  run_cmd git diff --check

  if [ "${1:-}" = "--api" ]; then
    run_cmd uv run --project services/quant-api pytest -q "${@:2}"
  elif [ "${1:-}" = "--web" ]; then
    run_cmd npm --prefix apps/quant-web run build
  elif [ "$#" -gt 0 ]; then
    run_cmd "$@"
  else
    echo
    echo "Base checks passed. Pass --api, --web, or a command for broader checks."
  fi
} 2>&1 | tee -a "$LOG_FILE"

echo
echo "Test log: $LOG_FILE"
