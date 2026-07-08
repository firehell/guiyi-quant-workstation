#!/usr/bin/env bash
set -euo pipefail

TASK_FILE="${1:-}"
BRANCH_NAME="${2:-}"

if [ -z "$TASK_FILE" ] || [ -z "$BRANCH_NAME" ]; then
  echo "Usage: scripts/ai/codex_dev.sh <task_file> <branch_name>" >&2
  exit 1
fi

if [ ! -f "$TASK_FILE" ]; then
  echo "Task file not found: $TASK_FILE" >&2
  exit 1
fi

case "$BRANCH_NAME" in
  codex/*|feature/*)
    ;;
  *)
    echo "Branch must start with codex/ or feature/: $BRANCH_NAME" >&2
    exit 1
    ;;
esac

if ! command -v codex >/dev/null 2>&1; then
  echo "codex CLI not found in PATH" >&2
  exit 1
fi

GIT_ROOT="$(git rev-parse --show-toplevel)"
cd "$GIT_ROOT"

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$CURRENT_BRANCH" != "main" ]; then
  echo "Current branch is $CURRENT_BRANCH, not main." >&2
  echo "Start development runs from main so the created branch has a clean base." >&2
  exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
  echo "Working tree is not clean. Commit, stash, or review changes before running dev." >&2
  git status --short
  exit 1
fi

mkdir -p .ai/results .ai/logs

git fetch origin main
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
  echo "Local main is not aligned with origin/main after fetch." >&2
  echo "Review with: git log --oneline --decorate --left-right HEAD...origin/main" >&2
  exit 1
fi

git switch -c "$BRANCH_NAME"

TS="$(date +%Y%m%d-%H%M%S)"
OUT_FILE=".ai/results/codex_dev_${TS}.md"
LOG_FILE=".ai/logs/codex_dev_${TS}.log"

{
  echo "Running Codex workspace-write development"
  echo "Repository: $GIT_ROOT"
  echo "Task: $TASK_FILE"
  echo "Branch: $BRANCH_NAME"
  echo "Output: $OUT_FILE"
  echo "Log: $LOG_FILE"
  echo
  git status --short --branch
  echo
} | tee "$LOG_FILE"

codex exec --sandbox workspace-write --output-last-message "$OUT_FILE" - <"$TASK_FILE" 2>&1 | tee -a "$LOG_FILE"

{
  echo
  echo "Codex dev finished"
  echo "Branch: $BRANCH_NAME"
  echo "Output: $OUT_FILE"
  echo "Log: $LOG_FILE"
  echo
  echo "Git status:"
  git status --short
  echo
  echo "Diff stat:"
  git diff --stat
} | tee -a "$LOG_FILE"
