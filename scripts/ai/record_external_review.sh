#!/usr/bin/env bash
# Record GPT external GitHub PR review status bound to the current PR head SHA.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel)"

TASK_ID=""
TASK_FILE=""
PR_NUMBER=""
REVIEWER_TYPE="gpt"
REVIEW_AUTHOR=""
DRY_RUN=false
JSON_OUTPUT=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task) TASK_ID="${2:-}"; shift 2 ;;
    --task-file) TASK_FILE="${2:-}"; shift 2 ;;
    --pr) PR_NUMBER="${2:-}"; shift 2 ;;
    --reviewer-type) REVIEWER_TYPE="${2:-}"; shift 2 ;;
    --review-author) REVIEW_AUTHOR="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --json) JSON_OUTPUT=true; shift ;;
    -h|--help)
      cat <<'EOF'
Usage: scripts/ai/record_external_review.sh --task <TASK_ID> [options]

Options:
  --task-file <path>       Explicit TASK file.
  --pr <number>            Override TASK GitHub PR.
  --reviewer-type <type>   Reviewer type label for the local record (default: gpt).
  --review-author <login>  Optional GitHub login filter.
  --dry-run                Read GitHub and evaluate without writing local record.
  --json                   Print machine-readable result.

This command reads real GitHub PR reviews through gh. It does not submit,
approve, dismiss, merge, mark ready, or close anything.
EOF
      exit 0
      ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$TASK_ID" ]] || { echo "--task is required" >&2; exit 2; }

args=(--task "$TASK_ID" --repo-root "$REPO_ROOT" --reviewer-type "$REVIEWER_TYPE")
[[ -n "$TASK_FILE" ]] && args+=(--task-file "$TASK_FILE")
[[ -n "$PR_NUMBER" ]] && args+=(--pr "$PR_NUMBER")
[[ -n "$REVIEW_AUTHOR" ]] && args+=(--review-author "$REVIEW_AUTHOR")
[[ "$DRY_RUN" == true ]] && args+=(--dry-run)
[[ "$JSON_OUTPUT" == true ]] && args+=(--json)

export PYTHONPATH="$SCRIPT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}"
python3 "$SCRIPT_DIR/lib/external_review_gate.py" "${args[@]}"
