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
  sed -nE "/^## 0\\./,/^## /s/^\\| $2 \\| (.*) \\|$/\\1/p" "$1" | head -1
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
  local approved_task_sha current_task_sha
  approved_task_sha="$(approval_json_value "$approval_file" task_sha256)"
  current_task_sha="$(approval_sha256 "$task_file")"
  if [[ -n "$approved_task_sha" && "$approved_task_sha" != "$current_task_sha" ]]; then
    echo "Approval invalid: TASK file changed since approval (approved=$approved_task_sha current=$current_task_sha)" >&2; return 1;
  fi
}
