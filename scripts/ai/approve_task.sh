#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
source "$SCRIPT_DIR/_approve_lib.sh"
source "$SCRIPT_DIR/_work_level_lib.sh"
TASK_ID=""
while [[ $# -gt 0 ]]; do
  case "$1" in --task) TASK_ID="${2:-}"; shift 2;; -h|--help) echo "Usage: scripts/ai/approve_task.sh --task <TASK_ID>"; exit 0;; *) echo "Unknown argument: $1" >&2; exit 2;; esac
done
[[ -n "$TASK_ID" ]] || { echo "--task is required" >&2; exit 2; }
cd "$REPO_ROOT"
TASK_FILE="$(resolve_task_file "$TASK_ID" || true)"
[[ -n "$TASK_FILE" ]] || { echo "TASK not found: $TASK_ID" >&2; exit 4; }
check_issue_gate "$TASK_FILE" || exit $?
check_worktree_gate "$TASK_FILE" || exit $?
ISSUE="$(extract_task_meta_field "$TASK_FILE" "GitHub Issue")"
PLAN_FILE=".ai/results/${TASK_ID}/plan_result.md"; [[ -f "$PLAN_FILE" ]] || { echo "Plan result missing: $PLAN_FILE" >&2; exit 4; }
check_branch "$TASK_FILE"
APPROVAL_FILE=".ai/approvals/${TASK_ID}.json"
generate_approval "$TASK_ID" "$TASK_FILE" "$PLAN_FILE" "$APPROVAL_FILE"
verify_approval "$APPROVAL_FILE" "$TASK_ID" "$TASK_FILE" "$PLAN_FILE"
echo "[OK] Approval generated: $APPROVAL_FILE"
echo "[OK] Plan SHA256: $(approval_sha256 "$PLAN_FILE")"
