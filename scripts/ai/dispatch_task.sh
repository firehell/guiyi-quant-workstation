#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
OUT_ROOT="$REPO_ROOT/.ai/results"
LOCK_DIR="$REPO_ROOT/.run/dispatch"

source "$SCRIPT_DIR/_work_level_lib.sh"
source "$SCRIPT_DIR/_approve_lib.sh"

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

  local route_args route_json route_rc task_id task_file_rel task_status calls_model sandbox
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

  if [[ "$dry_run" == true || "$stage" == "route" ]]; then
    write_route_status "$route_file" "0" "$(utc_now)" "$(utc_now)" "true"
    if [[ "$json_output" == true ]]; then
      read_file "$route_file"
    else
      echo "[DRY-RUN] task=$task_id stage=$stage sandbox=$sandbox calls_model=$calls_model route=$route_file"
    fi
    return 0
  fi

  if [[ "$stage" == "dev" || "$stage" == "fix" ]]; then
    local plan_file approval_file
    plan_file="$out_dir/plan_result.md"
    approval_file="$REPO_ROOT/.ai/approvals/${task_id}.json"
    verify_approval "$approval_file" "$task_id" "$task_file_rel" "$plan_file"
  fi

  COMMAND=()
  resolve_child_command "$stage" "$task_id"

  local lock_held started_at ended_at stage_log stage_rc
  lock_held=false
  if stage_requires_lock "$stage"; then
    acquire_lock "$task_id"
    lock_held=true
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

  if [[ "$lock_held" == true ]]; then
    release_lock "$task_id"
  fi

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

stage_requires_lock() {
  case "$1" in
    dev|fix|test|result) return 0 ;;
    *) return 1 ;;
  esac
}

acquire_lock() {
  local task_id="$1" lock_file="$LOCK_DIR/dispatch.lock" pid_file="$LOCK_DIR/dispatch.pid" ts_file="$LOCK_DIR/dispatch.timestamp"
  mkdir -p "$LOCK_DIR"
  if [[ -f "$lock_file" ]]; then
    local owner pid
    owner="$(read_file "$lock_file")"
    pid="$(read_file "$pid_file" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      echo "Dispatch lock is held by task=$owner pid=$pid" >&2
      return 3
    fi
    rm -f "$lock_file" "$pid_file" "$ts_file"
  fi
  printf '%s\n' "$task_id" > "$lock_file"
  printf '%s\n' "$$" > "$pid_file"
  utc_now > "$ts_file"
}

release_lock() {
  local task_id="$1" lock_file="$LOCK_DIR/dispatch.lock" pid_file="$LOCK_DIR/dispatch.pid" ts_file="$LOCK_DIR/dispatch.timestamp" owner
  owner="$(read_file "$lock_file" 2>/dev/null || true)"
  if [[ -z "$owner" || "$owner" == "$task_id" ]]; then
    rm -f "$lock_file" "$pid_file" "$ts_file"
  fi
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
