#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"

usage() {
  cat <<'EOF'
Usage: scripts/ai/workbuddy_task.sh <command> [options]

Commands:
  analyze
  bootstrap
  plan
  approve
  dev
  test
  review
  result
  delivery
  status
  cancel
  sync-pr
  record-external-review

Options:
  --issue <#N|N>                 GitHub Issue number.
  --task <TASK_ID>               TASK_ID for local controlled scripts.
  --pr <N>                       GitHub PR number for PR-related commands.
  --confirm-user-approval        Required for approve.
  --confirm-github-write         Required for sync-pr.
  --dry-run                      Pass dry-run where supported.
  --json                         Accepted for consistency; output is JSON where supported.

This facade only calls existing controlled workstation scripts. It does not
push, merge, deploy, close Issues, accept arbitrary shell, or maintain a second
task state.
EOF
}

json_emit() {
  python3 - "$@" <<'PY'
import json
import sys

payload = {}
for item in sys.argv[1:]:
    key, _, value = item.partition("=")
    if value == "true":
        payload[key] = True
    elif value == "false":
        payload[key] = False
    else:
        payload[key] = value
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
PY
}

fail_json() {
  local rc="$1"
  local code="$2"
  local message="$3"
  json_emit ok=false command="$COMMAND" code="$code" message="$message" >&2
  exit "$rc"
}

normalize_issue() {
  local raw="$1"
  raw="${raw#\#}"
  [[ "$raw" =~ ^[0-9]+$ ]] || fail_json 2 "invalid_issue" "Issue must be a number or #N."
  ISSUE_NUMBER="$raw"
  ISSUE_REF="#$raw"
}

normalize_pr() {
  local raw="$1"
  raw="${raw#\#}"
  [[ "$raw" =~ ^[0-9]+$ ]] || fail_json 2 "invalid_pr" "PR must be a number or #N."
  PR_NUMBER="$raw"
}

normalize_task() {
  local raw="$1"
  [[ "$raw" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || fail_json 2 "invalid_task" "TASK_ID contains unsupported characters."
  TASK_ID="$raw"
}

require_issue() {
  [[ -n "$ISSUE_REF" ]] || fail_json 2 "issue_required" "--issue is required for this command."
}

resolve_task_from_issue() {
  local payload
  payload="$("$SCRIPT_DIR/bootstrap_github_task.sh" --issue "$ISSUE_REF" --dry-run --json)"
  python3 -c 'import json,sys; print(json.load(sys.stdin).get("task_id",""))' <<<"$payload"
}

require_task() {
  if [[ -n "$TASK_ID" ]]; then
    printf '%s\n' "$TASK_ID"
    return 0
  fi
  if [[ -n "$ISSUE_REF" ]]; then
    local resolved
    resolved="$(resolve_task_from_issue)"
    [[ -n "$resolved" ]] || fail_json 4 "task_resolve_failed" "Issue did not resolve to a TASK_ID."
    printf '%s\n' "$resolved"
    return 0
  fi
  fail_json 2 "task_required" "--task or --issue is required for this command."
}

dispatch_target() {
  if [[ -n "$ISSUE_REF" ]]; then
    printf '%s\n' "$ISSUE_REF"
  else
    require_task
  fi
}

COMMAND="${1:-}"
if [[ -z "$COMMAND" || "$COMMAND" == "-h" || "$COMMAND" == "--help" ]]; then
  usage
  exit 0
fi
shift

TASK_ID=""
ISSUE_REF=""
ISSUE_NUMBER=""
PR_NUMBER=""
CONFIRM_USER_APPROVAL=false
CONFIRM_GITHUB_WRITE=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --issue)
      normalize_issue "${2:-}"
      shift 2
      ;;
    --task)
      normalize_task "${2:-}"
      shift 2
      ;;
    --pr)
      normalize_pr "${2:-}"
      shift 2
      ;;
    --confirm-user-approval)
      CONFIRM_USER_APPROVAL=true
      shift
      ;;
    --confirm-github-write)
      CONFIRM_GITHUB_WRITE=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --json)
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail_json 2 "unknown_argument" "Unknown argument: $1"
      ;;
  esac
done

cd "$REPO_ROOT"

case "$COMMAND" in
  analyze)
    if [[ -n "$ISSUE_REF" ]]; then
      "$SCRIPT_DIR/bootstrap_github_task.sh" --issue "$ISSUE_REF" --dry-run --json
    else
      task="$(require_task)"
      "$SCRIPT_DIR/route_task.sh" --task "$task" plan --json
    fi
    ;;
  bootstrap)
    require_issue
    args=(--issue "$ISSUE_REF" --json)
    [[ "$DRY_RUN" == true ]] && args+=(--dry-run)
    "$SCRIPT_DIR/bootstrap_github_task.sh" "${args[@]}"
    ;;
  plan|dev|test|review|result|status|cancel)
    target="$(dispatch_target)"
    "$SCRIPT_DIR/dispatch_task.sh" "$target" "$COMMAND" --json
    ;;
  approve)
    [[ "$CONFIRM_USER_APPROVAL" == true ]] || fail_json 6 "user_approval_required" "approve requires --confirm-user-approval."
    task="$(require_task)"
    "$SCRIPT_DIR/approve_task.sh" --task "$task" >&2
    json_emit ok=true command="$COMMAND" task_id="$task" state_source="TASK"
    ;;
  delivery)
    task="$(require_task)"
    "$SCRIPT_DIR/make_delivery_summary.sh" --task "$task" >&2
    json_emit ok=true command="$COMMAND" task_id="$task" message="delivery input generated; acceptance is not implied"
    ;;
  sync-pr)
    [[ "$CONFIRM_GITHUB_WRITE" == true ]] || fail_json 6 "github_write_confirmation_required" "sync-pr requires --confirm-github-write."
    task="$(require_task)"
    args=(--task "$task" --confirm-issue-ops --json)
    [[ -n "$PR_NUMBER" ]] && args+=(--pr "$PR_NUMBER")
    [[ "$DRY_RUN" == true ]] && args+=(--dry-run)
    "$SCRIPT_DIR/update_pr_from_result.sh" "${args[@]}"
    ;;
  record-external-review)
    task="$(require_task)"
    [[ -n "$PR_NUMBER" ]] || fail_json 2 "pr_required" "--pr is required for record-external-review."
    args=(--task "$task" --pr "$PR_NUMBER" --json)
    [[ "$DRY_RUN" == true ]] && args+=(--dry-run)
    "$SCRIPT_DIR/record_external_review.sh" "${args[@]}"
    ;;
  *)
    fail_json 2 "unknown_command" "Unknown command: $COMMAND"
    ;;
esac
