#!/usr/bin/env bash
# Create a GitHub Issue from a local TASK file. Does not modify code or create PRs.
set -euo pipefail

TASK_FILE="${1:-}"
DRY_RUN=false

if [ -z "$TASK_FILE" ]; then
  echo "Usage: scripts/ai/create_issue_from_task.sh <task_file> [--dry-run]" >&2
  exit 1
fi

if [ "${2:-}" = "--dry-run" ]; then
  DRY_RUN=true
fi

if [ ! -f "$TASK_FILE" ]; then
  echo "Task file not found: $TASK_FILE" >&2
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI not found. Install: brew install gh && gh auth login" >&2
  exit 1
fi

GIT_ROOT="$(git rev-parse --show-toplevel)"
cd "$GIT_ROOT"

extract_meta_value() {
  local field="$1"
  awk -v f="$field" '
    $0 ~ "^## 0\\. 元信息" { in_meta=1; next }
    in_meta && /^## / { exit }
    in_meta && $0 ~ "^\\| " f " \\|" {
      gsub(/^\\| [^|]+ \\| /, "", $0)
      gsub(/ \\|$/, "", $0)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", $0)
      print $0
      exit
    }
  ' "$TASK_FILE"
}

extract_task_id() {
  local from_meta
  from_meta="$(extract_meta_value "Task ID")"
  if [ -n "$from_meta" ] && [[ "$from_meta" =~ ^TASK- ]]; then
    echo "$from_meta"
    return
  fi
  local from_heading
  from_heading="$(awk '/^# TASK-/ { sub(/^# /, ""); print; exit }' "$TASK_FILE")"
  if [ -n "$from_heading" ]; then
    echo "$from_heading"
    return
  fi
  local from_section
  from_section="$(awk '/^## 任务编号$/{getline; getline; gsub(/^`|`$/,""); print; exit}' "$TASK_FILE")"
  echo "$from_section"
}

extract_short_title() {
  local heading subtitle
  subtitle="$(awk '/^> / { sub(/^> /, ""); print; exit }' "$TASK_FILE")"
  if [ -n "$subtitle" ]; then
    subtitle="${subtitle%%。*}"
    subtitle="${subtitle##*：}"
    subtitle="${subtitle##*: }"
    if [ -n "$subtitle" ]; then
      echo "$subtitle"
      return
    fi
  fi
  heading="$(awk '/^# TASK-/ {
    line=$0
    sub(/^# TASK-[0-9]{8}-[0-9]{3}-?/, "", line)
    sub(/^TASK-[0-9]{8}-[0-9]{3}-?/, "", line)
    gsub(/^[-–—[:space:]]+/, "", line)
    print line
    exit
  }' "$TASK_FILE")"
  if [ -n "$heading" ]; then
    echo "$heading"
    return
  fi
  echo "任务"
}

TASK_ID="$(extract_task_id)"
if [ -z "$TASK_ID" ]; then
  echo "Could not extract Task ID from: $TASK_FILE" >&2
  exit 1
fi

EXISTING_ISSUE="$(extract_meta_value "GitHub Issue")"
if [ -n "$EXISTING_ISSUE" ] && [[ "$EXISTING_ISSUE" =~ ^#[0-9]+$ ]]; then
  echo "Task already linked to GitHub Issue: $EXISTING_ISSUE" >&2
  echo "Refuse to create duplicate Issue for TASK: $TASK_ID" >&2
  exit 1
fi

SHORT_TITLE="$(extract_short_title)"
ISSUE_TITLE="${TASK_ID}：${SHORT_TITLE}"

RESULT_DIR=".ai/results/${TASK_ID}"
mkdir -p "$RESULT_DIR" .ai/logs
TS="$(date +%Y%m%d-%H%M%S)"
LOG_FILE=".ai/logs/create_issue_${TASK_ID}_${TS}.log"

{
  echo "Create GitHub Issue from TASK"
  echo "Repository: $GIT_ROOT"
  echo "Task file: $TASK_FILE"
  echo "TASK_ID: $TASK_ID"
  echo "Issue title: $ISSUE_TITLE"
  echo "Dry run: $DRY_RUN"
  echo
} | tee "$LOG_FILE"

if [ "$DRY_RUN" = true ]; then
  echo "Would run:"
  echo "  gh issue create --title \"$ISSUE_TITLE\" --body-file \"$TASK_FILE\" --label type/task --label status/requirement-ready"
  echo "Dry run complete. No Issue created."
  exit 0
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "gh is not authenticated. Run: gh auth login" >&2
  exit 1
fi

ISSUE_URL="$(gh issue create \
  --title "$ISSUE_TITLE" \
  --body-file "$TASK_FILE" \
  --label "type/task" \
  --label "status/requirement-ready")"

ISSUE_NUMBER="$(echo "$ISSUE_URL" | grep -oE '[0-9]+$' || true)"
if [ -z "$ISSUE_NUMBER" ]; then
  echo "Failed to parse issue number from: $ISSUE_URL" >&2
  exit 1
fi

{
  echo "Issue created: #$ISSUE_NUMBER"
  echo "Issue URL: $ISSUE_URL"
  echo
  echo "Next step:"
  echo "  scripts/ai/link_task_issue.sh $TASK_ID $ISSUE_NUMBER $TASK_FILE"
} | tee -a "$LOG_FILE"

echo "ISSUE_NUMBER=$ISSUE_NUMBER"
echo "ISSUE_URL=$ISSUE_URL"
