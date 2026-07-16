#!/usr/bin/env bash
approval_sha256() { shasum -a 256 "$1" | awk '{print $1}'; }
approval_json_value() {
  python3 - "$1" "$2" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh: value=json.load(fh).get(sys.argv[2], "")
print(json.dumps(value, ensure_ascii=False) if isinstance(value, (dict,list)) else value)
PY
}
extract_task_field() {
  local value
  if declare -F extract_task_meta_field >/dev/null 2>&1; then
    value="$(extract_task_meta_field "$1" "$2")"
    if [[ -n "$value" ]]; then
      printf '%s\n' "$value"
      return 0
    fi
  fi
  value="$(sed -nE "/^## 0\\./,/^## /s/^\\| $2 \\| (.*) \\|$/\\1/p" "$1" | head -1)"
  if [[ -n "$value" ]]; then
    printf '%s\n' "$value"
    return 0
  fi
}
check_branch() {
  local current expected
  current="$(git branch --show-current)"; expected="$(extract_task_field "$1" Branch)"
  [[ -n "$current" && "$current" != main && "$current" != master ]] || {
    echo "Branch Gate failed: main/master or detached HEAD is not allowed" >&2; return 1;
  }
  [[ -n "$expected" && "$current" == "$expected" ]] || {
    echo "Branch Gate failed: current=$current expected=${expected:-missing}" >&2; return 1;
  }
}
generate_approval() {
  local task_id="$1" task_file="$2" plan_file="$3" approval_file="$4"
  local issue branch task_sha plan_sha approved_at head approval_scope risk_level
  issue="$(extract_task_field "$task_file" "GitHub Issue")"; branch="$(extract_task_field "$task_file" Branch)"
  task_sha="$(approval_sha256 "$task_file")"; plan_sha="$(approval_sha256 "$plan_file")"
  approved_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"; head="$(git rev-parse HEAD)"
  # V2: extract approval_scope and risk_level if present
  approval_scope="$(extract_task_field "$task_file" "Approval Scope" 2>/dev/null || echo "")"
  risk_level="$(extract_task_field "$task_file" "Risk Level" 2>/dev/null || echo "")"
  # Normalize V2 fields
  if [[ -z "$approval_scope" ]] || [[ "$approval_scope" == "-" ]] || [[ "$approval_scope" == "N/A" ]]; then
    approval_scope="plan,code"
  fi
  if [[ -z "$risk_level" ]] || [[ "$risk_level" == "-" ]] || [[ "$risk_level" == "N/A" ]]; then
    risk_level="R3"
  fi
  mkdir -p "$(dirname "$approval_file")"
  TASK_ID_JSON="$task_id" ISSUE_JSON="$issue" TASK_FILE_JSON="$task_file" TASK_SHA_JSON="$task_sha" \
  PLAN_FILE_JSON="$plan_file" PLAN_SHA_JSON="$plan_sha" BRANCH_JSON="$branch" \
  APPROVED_AT_JSON="$approved_at" HEAD_JSON="$head" \
  APPROVAL_SCOPE_JSON="$approval_scope" RISK_LEVEL_JSON="$risk_level" \
  python3 - "$approval_file" <<'PY'
import json, os, subprocess, sys
import hashlib
status=subprocess.run(["git","status","--porcelain"],text=True,capture_output=True,check=True).stdout
paths=[line[3:] for line in status.splitlines() if len(line)>3]
hashes={}
for path in paths:
    try:
        with open(path,"rb") as fh: hashes[path]=hashlib.sha256(fh.read()).hexdigest()
    except (FileNotFoundError, IsADirectoryError, PermissionError): hashes[path]=""
# Parse approval_scope list from comma-separated string
scope_raw = os.environ.get("APPROVAL_SCOPE_JSON", "plan,code")
approval_scope = [s.strip() for s in scope_raw.split(",") if s.strip()]
payload={"schema_version":2,"task_id":os.environ["TASK_ID_JSON"],"issue":os.environ["ISSUE_JSON"],
"task_file":os.environ["TASK_FILE_JSON"],"task_sha256":os.environ["TASK_SHA_JSON"],
"approved_task_sha256":os.environ["TASK_SHA_JSON"],"current_task_sha256":os.environ["TASK_SHA_JSON"],
"plan_file":os.environ["PLAN_FILE_JSON"],"plan_sha256":os.environ["PLAN_SHA_JSON"],
"approval_scope":approval_scope,"risk_level":os.environ.get("RISK_LEVEL_JSON","R3"),
"approved_branch":os.environ["BRANCH_JSON"],"approved_at":os.environ["APPROVED_AT_JSON"],
"approved_by":"local-user","head_commit":os.environ["HEAD_JSON"],
"pre_existing_changes":paths,"pre_existing_sha256":hashes}
if os.environ.get("PRODUCTION_WRITE_APPROVED") == "true":
    payload["production_write_approved"] = True
with open(sys.argv[1],"w",encoding="utf-8") as fh: json.dump(payload,fh,ensure_ascii=False,indent=2); fh.write("\n")
PY
}
update_approval_current_task_sha() {
  local approval_file="$1" task_file="$2" transition_json="${3:-}"
  local current_task_sha
  current_task_sha="$(approval_sha256 "$task_file")"
  CURRENT_TASK_SHA_JSON="$current_task_sha" TRANSITION_JSON="$transition_json" python3 - "$approval_file" <<'PY'
import json, os, sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
data["current_task_sha256"] = os.environ["CURRENT_TASK_SHA_JSON"]
if os.environ.get("TRANSITION_JSON"):
    try:
        data["approval_status_transition"] = json.loads(os.environ["TRANSITION_JSON"])
    except json.JSONDecodeError:
        data["approval_status_transition"] = os.environ["TRANSITION_JSON"]
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}
detect_plan_change() {
  local approval_file="$1" plan_file="${2:-}" approved current
  [[ -f "$approval_file" ]] || return 1
  [[ -n "$plan_file" ]] || plan_file="$(approval_json_value "$approval_file" plan_file)"
  [[ -f "$plan_file" ]] || return 1
  approved="$(approval_json_value "$approval_file" plan_sha256)"; current="$(approval_sha256 "$plan_file")"
  [[ -n "$approved" && "$approved" == "$current" ]]
}
verify_approval() {
  local approval_file="$1" task_id="$2" task_file="$3" plan_file="${4:-}"
  [[ -f "$approval_file" ]] || { echo "Approval missing: $approval_file" >&2; return 1; }
  local schema_ver
  schema_ver="$(approval_json_value "$approval_file" schema_version)"
  # Support both v1 and v2 approval records
  if [[ "$schema_ver" != "1" && "$schema_ver" != "2" ]]; then
    echo "Approval invalid: unsupported schema_version=$schema_ver" >&2; return 1;
  fi
  [[ "$(approval_json_value "$approval_file" task_id)" == "$task_id" ]] || return 1
  [[ "$(approval_json_value "$approval_file" task_file)" == "$task_file" ]] || return 1
  check_branch "$task_file" || return 1
  detect_plan_change "$approval_file" "$plan_file" || { echo "Approval invalid: Plan hash changed" >&2; return 1; }
  # V2: also check TASK SHA256 consistency (WS-V2-001 C1 fix)
  local approved_task_sha current_task_sha current_allowed_sha
  approved_task_sha="$(approval_json_value "$approval_file" task_sha256)"
  current_allowed_sha="$(approval_json_value "$approval_file" current_task_sha256)"
  current_task_sha="$(approval_sha256 "$task_file")"
  if [[ -n "$current_allowed_sha" ]]; then
    if [[ "$current_allowed_sha" != "$current_task_sha" ]]; then
      echo "Approval invalid: TASK file changed since approval (approved_current=$current_allowed_sha current=$current_task_sha)" >&2; return 1;
    fi
  elif [[ -n "$approved_task_sha" && "$approved_task_sha" != "$current_task_sha" ]]; then
    echo "Approval invalid: TASK file changed since approval (approved=$approved_task_sha current=$current_task_sha)" >&2; return 1;
  fi
}

# ── V3: Atomic operation-level approval (WS-V2-003) ─────────────────────────

GENERATE_APPROVAL_V3_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/approval.sh"

generate_approval_v3() {
  local task_id="$1" epic_id="$2" task_file="$3" plan_file="$4" approval_file="$5"
  local approved_ops="${6:-AUDIT,DEV}" approver="${7:-local-user}" expires_at="${8:-}" one_time="${9:-false}"
  local approval_scope="${10:-}" forbidden_ops="${11:-}"

  local args=(
    create
    --task-id "$task_id"
    --epic-id "$epic_id"
    --plan-file "$plan_file"
    --task-file "$task_file"
    --approved-ops "$approved_ops"
    --approval-file "$approval_file"
    --repo-root "$(git -C "$(dirname "$task_file")" rev-parse --show-toplevel 2>/dev/null || pwd)"
    --approver "$approver"
    --json
  )

  [[ "$one_time" == "true" ]] && args+=(--one-time)
  [[ -n "$expires_at" ]] && args+=(--expires-at "$expires_at")
  [[ -n "$approval_scope" && "$approval_scope" != "-" ]] && args+=(--approval-scope "$approval_scope")
  [[ -n "$forbidden_ops" && "$forbidden_ops" != "-" ]] && args+=(--forbidden-ops "$forbidden_ops")

  "$GENERATE_APPROVAL_V3_SCRIPT" "${args[@]}"
}

verify_approval_v3() {
  local approval_file="$1" task_id="$2" task_file="$3" plan_file="$4" operation="$5"
  local repo_root="${6:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
  local strict_head="${7:-false}"

  [[ -f "$approval_file" ]] || { echo "Approval missing: $approval_file" >&2; return 1; }

  local schema_ver
  schema_ver="$(approval_json_value "$approval_file" schema_version)"

  # ── V2 backward compat: if schema_version < 3, fall back to V2 verify ──
  if [[ "$schema_ver" != "3" ]]; then
    echo "[V3→V2] approval $approval_file is schema_version=$schema_ver, using legacy V2 verify (no operation-level check)" >&2
    verify_approval "$approval_file" "$task_id" "$task_file" "$plan_file"
    return $?
  fi

  local args=(
    verify
    --approval-file "$approval_file"
    --task-id "$task_id"
    --task-file "$task_file"
    --plan-file "$plan_file"
    --operation "$operation"
    --repo-root "$repo_root"
    --json
  )

  [[ "$strict_head" == "true" ]] && args+=(--strict-head)

  local result result_rc
  set +e
  result="$("$GENERATE_APPROVAL_V3_SCRIPT" "${args[@]}" 2>&1)"
  result_rc=$?
  set -e

  if [[ $result_rc -ne 0 ]]; then
    echo "$result" >&2
    return 1
  fi

  # Check JSON result for REJECT status
  local status
  status="$(echo "$result" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))' 2>/dev/null || echo "")"
  if [[ "$status" == "REJECT" ]]; then
    echo "$result" >&2
    return 1
  fi

  return 0
}
