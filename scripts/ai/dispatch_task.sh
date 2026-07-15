#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
OUT_ROOT="$REPO_ROOT/.ai/results"

source "$SCRIPT_DIR/_work_level_lib.sh"
source "$SCRIPT_DIR/_approve_lib.sh"
source "$SCRIPT_DIR/_dispatch_phase_lib.sh"
source "$SCRIPT_DIR/_external_disk_lib.sh"
source "$SCRIPT_DIR/_dirty_gate_lib.sh"
source "$SCRIPT_DIR/_scope_report_lib.sh"

WRITER_LOCK_HELD=false
WRITER_LOCK_TASK_ID=""
WRITER_LOCK_WORKTREE=""
WRITER_LOCK_WRITER="codex"
WRITER_LOCK_PID="$$"

# Resource lock state (WS-V2-004)
RESOURCE_LOCKS_HELD=false
RESOURCE_LOCK_TASK_ID=""
RESOURCE_LOCK_PID="$$"

cleanup_resource_locks() {
  if [[ "${RESOURCE_LOCKS_HELD:-false}" == true && -n "${RESOURCE_LOCK_TASK_ID:-}" ]]; then
    "$SCRIPT_DIR/resource_lock.sh" release-all \
      --task-id "$RESOURCE_LOCK_TASK_ID" \
      --pid "$RESOURCE_LOCK_PID" >/dev/null 2>&1 || true
    RESOURCE_LOCKS_HELD=false
  fi
}

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
  cleanup_resource_locks
  cleanup_writer_lock
  trap - "$signal"
  kill -s "$signal" "$$"
}

_cleanup_all() {
  cleanup_resource_locks
  cleanup_writer_lock
}

trap _cleanup_all EXIT
trap 'on_signal INT' INT
trap 'on_signal TERM' TERM
trap 'on_signal HUP' HUP
trap 'on_signal QUIT' QUIT

usage() {
  cat <<'EOF'
Usage: scripts/ai/dispatch_task.sh <TASK_ID_OR_FILE> <STAGE> [OPTIONS]
       scripts/ai/dispatch_task.sh <TASK_ID_OR_FILE> --phase [OPTIONS]
       scripts/ai/dispatch_task.sh <TASK_ID_OR_FILE> --resume [OPTIONS]

STAGE:
  route | plan | dev | fix | test | review | result | pause | resume | cancel | status
  prepare | audit | dry-run | apply | close  (phased)

PHASED MODE:
  --phase       Run all phases from prepare through close (per risk level)
  --resume      Resume from last checkpoint

OPTIONS:
  --dry-run
  --explain
  --profile <profile>
  --json
  --no-color
EOF
}

main() {
  local task_arg stage dry_run explain requested_profile json_output no_color phased_mode resume_mode
  task_arg=""
  stage=""
  dry_run=false
  explain=false
  requested_profile=""
  json_output=false
  no_color=false
  phased_mode=false
  resume_mode=false

  if [[ $# -lt 1 ]]; then
    usage >&2
    return 2
  fi

  task_arg="$1"
  shift

  # Handle --phase and --resume as positional stage
  case "${1:-}" in
    --phase)  phased_mode=true; stage="prepare"; shift ;;
    --resume) resume_mode=true; stage="resume"; shift ;;
  esac

  # If 2 positional args, second is stage
  if [[ -z "$stage" && $# -ge 1 && "$1" != --* ]]; then
    stage="$1"
    shift
  fi

  if [[ -z "$stage" ]]; then
    usage >&2
    return 2
  fi

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

  # ── Phased / Resume routing ──────────────────────────────────────────
  if [[ "$phased_mode" == true ]]; then
    run_phased_dispatch "$task_id" "$task_file" "$task_file_rel" "$route_json" "$json_output"
    return $?
  fi

  if [[ "$resume_mode" == true ]]; then
    run_resume_dispatch "$task_id" "$task_file" "$task_file_rel" "$route_json" "$json_output"
    return $?
  fi

  # ── Legacy single-stage ──────────────────────────────────────────────

  if is_control_stage "$stage"; then
    execute_control_stage "$task_id" "$task_file" "$task_file_rel" "$stage" "$route_file" "$task_worktree" "$json_output"
    return $?
  fi

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
    # V3: Use operation-level approval verification
    verify_approval_v3 "$approval_file" "$task_id" "$task_file_rel" "$plan_file" "DEV" "$REPO_ROOT" "false"

    # WS-V2-006: Dirty workspace gate before dev
    echo "[GATE] Checking dirty workspace..." >&2
    check_dirty_workspace_gate "$task_file" "$task_id" "true" || {
      echo "Dirty workspace gate failed — stage=$stage blocked" >&2
      return 1
    }
  fi

  COMMAND=()
  resolve_child_command "$stage" "$task_id"

  local started_at ended_at stage_log stage_rc
  if stage_requires_writer_lock "$stage"; then
    acquire_resource_locks "$task_id" "$task_file"
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

  # WS-V2-006: Scope violation report after dev/fix
  if [[ "$stage" == "dev" || "$stage" == "fix" ]]; then
    if [[ $stage_rc -eq 0 ]]; then
      echo "[GATE] Generating scope violation report..." >&2
      check_scope_gate "$task_file" "$task_id" "$out_dir" "$REPO_ROOT" || {
        echo "Scope gate failed — subsequent phases (test/result) will be blocked" >&2
      }
    else
      echo "[GATE] Skipping scope report — dev/fix failed (rc=$stage_rc)" >&2
    fi
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

  # --- Risk Gate (V2) ---
  local risk_level
  risk_level="$(extract_task_meta_field "$task_file" "Risk Level" 2>/dev/null || echo "R3")"
  risk_level="${risk_level:-R3}"
  if [[ "$risk_level" == "R0" ]]; then
    case "$stage" in
      dev|fix|test|result)
        # R0 tasks require approval_scope to include external_review
        local approval_scope
        approval_scope="$(extract_task_meta_field "$task_file" "Approval Scope" 2>/dev/null || echo "")"
        if [[ "$approval_scope" != *"external_review"* ]]; then
          echo "Risk Gate (R0) failed: R0 tasks require approval_scope=external_review for stage=$stage, current scope=$approval_scope" >&2
          exit 1
        fi
        echo "[Risk Gate] R0 task, external_review in scope: OK"
        ;;
    esac
  fi

  case "$status" in
    CANCELLED|SKIPPED_NOT_APPLICABLE|SKIPPED_WITH_REASON)
      case "$stage" in
        dev|fix|test|result)
          echo "已取消/跳过 (status=$status)，无法执行 $stage" >&2
          exit 1
          ;;
      esac
      ;;
    PAUSED|BLOCKED)
      case "$stage" in
        dev|fix)
          echo "已暂停/阻塞 (status=$status)，需 resume" >&2
          exit 1
          ;;
      esac
      ;;
    BLOCKED_BY_DEPENDENCY)
      case "$stage" in
        dev|fix|test)
          echo "前置依赖未完成 (status=$status)，等待依赖解除" >&2
          exit 1
          ;;
      esac
      ;;
    FAILED)
      case "$stage" in
        plan|route|review|pause|cancel|status) ;;
        dev|test|result)
          echo "任务失败 (status=FAILED)，需先 fix 或 replan" >&2
          exit 1
          ;;
      esac
      ;;
    CLOSED)
      case "$stage" in
        route|status) ;;
        *)
          echo "任务已关闭 (status=CLOSED)，无法执行 $stage" >&2
          exit 1
          ;;
      esac
      ;;
  esac

  work_level="$(extract_work_level "$task_file")"
  if [[ "$stage" != "route" && "$work_level" != "L0" ]]; then
    check_worktree_gate "$task_file" 1>&2 || exit $?
    check_branch "$task_file" || exit $?
  fi

  # ── WS-V2-006 Gates ──────────────────────────────────────────────────
  check_base_branch "$task_file" || exit $?
  check_main_write_protection "$stage" "$REPO_ROOT" || exit $?
  check_external_disk_gate "$task_file" "$REPO_ROOT" || exit $?
  # ─────────────────────────────────────────────────────────────────────

  case "$stage" in
    route|review|pause|resume|cancel|status) return 0 ;;
    plan)
      [[ -z "$status" || "$status" == "DRAFT" || "$status" == "REQUIREMENT_READY" || "$status" == "REPLAN" || "$status" == "PLAN_READY" ]] || {
        echo "Stage Gate failed: plan is not allowed from Status=$status" >&2; exit 1;
      }
      ;;
    dev)
      [[ "$status" == "APPROVED_DEV" || "$status" == "APPROVED" || "$status" == "CODING" || "$status" == "EXECUTING" ]] || {
        echo "Stage Gate failed: dev requires APPROVED/APPROVED_DEV/CODING/EXECUTING, current=$status" >&2; exit 1;
      }
      ;;
    fix)
      [[ "$status" == "FAILED" || "$status" == "REPLAN" || "$status" == "APPROVED_DEV" || "$status" == "APPROVED" || "$status" == "CODING" || "$status" == "EXECUTING" ]] || {
        echo "Stage Gate failed: fix is not allowed from Status=$status" >&2; exit 1;
      }
      ;;
    test)
      [[ "$status" == "CODING" || "$status" == "EXECUTING" || "$status" == "TESTING" || "$status" == "APPROVED_DEV" || "$status" == "APPROVED" ]] || {
        echo "Stage Gate failed: test requires CODING/EXECUTING/TESTING/APPROVED, current=$status" >&2; exit 1;
      }
      ;;
    result)
      [[ "$status" == "TESTING" || "$status" == "REVIEWING" || "$status" == "DELIVERY_READY" || "$status" == "GATE_PASSED" || "$status" == "CLOSED" ]] || {
        echo "Stage Gate failed: result requires TESTING/REVIEWING/DELIVERY_READY/GATE_PASSED/CLOSED, current=$status" >&2; exit 1;
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

acquire_resource_locks() {
  local task_id="$1" task_file="$2"
  local resource_locks_json

  # Read resource_locks from task metadata (V2 YAML frontmatter)
  resource_locks_json="$(
    PYTHONPATH="$SCRIPT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}" python3 - "$task_file" <<'PY'
import json, sys
from pathlib import Path
from task_meta import parse_task_file
try:
    meta = parse_task_file(Path(sys.argv[1]))
    rl = meta.resource_locks
    print(json.dumps(list(rl)))
except Exception:
    print(json.dumps([]))
PY
  )"

  if [[ "$resource_locks_json" == "[]" || -z "$resource_locks_json" ]]; then
    return 0  # No resource locks needed
  fi

  local scopes
  scopes="$(python3 -c "import json; print(' '.join(json.loads('$resource_locks_json')))")"
  if [[ -z "$scopes" ]]; then
    return 0
  fi

  echo "[Resource Lock] Acquiring: $scopes"
  for scope in $scopes; do
    "$SCRIPT_DIR/resource_lock.sh" acquire \
      --scope "$scope" \
      --task-id "$task_id" \
      --pid "$RESOURCE_LOCK_PID" \
      >/dev/null || {
        echo "Resource lock failed for scope=$scope task=$task_id" >&2
        return 1
      }
  done
  RESOURCE_LOCK_TASK_ID="$task_id"
  RESOURCE_LOCKS_HELD=true
  echo "[Resource Lock] Acquired OK"
  return 0
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

is_control_stage() {
  case "$1" in
    pause|resume|cancel|status) return 0 ;;
    *) return 1 ;;
  esac
}

execute_control_stage() {
  local task_id="$1" task_file="$2" task_file_rel="$3" stage="$4" route_file="$5" worktree="$6" json_output="$7"
  local started_at ended_at stage_log output rc

  if [[ "$stage" == "resume" ]]; then
    validate_resume_gates "$task_file" "$task_id" "$task_file_rel" || return $?
  fi

  if [[ "$stage" == "pause" || "$stage" == "cancel" ]]; then
    release_task_writer_lock_if_held "$task_id" "$worktree"
  fi

  started_at="$(utc_now)"
  stage_log="$OUT_ROOT/$task_id/${stage}.log"
  set +e
  output="$(
    PYTHONPATH="$SCRIPT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}" \
      python3 "$SCRIPT_DIR/lib/dispatch_control.py" "$stage" "$task_id" --repo-root "$REPO_ROOT" --json 2>&1
  )"
  rc=$?
  set -e
  ended_at="$(utc_now)"
  {
    echo "[DISPATCH] started_at=$started_at"
    echo "[DISPATCH] task=$task_id stage=$stage"
    echo "$output"
    echo "[DISPATCH] ended_at=$ended_at"
    echo "[DISPATCH] exit_code=$rc"
  } > "$stage_log"

  write_route_status "$route_file" "$rc" "$started_at" "$ended_at" "false"
  if [[ $rc -ne 0 ]]; then
    echo "$output" >&2
    return "$rc"
  fi
  if [[ "$json_output" == true ]]; then
    printf '%s\n' "$output"
  else
    echo "[OK] task=$task_id stage=$stage log=$stage_log"
  fi
  return 0
}

validate_resume_gates() {
  local task_file="$1" task_id="$2" task_file_rel="$3" previous
  check_branch "$task_file" || return $?
  previous="$(
    python3 - "$OUT_ROOT/$task_id/pause_record.json" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
print(json.loads(path.read_text(encoding="utf-8")).get("previous_status", ""))
PY
  )"
  case "$previous" in
    APPROVED_DEV|CODING|FAILED|REPLAN)
      local plan_file approval_file
      plan_file="$OUT_ROOT/$task_id/plan_result.md"
      approval_file="$REPO_ROOT/.ai/approvals/${task_id}.json"
      verify_approval_v3 "$approval_file" "$task_id" "$task_file_rel" "$plan_file" "DEV" "$REPO_ROOT" "false" || return $?
      ;;
  esac
}

release_task_writer_lock_if_held() {
  local task_id="$1" worktree="$2"
  PYTHONPATH="$SCRIPT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}" python3 - "$REPO_ROOT" "$task_id" "$worktree" <<'PY'
import sys
from pathlib import Path
from writer_lock import lock_paths, read_lock, release

repo_root = Path(sys.argv[1])
task_id = sys.argv[2]
worktree = sys.argv[3]
lock_file, _, _ = lock_paths(repo_root, worktree)
lock = read_lock(lock_file)
if lock and lock.get("task_id") == task_id:
    release(
        repo_root,
        task_id=task_id,
        worktree=worktree,
        writer=str(lock.get("writer", "codex")),
        pid=lock.get("pid"),
    )
PY
}

# ── Phased Dispatch (WS-V2-005) ─────────────────────────────────────────────

run_phased_dispatch() {
  local task_id="$1" task_file="$2" task_file_rel="$3" route_json="$4" json_output="$5"

  local risk_level epic_id plan_file approval_file
  risk_level="$(json_get risk_level <<<"$route_json")"
  epic_id="${task_id%%-*}"  # Extract epic from task_id prefix
  plan_file="$OUT_ROOT/$task_id/plan_result.md"
  approval_file="$REPO_ROOT/.ai/approvals/${task_id}.json"

  echo "[PHASED] task=$task_id risk=$risk_level"

  run_phased_execution \
    "$task_id" "$task_file" "$task_file_rel" "$plan_file" \
    "$approval_file" "$OUT_ROOT/$task_id" "$risk_level" "$epic_id"
  local rc=$?

  if [[ "$json_output" == true ]]; then
    echo "{\"task_id\":\"$task_id\",\"phased\":true,\"exit_code\":$rc}"
  elif [[ $rc -eq 0 ]]; then
    echo "[OK] Phased dispatch complete: task=$task_id"
  else
    echo "[FAIL] Phased dispatch failed: task=$task_id exit_code=$rc" >&2
  fi
  return $rc
}

run_resume_dispatch() {
  local task_id="$1" task_file="$2" task_file_rel="$3" route_json="$4" json_output="$5"

  local checkpoint_file risk_level plan_file approval_file epic_id
  checkpoint_file="$OUT_ROOT/$task_id/dispatch_checkpoint.json"
  risk_level="$(json_get risk_level <<<"$route_json")"
  epic_id="${task_id%%-*}"
  plan_file="$OUT_ROOT/$task_id/plan_result.md"
  approval_file="$REPO_ROOT/.ai/approvals/${task_id}.json"

  # Verify checkpoint exists
  if [[ ! -f "$checkpoint_file" ]]; then
    echo "[ERROR] No checkpoint found for --resume: $checkpoint_file" >&2
    return 4
  fi

  # Verify resume integrity
  local integrity_result integrity_ok
  integrity_result="$(verify_resume_integrity "$checkpoint_file" "$plan_file" "$task_file_rel" 2>&1)"
  integrity_ok=$?
  if [[ $integrity_ok -ne 0 ]]; then
    echo "[ERROR] Resume integrity check failed:" >&2
    echo "$integrity_result" | python3 -c 'import json,sys; d=json.load(sys.stdin); [print(f"  - {f[\"check\"]}: expected={f.get(\"expected\",\"?\")} actual={f.get(\"actual\",\"?\")}") for f in d.get("failures",[])]' 2>/dev/null || echo "$integrity_result" >&2
    return 4
  fi

  # Find next phase
  local next_phase
  next_phase="$(find_resume_phase "$checkpoint_file" "$risk_level")"
  if [[ "$next_phase" == "ALL_DONE" || -z "$next_phase" ]]; then
    echo "[RESUME] All phases already completed for task=$task_id"
    return 0
  fi

  echo "[RESUME] task=$task_id risk=$risk_level resume_from=$next_phase"

  # Run from the resume point
  local phases overall_rc=0
  phases="$(get_phase_sequence "$risk_level")"
  local found=false

  for phase in $phases; do
    if [[ "$found" == false ]]; then
      if [[ "$phase" == "$next_phase" ]]; then
        found=true
      else
        continue
      fi
    fi

    echo "--- Phase: $phase ---"

    # Gate check
    local gate_result gate_ok
    gate_result="$(validate_phase_gate "$phase" "$risk_level" "$checkpoint_file" "false" "" 2>&1)"
    gate_ok=$?
    if [[ $gate_ok -ne 0 ]]; then
      echo "[GATE FAIL] $phase: $gate_result"
      local gate_msg
      gate_msg="$(echo "$gate_result" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("detail",""))' 2>/dev/null || echo "$gate_result")"
      update_checkpoint_phase "$checkpoint_file" "$phase" "FAILED" "1" "$gate_msg" ""
      overall_rc=1
      break
    fi

    local started_at ended_at phase_rc stage_log
    started_at="$(phase_utc_now)"
    stage_log="$OUT_ROOT/$task_id/phase_${phase}.log"

    set +e
    run_single_phase "$phase" "$task_id" "$task_file" "$plan_file" "$approval_file" "$OUT_ROOT/$task_id" "$stage_log"
    phase_rc=$?
    set -e

    ended_at="$(phase_utc_now)"

    if [[ $phase_rc -eq 0 ]]; then
      update_checkpoint_phase "$checkpoint_file" "$phase" "PASSED" "0" "" "$stage_log" "$started_at" "$ended_at"
      echo "[PASS] $phase"
    else
      local phase_error
      phase_error="$(tail -5 "$stage_log" 2>/dev/null | tr '\n' ' ')"
      update_checkpoint_phase "$checkpoint_file" "$phase" "FAILED" "$phase_rc" "$phase_error" "$stage_log" "$started_at" "$ended_at"
      echo "[FAIL] $phase exit_code=$phase_rc"
      overall_rc=$phase_rc
      break
    fi
  done

  if [[ "$json_output" == true ]]; then
    echo "{\"task_id\":\"$task_id\",\"resumed\":true,\"exit_code\":$overall_rc}"
  elif [[ $overall_rc -eq 0 ]]; then
    echo "[OK] Resume dispatch complete: task=$task_id"
  else
    echo "[FAIL] Resume dispatch failed: task=$task_id exit_code=$overall_rc" >&2
  fi
  return $overall_rc
}

main "$@"
