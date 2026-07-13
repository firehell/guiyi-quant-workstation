#!/usr/bin/env bash
# WS-V2-006 G4: Scope Report Gate
# Post-dev git diff against merge-base to detect out-of-scope file modifications.
# Generates scope_report.json; blocks subsequent phases when violations found.
# Bypass: GUIYI_SKIP_SCOPE_GATE=1
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

generate_scope_report() {
  local task_file="$1" repo_root="$2" out_dir="$3"

  PYTHONPATH="$SCRIPT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}" python3 - "$task_file" "$repo_root" "$out_dir" <<'PY'
import fnmatch
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

task_path = Path(sys.argv[1])
repo_root = Path(sys.argv[2])
out_dir = Path(sys.argv[3])

# --- Load allowed/forbidden patterns from task metadata ---
try:
    from task_meta import parse_task_file
    meta = parse_task_file(task_path)
    allowed_patterns = list(meta.allowed_paths) if meta.allowed_paths else []
    forbidden_patterns = list(meta.forbidden_paths) if meta.forbidden_paths else []
    base_branch = meta.base_branch
    task_id_from_meta = meta.task_id
except Exception:
    allowed_patterns = []
    forbidden_patterns = []
    base_branch = "main"
    task_id_from_meta = task_path.stem

# Add default AI-workspace scoped paths
default_allowed = [".ai/**", "workstation/**", ".workbuddy/**", "**/__pycache__/**"]
for dp in default_allowed:
    if dp not in allowed_patterns:
        allowed_patterns.append(dp)

# Get the merge-base
try:
    merge_base = subprocess.run(
        ["git", "-C", str(repo_root), "merge-base", base_branch, "HEAD"],
        capture_output=True, text=True, check=True
    ).stdout.strip()
    if not merge_base:
        merge_base = "HEAD~1"
except subprocess.CalledProcessError:
    merge_base = "HEAD~1"

# Get changed files between merge-base and current HEAD
try:
    changed = subprocess.run(
        ["git", "-C", str(repo_root), "diff", "--name-only", merge_base, "HEAD"],
        capture_output=True, text=True, check=True
    ).stdout.strip().splitlines()
except subprocess.CalledProcessError:
    changed = []

changed = [f for f in changed if f]

# Classify each changed file
allowed_files = []
violation_files = []
unknown_files = []

for f in changed:
    for pattern in forbidden_patterns:
        if fnmatch.fnmatch(f, pattern):
            violation_files.append(f)
            break
    else:
        for pattern in allowed_patterns:
            if fnmatch.fnmatch(f, pattern):
                allowed_files.append(f)
                break
        else:
            unknown_files.append(f)

report = {
    "schema_version": "1.0",
    "task_id": task_id_from_meta,
    "base_branch": base_branch,
    "merge_base": merge_base,
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "total_changed": len(changed),
    "allowed_count": len(allowed_files),
    "violation_count": len(violation_files),
    "unknown_count": len(unknown_files),
    "allowed_files": [{"path": f, "classification": "allowed"} for f in allowed_files],
    "violation_files": [{"path": f, "classification": "violation"} for f in violation_files],
    "unknown_files": [{"path": f, "classification": "unknown"} for f in unknown_files],
    "ok": len(violation_files) == 0,
}

out_dir.mkdir(parents=True, exist_ok=True)
report_path = out_dir / "scope_report.json"
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

# Print the report JSON to stdout
print(json.dumps(report, ensure_ascii=False))
PY
}

check_scope_gate() {
  local task_id="$1" repo_root="$2" out_dir="$3" task_file="${4:-}"

  if [[ "${GUIYI_SKIP_SCOPE_GATE:-}" == "1" ]]; then
    echo "[SKIP] Scope Report Gate: GUIYI_SKIP_SCOPE_GATE=1" >&2
    return 0
  fi

  if [[ -z "$repo_root" ]]; then
    repo_root="${REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
  fi

  if [[ -z "$out_dir" ]]; then
    out_dir="${REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}/.ai/results/${task_id}"
  fi

  local task_file_path="$task_file"
  if [[ -z "$task_file_path" ]]; then
    task_file_path="$(find_task_file_for_id "$task_id" 2>/dev/null || echo "")"
  fi

  if [[ ! -f "$task_file_path" ]]; then
    echo "[WARN] Scope Report Gate: cannot find task file for $task_id, skipping" >&2
    return 0
  fi

  local report
  report="$(generate_scope_report "$task_file_path" "$repo_root" "$out_dir" 2>/dev/null)" || {
    echo "Scope Report Gate: failed to generate report" >&2
    return 9
  }

  local ok
  ok="$(python3 -c "import json,sys; print('true' if json.loads(sys.stdin.read()).get('ok',False) else 'false')" <<< "$report" 2>/dev/null || echo "false")"

  if [[ "$ok" != "true" ]]; then
    local violations
    violations="$(python3 -c "
import json,sys
r = json.loads(sys.stdin.read())
for f in r.get('violation_files', []):
    print(f['path'])
" <<< "$report" 2>/dev/null)"
    echo "Scope Report Gate: violations detected:" >&2
    while IFS= read -r v; do
      [[ -n "$v" ]] && echo "  - $v" >&2
    done <<< "$violations"
    echo "Scope Report Gate: report=$out_dir/scope_report.json" >&2
    return 9
  fi

  echo "[OK] Scope Report Gate: clean ($(python3 -c "import json,sys; r=json.loads(sys.stdin.read()); print(r['total_changed'])" <<< "$report" 2>/dev/null || echo '?') files)" >&2
  return 0
}

find_task_file_for_id() {
  local task_id="$1" repo_root candidate
  repo_root="${REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
  for candidate in ".ai/tasks/${task_id}.md" "docs/tasks/${task_id}.md"; do
    if [[ -f "$repo_root/$candidate" ]]; then
      printf '%s\n' "$repo_root/$candidate"
      return 0
    fi
  done
  return 1
}
