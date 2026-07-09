#!/usr/bin/env bash
# Link a GitHub Issue number back into a TASK file meta section.
set -euo pipefail

TASK_ID="${1:-}"
ISSUE_NUMBER="${2:-}"
TASK_FILE="${3:-}"

if [ -z "$TASK_ID" ] || [ -z "$ISSUE_NUMBER" ]; then
  echo "Usage: scripts/ai/link_task_issue.sh <TASK_ID> <ISSUE_NUMBER> [task_file]" >&2
  exit 1
fi

if ! [[ "$ISSUE_NUMBER" =~ ^[0-9]+$ ]]; then
  echo "ISSUE_NUMBER must be numeric, got: $ISSUE_NUMBER" >&2
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

TASK_FILE="$(resolve_task_file)"
if [ -z "$TASK_FILE" ]; then
  echo "Task file not found for TASK_ID: $TASK_ID" >&2
  echo "Tried: .ai/tasks/, docs/tasks/examples/, docs/tasks/" >&2
  exit 1
fi

TODAY="$(date +%Y-%m-%d)"
ISSUE_REF="#${ISSUE_NUMBER}"
TMP_FILE="$(mktemp)"

update_meta_field() {
  local field="$1"
  local value="$2"
  local file="$3"
  local out="$4"
  awk -v field="$field" -v value="$value" '
    $0 ~ "^## 0\\. 元信息" { in_meta=1 }
    in_meta && $0 ~ "^\\| " field " \\|" {
      print "| " field " | " value " |"
      next
    }
    { print }
  ' "$file" >"$out"
}

if ! grep -q '^## 0\. 元信息' "$TASK_FILE"; then
  echo "Task file missing '## 0. 元信息' section: $TASK_FILE" >&2
  echo "Update task file to match docs/tasks/TASK_TEMPLATE.md" >&2
  exit 1
fi

update_meta_field "GitHub Issue" "$ISSUE_REF" "$TASK_FILE" "$TMP_FILE"
mv "$TMP_FILE" "$TASK_FILE"
update_meta_field "Updated At" "$TODAY" "$TASK_FILE" "$TMP_FILE"
mv "$TMP_FILE" "$TASK_FILE"

if grep -q '^| Task ID |' "$TASK_FILE"; then
  :
else
  update_meta_field "Task ID" "$TASK_ID" "$TASK_FILE" "$TMP_FILE"
  mv "$TMP_FILE" "$TASK_FILE"
fi

RESULT_DIR=".ai/results/${TASK_ID}"
mkdir -p "$RESULT_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
LINK_FILE="${RESULT_DIR}/issue_link.md"

REPO_URL="$(gh repo view --json url -q .url 2>/dev/null || echo "https://github.com/firehell/guiyi-quant-workstation")"
ISSUE_URL="${REPO_URL}/issues/${ISSUE_NUMBER}"

{
  echo "# Issue Link"
  echo
  echo "- **TASK_ID**: ${TASK_ID}"
  echo "- **GitHub Issue**: ${ISSUE_REF}"
  echo "- **Issue URL**: ${ISSUE_URL}"
  echo "- **Linked at**: ${TS}"
  echo "- **Task file**: ${TASK_FILE}"
} >"$LINK_FILE"

echo "Linked $TASK_ID -> $ISSUE_REF"
echo "Task file updated: $TASK_FILE"
echo "Issue link record: $LINK_FILE"
echo "ISSUE_URL=$ISSUE_URL"
