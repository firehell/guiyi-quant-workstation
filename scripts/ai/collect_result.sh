#!/usr/bin/env bash
# Collect git status, diff, and test log summary into execution_summary.md.
# Does not auto-fix, commit, or push.
set -euo pipefail

TASK_ID="${1:-}"
TASK_FILE="${2:-}"

if [ -z "$TASK_ID" ]; then
  echo "Usage: scripts/ai/collect_result.sh <TASK_ID> [task_file]" >&2
  exit 1
fi

GIT_ROOT="$(git rev-parse --show-toplevel)"
cd "$GIT_ROOT"

RESULT_DIR=".ai/results/${TASK_ID}"
mkdir -p "$RESULT_DIR" .ai/logs

TS="$(date +%Y%m%d-%H%M%S)"
SUMMARY_FILE="${RESULT_DIR}/execution_summary.md"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
STATUS_SHORT="$(git status --short --branch)"
DIFF_STAT="$(git diff --stat 2>/dev/null || true)"
CHANGED_FILES="$(git diff --name-only 2>/dev/null || true)"
STAGED_FILES="$(git diff --cached --name-only 2>/dev/null || true)"
UNTRACKED_FILES="$(git ls-files --others --exclude-standard 2>/dev/null || true)"
LAST_COMMIT="$(git log -1 --oneline 2>/dev/null || echo 'no commits')"

LATEST_TEST_LOG=""
if [ -d .ai/logs ]; then
  if [ -n "${TASK_ID}" ]; then
    LATEST_TEST_LOG="$(ls -t .ai/logs/tests_${TASK_ID}_*.log 2>/dev/null | head -1 || true)"
  fi
  if [ -z "$LATEST_TEST_LOG" ]; then
    LATEST_TEST_LOG="$(ls -t .ai/logs/tests_*.log 2>/dev/null | head -1 || true)"
  fi
fi

TEST_SUMMARY="(no test log found)"
if [ -n "$LATEST_TEST_LOG" ] && [ -f "$LATEST_TEST_LOG" ]; then
  TEST_SUMMARY="$(tail -30 "$LATEST_TEST_LOG")"
fi

{
  echo "# Execution Summary"
  echo
  echo "- **TASK_ID**: ${TASK_ID}"
  echo "- **Collected at**: ${TS}"
  echo "- **Task file**: ${TASK_FILE:-<not provided>}"
  echo "- **Branch**: ${BRANCH}"
  echo "- **Last commit**: ${LAST_COMMIT}"
  echo
  echo "## Git Status"
  echo
  echo '```'
  echo "$STATUS_SHORT"
  echo '```'
  echo
  echo "## Diff Stat"
  echo
  echo '```'
  if [ -n "$DIFF_STAT" ]; then
    echo "$DIFF_STAT"
  else
    echo "(no unstaged diff)"
  fi
  echo '```'
  echo
  echo "## Changed Files (unstaged)"
  echo
  if [ -n "$CHANGED_FILES" ]; then
    echo "$CHANGED_FILES" | sed 's/^/- /'
  else
    echo "- (none)"
  fi
  echo
  echo "## Staged Files"
  echo
  if [ -n "$STAGED_FILES" ]; then
    echo "$STAGED_FILES" | sed 's/^/- /'
  else
    echo "- (none)"
  fi
  echo
  echo "## Untracked Files"
  echo
  if [ -n "$UNTRACKED_FILES" ]; then
    echo "$UNTRACKED_FILES" | sed 's/^/- /'
  else
    echo "- (none)"
  fi
  echo
  echo "## Latest Test Log"
  echo
  if [ -n "$LATEST_TEST_LOG" ]; then
    echo "- Path: \`${LATEST_TEST_LOG}\`"
  fi
  echo
  echo '```'
  echo "$TEST_SUMMARY"
  echo '```'
} >"$SUMMARY_FILE"

echo "Execution summary: $SUMMARY_FILE"
cat "$SUMMARY_FILE"
