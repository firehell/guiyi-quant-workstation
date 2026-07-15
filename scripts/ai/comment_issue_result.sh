#!/usr/bin/env bash
# Upsert a safe, redacted result summary comment on the linked GitHub Issue.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel)"

TASK_ID="${1:-}"
MODE="${2:-}"
TASK_FILE=""
BUNDLE=""
DRY_RUN=false
CONFIRM_ISSUE_OPS=false
JSON_OUTPUT=false

shift 2 2>/dev/null || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --bundle) BUNDLE="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --confirm-issue-ops) CONFIRM_ISSUE_OPS=true; shift ;;
    --json) JSON_OUTPUT=true; shift ;;
    *)
      if [[ -z "$TASK_FILE" && -f "$1" ]]; then
        TASK_FILE="$1"
        shift
      else
        echo "Unknown argument: $1" >&2
        exit 2
      fi
      ;;
  esac
done

if [[ -z "$TASK_ID" || -z "$MODE" ]]; then
  echo "Usage: scripts/ai/comment_issue_result.sh <TASK_ID> <plan|test|review|result|delivery> [task_file] [--bundle <json>] [--dry-run] [--confirm-issue-ops] [--json]" >&2
  exit 1
fi

case "$MODE" in
  plan|test|review|result|delivery) ;;
  *) echo "MODE must be one of: plan, test, review, result, delivery" >&2; exit 1 ;;
esac

args=(issue --task "$TASK_ID" --mode "$MODE" --repo-root "$REPO_ROOT")
[[ -n "$TASK_FILE" ]] && args+=(--task-file "$TASK_FILE")
[[ -n "$BUNDLE" ]] && args+=(--bundle "$BUNDLE")
[[ "$DRY_RUN" == true ]] && args+=(--dry-run)
[[ "$CONFIRM_ISSUE_OPS" == true ]] && args+=(--confirm-issue-ops)
[[ "$JSON_OUTPUT" == true ]] && args+=(--json)

if [[ "$DRY_RUN" != true && "$CONFIRM_ISSUE_OPS" != true ]]; then
  validate_args=("${args[@]}" --dry-run)
  PYTHONPATH="$SCRIPT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}" python3 "$SCRIPT_DIR/lib/github_result_sync.py" "${validate_args[@]}" >/dev/null
  echo "[PLAN] gh issue comment upsert for ${TASK_ID} mode=${MODE}"
  echo "Issue operation blocked: pass --confirm-issue-ops to execute external writes" >&2
  exit 6
fi

if [[ "$DRY_RUN" == true && "$JSON_OUTPUT" != true ]]; then
  echo "[PLAN] gh issue comment upsert for ${TASK_ID} mode=${MODE}"
fi

export PYTHONPATH="$SCRIPT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}"
python3 "$SCRIPT_DIR/lib/github_result_sync.py" "${args[@]}"
