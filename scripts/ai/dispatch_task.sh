#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
OUT_ROOT="$REPO_ROOT/.ai/results"

source "$SCRIPT_DIR/_work_level_lib.sh"
source "$SCRIPT_DIR/_approve_lib.sh"

WRITER_LOCK_HELD=false
WRITER_LOCK_TASK_ID=""
WRITER_LOCK_WORKTREE=""
WRITER_LOCK_WRITER="codex"
WRITER_LOCK_PID="$$"

cleanup_writer_lock() {
  if [[ "${WRITER_LOCK_HELD:-false}" == true ]]; then
    "$SCRIPT_DIR/writer_lock.sh" release \
      --task-id "$WRITER_LOCK_TASK_ID" \
      --worktree "$WRITER_LOCK_WORKTREE" \
      --writer "$WRITER_LOCK_WRITER" \
      --pid "$WRITER_LOCK_PID" >/dev/null 2>&1 || true
    WRITER_LOCK_HELD=false
  fi
}

on_signal() {
  local signal="$1"
  cleanup_writer_lock
  trap - "$signal"
  kill -s "$signal" "$$"
}

trap cleanup_writer_lock EXIT
trap 'on_signal INT' INT
trap 'on_signal TERM' TERM
trap 'on_signal HUP' HUP
trap 'on_signal QUIT' QUIT

usage() {
  cat <<'EOF'
Usage: scripts/ai/dispatch_task.sh <TASK_ID_OR_FILE> <STAGE> [OPTIONS]

STAGE:
  route | plan | dev | fix | test | review | result

OPTIONS:
  --dry-run
  --explain
  --profile <profile>
  --json
  --no-color
EOF
}

main() {
  local task_arg stage dry_run explain requested_profile json_output no_color
  task_arg=""
  stage=""
  dry_run=false
  explain=false
  requested_profile=""
  json_output=false
  no_color=false

  if [[ $# -lt 2 ]]; then
    usage >&2
    return 2
  fi

  task_arg="$1"
  stage="$2"
  shift 2

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run) dry_run=true; shift ;;
      --explain) explain=true; shift ;;
      --profile) requested_profile="${2:-}"; [[ -n "$requested_profile" ]] || { echo "--profile requires a value" >&2; return 2; }; shift 2 ;;
      --json) json_output=true; shift ;;
      --no-color) no_color=true; shift ;;
      --yolo|*danger-full-access*|*dangerously-bypass-approvals-and-sandbox*)
        echo "Forbidden option: $1" >&2
        return 2
        ;;
      -h|--help) usage; return 0 ;;
      *) echo "Unknown argument: $1" >&2; usage >&2; return 2 ;;
    esac
  done

  if [[ "${GUIYI_AI_DRY_RUN:-}" == "1" ]]; then
    dry_run=true
  fi

  cd "$REPO_ROOT"

  local route_args route_json route_rc task_id task_file_rel task_status calls_model sandbox task_branch task_worktree
  route_args=("$task_arg" "$stage" "--json")
  if [[ -n "$requested_profile" ]]; then
    route_args+=("--profile" "$requested_profile")
  fi
  if [[ "$explain" == true ]]; then
    route_args+=("--explain")
  fi

  set +e
  route_json="$("$SCRIPT_DIR/route_task.sh" "${route_args[@]}" 2> >(cat >&2))"
  route_rc=$?
  set -e
  if [[ $route_rc -ne 0 ]]; then
    return "$route_rc"
  fi

  task_id="$(json_get task_id <<<"$route_json")"
  task_file_rel="$(json_get task_file <<<"$route_json")"
  task_status="$(json_get status <<<"$route_json")"
  calls_model="$(json_get calls_model <<<"$route_json")"
  sandbox="$(json_get sandbox <<<"$route_json")"
  task_branch="$(json_get branch <<<"$route_json")"
  task_worktree="$(json_get worktree <<<"$route_json")"

  local out_dir route_file task_file
  out_dir="$OUT_ROOT/$task_id"
  mkdir -p "$out_dir"
  route_file="$out_dir/route.json"
  printf '%s\n' "$route_json" > "$route_file"

  task_file="$task_file_rel"
  if [[ "$task_file" != /* ]]; then
    task_file="$REPO_ROOT/$task_file_rel"
  fi

  validate_static_gates "$task_file" "$stage" "$task_status"
  validate_production_gate "$task_file" "$task_id" "$stage" "$route_json"
  task_worktree="$(resolve_lock_worktree "$task_worktree")"
  if stage_conflicts_with_writer "$stage"; then
    ensure_no_active_writer "$task_worktree"
  fi

  if [[ "$dry_run" == true || "$stage" == "route" ]]; then
    write_route_status "$route_file" "0" "$(utc_now)" "$(utc_now)" "true"
    if [[ "$json_output" == true ]]; then
      read_file "$route_file"
    else
      echo "[DRY-RUN] task=$task_id stage=$stage sandbox=$sandbox calls_model=$calls_model route=$route_file"
    fi
    return 0
  fi

  local env_check_file env_check_rc
  env_check_file="$out_dir/env_check.json"
  set +e
  "$REPO_ROOT/scripts/env/check_task_env.sh" \
    --task "$task_file" \
    --stage "$stage" \
    --worktree "$task_worktree" \
    --output "$env_check_file" \
    --quiet
  env_check_rc=$?
  set -e
  if [[ $env_check_rc -ne 0 ]]; then
    print_env_check_failures "$env_check_file"
    return "$env_check_rc"
  fi

  if [[ "$stage" == "dev" || "$stage" == "fix" ]]; then
    local plan_file approval_file
    plan_file="$out_dir/plan_result.md"
    approval_file="$REPO_ROOT/.ai/approvals/${task_id}.json"
    verify_approval "$approval_file" "$task_id" "$task_file_rel" "$plan_file"
  fi

  COMMAND=()
  resolve_child_command "$stage" "$task_id"

  local started_at ended_at stage_log stage_rc
  if stage_requires_writer_lock "$stage"; then
    acquire_writer_lock "$task_id" "$task_worktree" "$task_branch" "$stage"
  fi

  started_at="$(utc_now)"
  stage_log="$out_dir/${stage}.log"
  set +e
  {
    echo "[DISPATCH] started_at=$started_at"
    echo "[DISPATCH] task=$task_id stage=$stage sandbox=$sandbox calls_model=$calls_model"
    echo "[DISPATCH] command=${COMMAND[*]}"
    "${COMMAND[@]}"
  } > "$stage_log" 2>&1
  stage_rc=$?
  set -e
  ended_at="$(utc_now)"
  {
    echo "[DISPATCH] ended_at=$ended_at"
    echo "[DISPATCH] exit_code=$stage_rc"
  } >> "$stage_log"

  cleanup_writer_lock

  write_route_status "$route_file" "$stage_rc" "$started_at" "$ended_at" "false"

  if [[ "$json_output" == true ]]; then
    read_file "$route_file"
  elif [[ $stage_rc -eq 0 ]]; then
    echo "[OK] task=$task_id stage=$stage log=$stage_log route=$route_file"
  else
    echo "[FAIL] task=$task_id stage=$stage exit_code=$stage_rc log=$stage_log" >&2
  fi

  return "$stage_rc"
}

json_get() {
  python3 -c '
import json, sys
field = sys.argv[1]
data = json.load(sys.stdin)
value = data.get(field, "")
if isinstance(value, bool):
    print("true" if value else "false")
else:
    print(value)
' "$1"
}

read_file() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).read_text(encoding="utf-8"), end="")
PY
}

utc_now() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

validate_static_gates() {
  local task_file="$1" stage="$2" status="$3" work_level
  [[ -f "$task_file" ]] || { echo "TASK file missing: $task_file" >&2; exit 4; }

  work_level="$(extract_work_level "$task_file")"
  if [[ "$stage" != "route" && "$work_level" != "L0" ]]; then
    check_worktree_gate "$task_file" 1>&2 || exit $?
    check_branch "$task_file" || exit $?
  fi

  case "$stage" in
    route|review) return 0 ;;
    plan)
      [[ -z "$status" || "$status" == "REQUIREMENT_READY" || "$status" == "REPLAN" || "$status" == "PLAN_READY" ]] || {
        echo "Stage Gate failed: plan is not allowed from Status=$status" >&2; exit 1;
      }
      ;;
    dev)
      [[ "$status" == "APPROVED_DEV" || "$status" == "CODING" ]] || {
        echo "Stage Gate failed: dev requires APPROVED_DEV or CODING, current=$status" >&2; exit 1;
      }
      ;;
    fix)
      [[ "$status" == "FAILED" || "$status" == "REPLAN" || "$status" == "APPROVED_DEV" || "$status" == "CODING" ]] || {
        echo "Stage Gate failed: fix is not allowed from Status=$status" >&2; exit 1;
      }
      ;;
    test)
      [[ "$status" == "CODING" || "$status" == "TESTING" || "$status" == "APPROVED_DEV" ]] || {
        echo "Stage Gate failed: test requires CODING/TESTING/APPROVED_DEV, current=$status" >&2; exit 1;
      }
      ;;
    result)
      [[ "$status" == "TESTING" || "$status" == "DELIVERY_READY" || "$status" == "CLOSED" ]] || {
        echo "Stage Gate failed: result requires TESTING/DELIVERY_READY/CLOSED, current=$status" >&2; exit 1;
      }
      ;;
  esac
}

validate_production_gate() {
  local task_file="$1" task_id="$2" stage="$3" route_json="$4"
  case "$stage" in
    dev|fix|test|result) ;;
    *) return 0 ;;
  esac

  local production_requested production_approved task_approved
  production_requested="$(json_get production_write_requested <<<"$route_json")"
  if [[ "${APP_ENV:-}" == "production" ]]; then
    production_requested="true"
  fi
  [[ "$production_requested" == "true" ]] || return 0

  production_approved="$(json_get production_write_approved <<<"$route_json")"
  task_approved="false"
  if [[ -f "$REPO_ROOT/.ai/approvals/${task_id}.json" ]]; then
    task_approved="$(python3 - "$REPO_ROOT/.ai/approvals/${task_id}.json" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    print("false")
    raise SystemExit(0)
print("true" if data.get("production_write_approved") is True else "false")
PY
)"
  fi

  if [[ "$production_approved" == "true" || "$task_approved" == "true" ]]; then
    return 0
  fi

  echo "Production Write Gate failed: production write requested but not approved for stage=$stage" >&2
  exit 1
}

resolve_child_command() {
  local stage="$1" task_id="$2" child_dir
  child_dir="${GUIYI_AI_SCRIPT_DIR:-$SCRIPT_DIR}"
  case "$stage" in
    plan) COMMAND=("$child_dir/codex_plan.sh" "--task" "$task_id") ;;
    dev|fix) COMMAND=("$child_dir/codex_dev.sh" "--task" "$task_id") ;;
    test) COMMAND=("$child_dir/run_tests.sh" "--task" "$task_id") ;;
    result) COMMAND=("$child_dir/collect_result.sh" "--task" "$task_id") ;;
    review)
      if [[ -x "$child_dir/codex_review.sh" ]]; then
        COMMAND=("$child_dir/codex_review.sh" "--task" "$task_id")
      elif [[ -x "$child_dir/review_task.sh" ]]; then
        COMMAND=("$child_dir/review_task.sh" "--task" "$task_id")
      else
        echo "Review stage is not available: no codex_review.sh or review_task.sh" >&2
        exit 4
      fi
      ;;
    *) echo "No child command for stage=$stage" >&2; exit 2 ;;
  esac
}

stage_requires_writer_lock() {
  case "$1" in
    dev|fix) return 0 ;;
    *) return 1 ;;
  esac
}

stage_conflicts_with_writer() {
  case "$1" in
    plan|review) return 0 ;;
    *) return 1 ;;
  esac
}

resolve_lock_worktree() {
  local task_worktree="${1:-}"
  if [[ -n "$task_worktree" ]]; then
    printf '%s\n' "$task_worktree"
  else
    printf '%s\n' "$REPO_ROOT"
  fi
}

ensure_no_active_writer() {
  local worktree="$1"
  "$SCRIPT_DIR/writer_lock.sh" status --worktree "$worktree" --fail-if-held >/dev/null
}

print_env_check_failures() {
  local env_check_file="$1"
  python3 - "$env_check_file" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file():
    print("Environment Gate failed: result file missing", file=sys.stderr)
    raise SystemExit(0)
data = json.loads(path.read_text(encoding="utf-8"))
for failure in data.get("failures", []):
    print(f"[FAIL] {failure}", file=sys.stderr)
PY
}

acquire_writer_lock() {
  local task_id="$1" worktree="$2" branch="$3" stage="$4"
  "$SCRIPT_DIR/writer_lock.sh" acquire \
    --task-id "$task_id" \
    --worktree "$worktree" \
    --branch "$branch" \
    --writer "$WRITER_LOCK_WRITER" \
    --stage "$stage" \
    --pid "$WRITER_LOCK_PID" \
    --command "${COMMAND[*]}" >/dev/null
  WRITER_LOCK_TASK_ID="$task_id"
  WRITER_LOCK_WORKTREE="$worktree"
  WRITER_LOCK_HELD=true
}

write_route_status() {
  local route_file="$1" exit_code="$2" started_at="$3" ended_at="$4" dry_run="$5"
  python3 - "$route_file" "$exit_code" "$started_at" "$ended_at" "$dry_run" <<'PY'
import json, sys
path, exit_code, started_at, ended_at, dry_run = sys.argv[1:6]
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)
data["dispatcher"] = {
    "dry_run": dry_run == "true",
    "started_at": started_at,
    "ended_at": ended_at,
    "exit_code": int(exit_code),
}
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
PY
}

main "$@"
