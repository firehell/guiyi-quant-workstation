#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
source "$SCRIPT_DIR/_work_level_lib.sh"

TASK_ID=""
TARGET="L2"

usage() {
  echo "Usage: scripts/ai/upgrade_task_level.sh --task <TASK_ID> --to L2"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task) TASK_ID="${2:-}"; shift 2 ;;
    --to) TARGET="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$TASK_ID" ]] || { usage >&2; exit 2; }
TARGET="$(normalize_work_level "$TARGET")"
[[ "$TARGET" == "L2" ]] || { echo "Only upgrade --to L2 is supported" >&2; exit 2; }

cd "$REPO_ROOT"
TASK_FILE="$(resolve_task_file "$TASK_ID" || true)"
[[ -n "$TASK_FILE" ]] || { echo "TASK not found: $TASK_ID" >&2; exit 4; }

current="$(extract_work_level "$TASK_FILE")"
if [[ "$current" == "L2" ]]; then
  echo "[OK] Already L2: $TASK_ID"
  exit 0
fi

issue="$(extract_task_meta_field "$TASK_FILE" "GitHub Issue")"
[[ "$issue" =~ ^#[0-9]+$ ]] || {
  echo "Cannot upgrade to L2: GitHub Issue #N required" >&2
  echo "Run: scripts/ai/create_issue_from_task.sh $TASK_FILE" >&2
  echo "     scripts/ai/link_task_issue.sh $TASK_ID <N>" >&2
  exit 5
}

if ! extract_worktree_path "$TASK_FILE" >/dev/null 2>&1; then
  echo "Cannot upgrade to L2: Worktree not set; run init_task_worktree.sh first" >&2
  exit 7
fi

for section in "## 15." "## 16." "## 17."; do
  if ! grep -q "^${section}" "$TASK_FILE"; then
    echo "[WARN] Missing section $section — L2 TASK should include Plan/Dev/CodeBuddy prompts"
  fi
done

set_task_meta_field "$TASK_FILE" "Work Level" "L2"
echo "[OK] Upgraded $TASK_ID from $current to L2"
echo "[OK] Issue: $issue"
