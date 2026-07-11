#!/usr/bin/env bash
# Sync GitHub Issue status/* labels and TASK Status meta from status machine state.
set -euo pipefail

TASK_ID="${1:-}"
STATUS="${2:-}"
TASK_FILE=""
CLOSE_ISSUE=false

if [ $# -ge 3 ]; then
  shift 2
  while [ $# -gt 0 ]; do
    case "$1" in
      --close)
        CLOSE_ISSUE=true
        ;;
      *)
        if [ -z "$TASK_FILE" ] && [ -f "$1" ]; then
          TASK_FILE="$1"
        fi
        ;;
    esac
    shift
  done
fi

if [ -z "$TASK_ID" ] || [ -z "$STATUS" ]; then
  echo "Usage: scripts/ai/update_issue_status.sh <TASK_ID> <STATUS> [task_file] [--close]" >&2
  echo "STATUS: REQUIREMENT_READY | PLAN_READY | APPROVED_DEV | CODING | TESTING | DELIVERY_READY | CLOSED | FAILED | REPLAN" >&2
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI not found. Install: brew install gh && gh auth login" >&2
  exit 1
fi

map_status_label() {
  case "$1" in
    REQUIREMENT_READY) echo "status/requirement-ready" ;;
    PLAN_READY) echo "status/plan-ready" ;;
    APPROVED_DEV) echo "status/approved-dev" ;;
    CODING) echo "status/coding" ;;
    TESTING) echo "status/testing" ;;
    DELIVERY_READY) echo "status/delivery-ready" ;;
    CLOSED) echo "status/closed" ;;
    FAILED) echo "status/failed" ;;
    REPLAN) echo "status/replan" ;;
    *)
      echo ""
      ;;
  esac
}

NEW_LABEL="$(map_status_label "$STATUS")"
if [ -z "$NEW_LABEL" ]; then
  echo "Unknown STATUS: $STATUS" >&2
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
    "docs/tasks/${TASK_ID}.md"
    ".ai/tasks/${TASK_ID}.md"
    "docs/tasks/examples/${TASK_ID}.md"
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

update_meta_field() {
  local field="$1"
  local value="$2"
  local file="$3"
  local tmp
  tmp="$(mktemp)"
  awk -v field="$field" -v value="$value" '
    $0 ~ "^## 0\\. 元信息" { in_meta=1 }
    in_meta && $0 ~ "^\\| " field " \\|" {
      print "| " field " | " value " |"
      next
    }
    { print }
  ' "$file" >"$tmp"
  mv "$tmp" "$file"
}

TASK_FILE="$(resolve_task_file)"
if [ -z "$TASK_FILE" ]; then
  echo "Task file not found for TASK_ID: $TASK_ID" >&2
  exit 1
fi

ISSUE_NUMBER="$(extract_issue_number "$TASK_FILE")"
if [ -z "$ISSUE_NUMBER" ]; then
  echo "GitHub Issue not linked in task file: $TASK_FILE" >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "gh is not authenticated. Run: gh auth login" >&2
  exit 1
fi

TODAY="$(date +%Y-%m-%d)"
if grep -q '^## 0\. 元信息' "$TASK_FILE"; then
  update_meta_field "Status" "$STATUS" "$TASK_FILE"
  update_meta_field "Updated At" "$TODAY" "$TASK_FILE"
fi

if grep -q '^## 任务状态' "$TASK_FILE"; then
  tmp="$(mktemp)"
  awk -v status="$STATUS" '
    /^## 任务状态$/ { print; getline; print; print "`" status "`"; skip=1; next }
    skip && /^`.*`$/ { skip=0; next }
    { print }
  ' "$TASK_FILE" >"$tmp"
  mv "$tmp" "$TASK_FILE"
fi

STATUS_LABELS=(
  status/requirement-ready
  status/plan-ready
  status/approved-dev
  status/coding
  status/testing
  status/delivery-ready
  status/closed
  status/failed
  status/replan
)

for old in "${STATUS_LABELS[@]}"; do
  gh issue edit "$ISSUE_NUMBER" --remove-label "$old" 2>/dev/null || true
done

gh issue edit "$ISSUE_NUMBER" --add-label "$NEW_LABEL"

if [ "$CLOSE_ISSUE" = true ]; then
  gh issue close "$ISSUE_NUMBER"
  echo "Closed issue #$ISSUE_NUMBER"
elif [ "$STATUS" = "CLOSED" ]; then
  echo "STATUS=CLOSED set label only. Pass --close to close the issue."
fi

echo "Updated issue #$ISSUE_NUMBER label -> $NEW_LABEL"
echo "Updated TASK Status -> $STATUS in $TASK_FILE"
