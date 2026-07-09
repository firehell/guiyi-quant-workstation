#!/usr/bin/env bash
# Append plan/test/delivery results as comments on the linked GitHub Issue.
set -euo pipefail

TASK_ID="${1:-}"
MODE="${2:-}"
TASK_FILE="${3:-}"

if [ -z "$TASK_ID" ] || [ -z "$MODE" ]; then
  echo "Usage: scripts/ai/comment_issue_result.sh <TASK_ID> <plan|test|delivery> [task_file]" >&2
  exit 1
fi

case "$MODE" in
  plan|test|delivery) ;;
  *)
    echo "MODE must be one of: plan, test, delivery" >&2
    exit 1
    ;;
esac

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI not found. Install: brew install gh && gh auth login" >&2
  exit 1
fi

GIT_ROOT="$(git rev-parse --show-toplevel)"
cd "$GIT_ROOT"

resolve_task_file() {
  if [ -n "$TASK_FILE" ] && [ -f "$TASK_FILE" ]; then
    echo "$TASK_FILE"
    return
  fi
  local candidates=(
    ".ai/tasks/${TASK_ID}.md"
    "docs/tasks/examples/${TASK_ID}.md"
    "docs/tasks/${TASK_ID}.md"
  )
  local c
  for c in "${candidates[@]}"; do
    if [ -f "$c" ]; then
      echo "$c"
      return
    fi
  done
  echo ""
}

extract_issue_number() {
  local file="$1"
  local ref
  ref="$(awk '
    $0 ~ "^## 0\\. 元信息" { in_meta=1; next }
    in_meta && /^## / { exit }
    in_meta && $0 ~ "^\\| GitHub Issue \\|" {
      if (match($0, /#[0-9]+/)) {
        print substr($0, RSTART + 1, RLENGTH - 1)
        exit
      }
    }
  ' "$file")"
  echo "$ref"
}

TASK_FILE="$(resolve_task_file)"
if [ -z "$TASK_FILE" ]; then
  echo "Task file not found for TASK_ID: $TASK_ID" >&2
  exit 1
fi

ISSUE_NUMBER="$(extract_issue_number "$TASK_FILE")"
if [ -z "$ISSUE_NUMBER" ]; then
  echo "GitHub Issue not linked in task file: $TASK_FILE" >&2
  echo "Run: scripts/ai/link_task_issue.sh $TASK_ID <ISSUE_NUMBER> $TASK_FILE" >&2
  exit 1
fi

RESULT_DIR=".ai/results/${TASK_ID}"
mkdir -p "$RESULT_DIR" .ai/logs

find_result_file() {
  local mode="$1"
  local primary fallback path

  case "$mode" in
    plan)
      primary="${RESULT_DIR}/plan_result.md"
      if [ -f "$primary" ]; then echo "$primary"; return; fi
      fallback="$(ls -t "${RESULT_DIR}"/codex_plan_*.md 2>/dev/null | head -1 || true)"
      ;;
    test)
      primary="${RESULT_DIR}/test_result.md"
      if [ -f "$primary" ]; then echo "$primary"; return; fi
      if [ -f "${RESULT_DIR}/execution_summary.md" ]; then
        echo "${RESULT_DIR}/execution_summary.md"
        return
      fi
      fallback="$(ls -t .ai/logs/tests_${TASK_ID}_*.log 2>/dev/null | head -1 || true)"
      if [ -z "$fallback" ]; then
        fallback="$(ls -t .ai/logs/tests_*.log 2>/dev/null | head -1 || true)"
      fi
      ;;
    delivery)
      primary="${RESULT_DIR}/delivery_report.md"
      if [ -f "$primary" ]; then echo "$primary"; return; fi
      fallback="${RESULT_DIR}/delivery_report_draft.md"
      ;;
  esac

  if [ -n "${fallback:-}" ] && [ -f "$fallback" ]; then
    echo "$fallback"
    return
  fi
  echo ""
}

RESULT_FILE="$(find_result_file "$MODE")"
if [ -z "$RESULT_FILE" ] || [ ! -f "$RESULT_FILE" ]; then
  echo "Result file not found for mode=$MODE under $RESULT_DIR" >&2
  case "$MODE" in
    plan) echo "Expected: plan_result.md or codex_plan_*.md" >&2 ;;
    test) echo "Expected: test_result.md, execution_summary.md, or tests_*.log" >&2 ;;
    delivery) echo "Expected: delivery_report.md or delivery_report_draft.md" >&2 ;;
  esac
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "gh is not authenticated. Run: gh auth login" >&2
  exit 1
fi

TS="$(date +%Y-%m-%d %H:%M:%S)"
TMP_COMMENT="$(mktemp)"
MODE_TITLE="$(echo "$MODE" | awk '{print toupper(substr($0,1,1)) tolower(substr($0,2))}')"

{
  echo "## ${MODE_TITLE} Result — ${TASK_ID}"
  echo
  echo "- **Posted at**: ${TS}"
  echo "- **Source file**: \`${RESULT_FILE}\`"
  echo
  echo "---"
  echo
  cat "$RESULT_FILE"
} >"$TMP_COMMENT"

LOG_FILE=".ai/logs/comment_issue_${TASK_ID}_${MODE}_$(date +%Y%m%d-%H%M%S).log"
gh issue comment "$ISSUE_NUMBER" --body-file "$TMP_COMMENT" | tee "$LOG_FILE"
rm -f "$TMP_COMMENT"

echo "Commented $MODE result on issue #$ISSUE_NUMBER"
echo "Source: $RESULT_FILE"
echo "Log: $LOG_FILE"
