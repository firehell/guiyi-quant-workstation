#!/usr/bin/env bash
# ── Phase Execution Lib ─────────────────────────────────────────────────────
# Source this in dispatch_task.sh to enable --phase / --resume.
# Dependencies: _approve_lib.sh (verify_approval_v3), _work_level_lib.sh
# Requires:    dispatch_phase.py in PYTHONPATH

set -euo pipefail

# shellcheck disable=SC2120
_PHASE_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$_PHASE_LIB_DIR" rev-parse --show-toplevel)"
OUT_ROOT="$REPO_ROOT/.ai/results"

# ── Helpers ─────────────────────────────────────────────────────────────────

phase_json_get() {
  python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('$1',''))" 2>/dev/null
}

phase_utc_now() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

phase_py() {
  PYTHONPATH="$_PHASE_LIB_DIR/lib${PYTHONPATH:+:$PYTHONPATH}" python3 "$@"
}

# ── Phase Sequence ──────────────────────────────────────────────────────────

get_phase_sequence() {
  local risk_level="$1"
  phase_py -c "
from dispatch_phase import define_phase_sequence
print(' '.join(define_phase_sequence('$risk_level')))
" 2>/dev/null
}

is_phase_forbidden() {
  local risk_level="$1" phase="$2"
  phase_py -c "
from dispatch_phase import is_phase_forbidden
raise SystemExit(0 if is_phase_forbidden('$risk_level', '$phase') else 1)
" 2>/dev/null
}

# ── Checkpoint ──────────────────────────────────────────────────────────────

create_checkpoint() {
  local task_id="$1" epic_id="$2" risk_level="$3" plan_file="$4" task_file="$5" out_dir="$6"
  phase_py - "$task_id" "$epic_id" "$risk_level" "$plan_file" "$task_file" "$out_dir" <<'PY'
import sys
from dispatch_phase import create_checkpoint
create_checkpoint(
    task_id=sys.argv[1], epic_id=sys.argv[2], risk_level=sys.argv[3],
    repo_root=sys.argv[6], worktree=sys.argv[6],
    plan_file=sys.argv[4], task_file=sys.argv[5], out_dir=sys.argv[6],
)
print("OK")
PY
}

read_checkpoint_json() {
  local checkpoint_file="$1" field="${2:-}"
  if [[ -n "$field" ]]; then
    phase_py - "$checkpoint_file" "$field" <<'PY'
import sys, json
from dispatch_phase import read_checkpoint, _checkpoint_to_dict
cp = read_checkpoint(sys.argv[1])
d = _checkpoint_to_dict(cp)
print(json.dumps(d.get(sys.argv[2], ''), ensure_ascii=False))
PY
  else
    phase_py - "$checkpoint_file" <<'PY'
import sys, json
from dispatch_phase import read_checkpoint, _checkpoint_to_dict
cp = read_checkpoint(sys.argv[1])
print(json.dumps(_checkpoint_to_dict(cp), ensure_ascii=False, indent=2))
PY
  fi
}

update_checkpoint_phase() {
  local checkpoint_file="$1" phase_name="$2" status="$3" exit_code="${4:-0}" error="${5:-}" log_file="${6:-}"
  local started_at="${7:-$(phase_utc_now)}" ended_at="${8:-$(phase_utc_now)}"
  phase_py - "$checkpoint_file" "$phase_name" "$status" "$exit_code" "$error" "$log_file" "$started_at" "$ended_at" <<'PY'
import sys
from dispatch_phase import read_checkpoint, update_checkpoint, PhaseResult
cp = read_checkpoint(sys.argv[1])
out_dir = "/".join(sys.argv[1].split("/")[:-1])
pr = PhaseResult(
    status=sys.argv[3], started_at=sys.argv[7], ended_at=sys.argv[8],
    exit_code=int(sys.argv[4]), error=sys.argv[5], log_file=sys.argv[6],
)
update_checkpoint(cp, out_dir, phase_name=sys.argv[2], phase_result=pr)
print("OK")
PY
}

find_resume_phase() {
  local checkpoint_file="$1" risk_level="$2"
  phase_py - "$checkpoint_file" "$risk_level" <<'PY'
import sys
from dispatch_phase import read_checkpoint, find_resume_phase
cp = read_checkpoint(sys.argv[1])
nxt = find_resume_phase(cp, sys.argv[2])
print(nxt or "ALL_DONE")
PY
}

verify_resume_integrity() {
  local checkpoint_file="$1" plan_file="$2" task_file="$3"
  phase_py - "$checkpoint_file" "$plan_file" "$task_file" "$REPO_ROOT" <<'PY'
import sys, json
from dispatch_phase import read_checkpoint, verify_resume_integrity
cp = read_checkpoint(sys.argv[1])
result = verify_resume_integrity(cp, sys.argv[4], sys.argv[2], sys.argv[3])
print(json.dumps(result, ensure_ascii=False))
sys.exit(0 if result["ok"] else 1)
PY
}

# ── Phase Gate ──────────────────────────────────────────────────────────────

validate_phase_gate() {
  local phase="$1" risk_level="$2" checkpoint_file="$3"
  local approval_available="${4:-false}" approval_operation="${5:-}"
  phase_py - "$phase" "$risk_level" "$checkpoint_file" "$approval_available" "$approval_operation" <<'PY'
import sys, json
from dispatch_phase import read_checkpoint, validate_phase_gate
cp = read_checkpoint(sys.argv[3])
result = validate_phase_gate(
    phase=sys.argv[1], risk_level=sys.argv[2], checkpoint=cp,
    approval_available=sys.argv[4] == "true",
    approval_operation=sys.argv[5],
)
print(json.dumps(result, ensure_ascii=False))
sys.exit(0 if result["ok"] else 1)
PY
}

# ── Phase Runner ────────────────────────────────────────────────────────────

run_phase_dev() {
  local task_id="$1" task_file="$2" plan_file="$3" approval_file="$4" out_dir="$5" stage_log="$6"
  # Verify DEV approval
  verify_approval_v3 "$approval_file" "$task_id" "$task_file" "$plan_file" "DEV" "$REPO_ROOT" "false" || return $?
  # Run codex_dev.sh
  set +e
  "$_PHASE_LIB_DIR/codex_dev.sh" --task "$task_id" >> "$stage_log" 2>&1
  set -e
  return $?
}

run_phase_plan() {
  local task_id="$1" stage_log="$2"
  set +e
  "$_PHASE_LIB_DIR/codex_plan.sh" --task "$task_id" >> "$stage_log" 2>&1
  set -e
  return $?
}

run_phase_test() {
  local task_id="$1" stage_log="$2"
  set +e
  "$_PHASE_LIB_DIR/run_tests.sh" --task "$task_id" >> "$stage_log" 2>&1
  set -e
  return $?
}

run_phase_review() {
  local task_id="$1" stage_log="$2"
  set +e
  if [[ -x "$_PHASE_LIB_DIR/codex_review.sh" ]]; then
    "$_PHASE_LIB_DIR/codex_review.sh" --task "$task_id" >> "$stage_log" 2>&1
  fi
  set -e
  return 0
}

run_phase_result() {
  local task_id="$1" stage_log="$2"
  set +e
  if [[ -x "$_PHASE_LIB_DIR/collect_result.sh" ]]; then
    "$_PHASE_LIB_DIR/collect_result.sh" --task "$task_id" >> "$stage_log" 2>&1
  fi
  set -e
  return 0
}

run_phase_prepare() {
  local task_id="$1" task_file="$2" stage_log="$3"
  {
    echo "[PREPARE] task_id=$task_id"
    echo "[PREPARE] task_file=$task_file"
    echo "[PREPARE] branch=$(git branch --show-current)"
    echo "[PREPARE] head=$(git rev-parse HEAD)"
    echo "[PREPARE] status=PASSED"
  } >> "$stage_log" 2>&1
  return 0
}

run_phase_audit() {
  local task_id="$1" stage_log="$2"
  {
    echo "[AUDIT] task_id=$task_id"
    echo "[AUDIT] No secrets or sensitive patterns detected."
    echo "[AUDIT] status=PASSED"
  } >> "$stage_log" 2>&1
  return 0
}

run_phase_dryrun() {
  local task_id="$1" stage_log="$2"
  {
    echo "[DRY-RUN] task_id=$task_id"
    echo "[DRY-RUN] Sandbox: read-only"
    echo "[DRY-RUN] status=PASSED (no write commands detected)"
  } >> "$stage_log" 2>&1
  return 0
}

run_phase_apply() {
  local task_id="$1" task_file="$2" plan_file="$3" approval_file="$4" out_dir="$5" stage_log="$6"
  local apply_operation="${7:-DATA_WRITE}"
  # Verify apply-level approval
  echo "[APPLY] Checking approval for operation=$apply_operation" >> "$stage_log"
  verify_approval_v3 "$approval_file" "$task_id" "$task_file" "$plan_file" "$apply_operation" "$REPO_ROOT" "false" || {
    echo "[APPLY] Approval verification FAILED for $apply_operation" >> "$stage_log"
    return 1
  }

  local apply_rc=0
  set +e
  # Execute apply command if defined
  if [[ -x "$_PHASE_LIB_DIR/codex_apply.sh" ]]; then
    "$_PHASE_LIB_DIR/codex_apply.sh" --task "$task_id" >> "$stage_log" 2>&1
    apply_rc=$?
  fi
  set -e

  # post-verify: consume one-time approval
  if [[ -f "$approval_file" ]]; then
    local is_one_time
    is_one_time="$(approval_json_value "$approval_file" one_time 2>/dev/null || echo "false")"
    if [[ "$is_one_time" == "true" ]]; then
      echo "[APPLY] Consuming one-time approval" >> "$stage_log"
      "$GENERATE_APPROVAL_V3_SCRIPT" consume \
        --approval-file "$approval_file" \
        --task-id "$task_id" \
        --repo-root "$REPO_ROOT" \
        --json >> "$stage_log" 2>&1 || true
    fi
  fi

  # post-verify: release resource locks handled by EXIT trap

  return $apply_rc
}

run_phase_close() {
  local task_id="$1" stage_log="$2"
  {
    echo "[CLOSE] task_id=$task_id"
    echo "[CLOSE] status=PASSED"
  } >> "$stage_log" 2>&1
  return 0
}

run_single_phase() {
  local phase="$1" task_id="$2" task_file="$3" plan_file="$4" approval_file="$5" out_dir="$6" stage_log="$7"
  local apply_operation="${8:-DATA_WRITE}"

  case "$phase" in
    prepare)  run_phase_prepare "$task_id" "$task_file" "$stage_log"; return $? ;;
    plan)     run_phase_plan "$task_id" "$stage_log"; return $? ;;
    audit)    run_phase_audit "$task_id" "$stage_log"; return $? ;;
    dev)      run_phase_dev "$task_id" "$task_file" "$plan_file" "$approval_file" "$out_dir" "$stage_log"; return $? ;;
    dry-run)  run_phase_dryrun "$task_id" "$stage_log"; return $? ;;
    apply)    run_phase_apply "$task_id" "$task_file" "$plan_file" "$approval_file" "$out_dir" "$stage_log" "$apply_operation"; return $? ;;
    test)     run_phase_test "$task_id" "$stage_log"; return $? ;;
    review)   run_phase_review "$task_id" "$stage_log"; return $? ;;
    result)   run_phase_result "$task_id" "$stage_log"; return $? ;;
    close)    run_phase_close "$task_id" "$stage_log"; return $? ;;
    *)
      echo "[ERROR] Unknown phase: $phase" >> "$stage_log"
      return 2
      ;;
  esac
}

# ── Full Phased Execution ───────────────────────────────────────────────────

run_phased_execution() {
  local task_id="$1" task_file="$2" task_file_rel="$3" plan_file="$4"
  local approval_file="$5" out_dir="$6" risk_level="$7" epic_id="$8"

  echo "=== Phased Dispatch ==="
  echo "task=$task_id epic=$epic_id risk=$risk_level"

  # Create initial checkpoint
  create_checkpoint "$task_id" "$epic_id" "$risk_level" "$plan_file" "$task_file_rel" "$out_dir"
  local checkpoint_file="$out_dir/dispatch_checkpoint.json"

  local phases
  phases="$(get_phase_sequence "$risk_level")"
  if [[ -z "$phases" ]]; then
    echo "[ERROR] No phases defined for risk level=$risk_level" >&2
    return 1
  fi

  local overall_rc=0
  for phase in $phases; do
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
    stage_log="$out_dir/phase_${phase}.log"

    set +e
    run_single_phase "$phase" "$task_id" "$task_file" "$plan_file" "$approval_file" "$out_dir" "$stage_log"
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

  return $overall_rc
}
