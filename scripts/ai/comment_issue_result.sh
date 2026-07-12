#!/usr/bin/env bash
# Append plan/test/delivery results as comments on the linked GitHub Issue.
set -euo pipefail

TASK_ID="${1:-}"
MODE="${2:-}"
TASK_FILE=""
DRY_RUN=false
CONFIRM_ISSUE_OPS=false

shift 2 2>/dev/null || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true ;;
    --confirm-issue-ops) CONFIRM_ISSUE_OPS=true ;;
    *)
      if [[ -z "$TASK_FILE" && -f "$1" ]]; then
        TASK_FILE="$1"
      else
        echo "Unknown argument: $1" >&2
        exit 2
      fi
      ;;
  esac
  shift
done

if [[ -z "$TASK_ID" || -z "$MODE" ]]; then
  echo "Usage: scripts/ai/comment_issue_result.sh <TASK_ID> <plan|test|delivery> [task_file] [--dry-run] [--confirm-issue-ops]" >&2
  exit 1
fi

case "$MODE" in
  plan|test|delivery) ;;
  *)
    echo "MODE must be one of: plan, test, delivery" >&2
    exit 1
    ;;
esac

GIT_ROOT="$(git rev-parse --show-toplevel)"
cd "$GIT_ROOT"

resolve_task_file() {
  if [[ -n "$TASK_FILE" && -f "$TASK_FILE" ]]; then
    echo "$TASK_FILE"
    return
  fi
  local candidates=(
    "docs/tasks/${TASK_ID}.md"
    ".ai/tasks/${TASK_ID}.md"
    "docs/tasks/examples/${TASK_ID}.md"
  )
  local c
  for c in "${candidates[@]}"; do
    if [[ -f "$c" ]]; then
      echo "$c"
      return
    fi
  done
  echo ""
}

extract_issue_number() {
  local file="$1"
  awk '
    $0 ~ "^## 0\\. 元信息" { in_meta=1; next }
    in_meta && /^## / { exit }
    in_meta && $0 ~ "^\\| GitHub Issue \\|" {
      if (match($0, /#[0-9]+/)) {
        print substr($0, RSTART + 1, RLENGTH - 1)
        exit
      }
    }
  ' "$file"
}

TASK_FILE="$(resolve_task_file)"
if [[ -z "$TASK_FILE" ]]; then
  echo "Task file not found for TASK_ID: $TASK_ID" >&2
  exit 1
fi

ISSUE_NUMBER="$(extract_issue_number "$TASK_FILE")"
if [[ -z "$ISSUE_NUMBER" ]]; then
  echo "GitHub Issue not linked in task file: $TASK_FILE" >&2
  echo "Run: scripts/ai/link_task_issue.sh $TASK_ID <ISSUE_NUMBER> $TASK_FILE" >&2
  exit 1
fi

RESULT_DIR=".ai/results/${TASK_ID}"
mkdir -p "$RESULT_DIR" .ai/logs

find_result_file() {
  local mode="$1"
  local primary fallback

  case "$mode" in
    plan)
      primary="${RESULT_DIR}/plan_result.md"
      if [[ -f "$primary" ]]; then echo "$primary"; return; fi
      fallback="$(ls -t "${RESULT_DIR}"/codex_plan_*.md 2>/dev/null | head -1 || true)"
      ;;
    test)
      primary="${RESULT_DIR}/test_result.md"
      if [[ -f "$primary" ]]; then echo "$primary"; return; fi
      if [[ -f "${RESULT_DIR}/execution_summary.md" ]]; then
        echo "${RESULT_DIR}/execution_summary.md"
        return
      fi
      fallback="$(ls -t .ai/logs/tests_${TASK_ID}_*.log 2>/dev/null | head -1 || true)"
      if [[ -z "$fallback" ]]; then
        fallback="$(ls -t .ai/logs/tests_*.log 2>/dev/null | head -1 || true)"
      fi
      ;;
    delivery)
      primary="${RESULT_DIR}/delivery_report.md"
      if [[ -f "$primary" ]]; then echo "$primary"; return; fi
      fallback="${RESULT_DIR}/delivery_report_draft.md"
      ;;
  esac

  if [[ -n "${fallback:-}" && -f "$fallback" ]]; then
    echo "$fallback"
    return
  fi
  echo ""
}

RESULT_FILE="$(find_result_file "$MODE")"
if [[ -z "$RESULT_FILE" || ! -f "$RESULT_FILE" ]]; then
  echo "Result file not found for mode=$MODE under $RESULT_DIR" >&2
  exit 1
fi

echo "[PLAN] gh issue comment #$ISSUE_NUMBER --body-file <${MODE} from ${RESULT_FILE}>"

if [[ "$DRY_RUN" == true ]]; then
  echo "[DRY-RUN] no Issue comment posted"
  exit 0
fi

if [[ "$CONFIRM_ISSUE_OPS" != true ]]; then
  echo "Issue operation blocked: pass --confirm-issue-ops to execute external writes" >&2
  exit 6
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI not found. Install: brew install gh && gh auth login" >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "gh is not authenticated. Run: gh auth login" >&2
  exit 1
fi

TS="$(date '+%Y-%m-%d %H:%M:%S')"
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
