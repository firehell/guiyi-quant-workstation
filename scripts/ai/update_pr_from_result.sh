#!/usr/bin/env bash
# Upsert the safe Result Sync block in the linked Draft PR body.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel)"

TASK_ID=""
TASK_FILE=""
BUNDLE=""
PR_NUMBER=""
DRY_RUN=false
CONFIRM_ISSUE_OPS=false
JSON_OUTPUT=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task) TASK_ID="${2:-}"; shift 2 ;;
    --task-file) TASK_FILE="${2:-}"; shift 2 ;;
    --bundle) BUNDLE="${2:-}"; shift 2 ;;
    --pr) PR_NUMBER="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --confirm-issue-ops) CONFIRM_ISSUE_OPS=true; shift ;;
    --json) JSON_OUTPUT=true; shift ;;
    -h|--help)
      echo "Usage: scripts/ai/update_pr_from_result.sh --task <TASK_ID> [--pr <N>] [--bundle <json>] [--dry-run] [--confirm-issue-ops] [--json]"
      exit 0
      ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$TASK_ID" ]] || { echo "--task is required" >&2; exit 2; }

args=(pr --task "$TASK_ID" --repo-root "$REPO_ROOT")
[[ -n "$TASK_FILE" ]] && args+=(--task-file "$TASK_FILE")
[[ -n "$BUNDLE" ]] && args+=(--bundle "$BUNDLE")
[[ -n "$PR_NUMBER" ]] && args+=(--pr "$PR_NUMBER")
[[ "$DRY_RUN" == true ]] && args+=(--dry-run)
[[ "$CONFIRM_ISSUE_OPS" == true ]] && args+=(--confirm-issue-ops)
[[ "$JSON_OUTPUT" == true ]] && args+=(--json)

if [[ "$DRY_RUN" != true && "$CONFIRM_ISSUE_OPS" != true ]]; then
  validate_args=("${args[@]}" --dry-run)
  PYTHONPATH="$SCRIPT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}" python3 "$SCRIPT_DIR/lib/github_result_sync.py" "${validate_args[@]}" >/dev/null
  echo "[PLAN] gh pr body upsert for ${TASK_ID}"
  echo "PR operation blocked: pass --confirm-issue-ops to execute external writes" >&2
  exit 6
fi

if [[ "$DRY_RUN" == true && "$JSON_OUTPUT" != true ]]; then
  echo "[PLAN] gh pr body upsert for ${TASK_ID}"
fi

export PYTHONPATH="$SCRIPT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}"
python3 "$SCRIPT_DIR/lib/github_result_sync.py" "${args[@]}"
