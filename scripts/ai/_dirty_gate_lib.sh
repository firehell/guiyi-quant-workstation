#!/usr/bin/env bash
# ── Dirty Workspace Gate (WS-V2-006 G3) ──────────────────────────────────────
# Pre-dev: scan workspace for uncommitted changes.
# Classifies changes into: allowed (within declared allowed_paths),
# unknown (not matching any allowed pattern), or violation (in forbidden_paths).
# Blocks execution when violations or unknown changes are present.

set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"

# Extract allowed_paths list from a task file (Python/TaskMeta).
get_allowed_patterns() {
  local task_file="$1"
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$REPO_ROOT/scripts/ai/lib${PYTHONPATH:+:$PYTHONPATH}" python3 - "$task_file" <<'PY'
import json, sys
from pathlib import Path
from task_meta import parse_task_file

try:
    meta = parse_task_file(Path(sys.argv[1]))
    print(json.dumps(list(meta.allowed_paths)))
except Exception:
    print(json.dumps([]))
PY
}

# Extract forbidden_paths list from a task file.
get_forbidden_patterns() {
  local task_file="$1"
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$REPO_ROOT/scripts/ai/lib${PYTHONPATH:+:$PYTHONPATH}" python3 - "$task_file" <<'PY'
import json, sys
from pathlib import Path
from task_meta import parse_task_file

try:
    meta = parse_task_file(Path(sys.argv[1]))
    print(json.dumps(list(meta.forbidden_paths)))
except Exception:
    print(json.dumps([]))
PY
}

# Classify a single file path against allowed and forbidden glob patterns.
# Returns: "allowed" | "violation" | "unknown"
_classify_path() {
  local file_path="$1"
  local allowed_json="$2"
  local forbidden_json="$3"

  PYTHONDONTWRITEBYTECODE=1 python3 - "$file_path" "$allowed_json" "$forbidden_json" <<'PY'
import fnmatch, json, os, sys

file_path = sys.argv[1]
allowed = json.loads(sys.argv[2])
forbidden = json.loads(sys.argv[3])

# Check forbidden first (takes precedence)
for pattern in forbidden:
    if pattern and fnmatch.fnmatch(file_path, pattern):
        print("violation")
        raise SystemExit(0)

# Check allowed
for pattern in allowed:
    if pattern and fnmatch.fnmatch(file_path, pattern):
        print("allowed")
        raise SystemExit(0)

print("unknown")
PY
}

# Main gate: scan dirty workspace, classify, and report.
# Returns 0 if clean or all changes are allowed.
# Returns 1 if violations or unknowns found.
check_dirty_workspace_gate() {
  local task_file="$1"
  local task_id="${2:-unknown}"
  local strict="${3:-true}"  # If true, unknown changes are blocking

  # Allow bypass via env var (test/CI environments)
  if [[ "${GUIYI_SKIP_DIRTY_GATE:-}" == "1" ]]; then
    echo "[DIRTY_GATE] Bypassed (GUIYI_SKIP_DIRTY_GATE=1)" >&2
    return 0
  fi

  local allowed_json forbidden_json
  allowed_json="$(get_allowed_patterns "$task_file")"
  forbidden_json="$(get_forbidden_patterns "$task_file")"

  echo "[DIRTY_GATE] Scanning workspace for uncommitted changes..." >&2

  # Collect all modified/untracked files
  local changes
  changes="$(comm -23 \
    <(git -C "$REPO_ROOT" ls-files --modified --others --exclude-standard | sort) \
    <(sort /dev/null 2>/dev/null || true) \
    2>/dev/null || true)"

  # Also check staged changes
  local staged
  staged="$(git -C "$REPO_ROOT" diff --name-only --cached 2>/dev/null || true)"

  local all_changes
  all_changes="$(printf '%s\n%s\n' "$changes" "$staged" | sort -u | grep -v '^$' || true)"

  if [[ -z "$all_changes" ]]; then
    echo "[DIRTY_GATE] Workspace clean — gate passes."
    return 0
  fi

  local allowed_count=0 unknown_count=0 violation_count=0
  local report_lines=()

  while IFS= read -r file; do
    [[ -n "$file" ]] || continue
    local classification
    classification="$(_classify_path "$file" "$allowed_json" "$forbidden_json")"

    case "$classification" in
      allowed)
        allowed_count=$((allowed_count + 1))
        report_lines+=("  [ALLOWED]   $file")
        ;;
      violation)
        violation_count=$((violation_count + 1))
        report_lines+=("  [VIOLATION] $file (matches forbidden_paths)")
        ;;
      unknown)
        unknown_count=$((unknown_count + 1))
        report_lines+=("  [UNKNOWN]   $file (not in allowed_paths)")
        ;;
    esac
  done <<< "$all_changes"

  # Print report
  echo "[DIRTY_GATE] --- Dirty Workspace Report ---"
  echo "[DIRTY_GATE] task=$task_id"
  printf '%s\n' "${report_lines[@]}"
  echo "[DIRTY_GATE] Summary: allowed=$allowed_count unknown=$unknown_count violation=$violation_count"

  # Decide outcome
  if [[ $violation_count -gt 0 ]]; then
    echo "[DIRTY_GATE] FAIL: $violation_count file(s) violate forbidden_paths" >&2
    return 1
  fi

  if [[ "$strict" == true && $unknown_count -gt 0 ]]; then
    echo "[DIRTY_GATE] FAIL: $unknown_count unknown file(s) not in allowed_paths (strict mode)" >&2
    return 2
  fi

  if [[ "$strict" == false && $unknown_count -gt 0 ]]; then
    echo "[DIRTY_GATE] WARN: $unknown_count unknown file(s) — continuing (non-strict mode)"
  fi

  echo "[DIRTY_GATE] Gate passes — all changes are allowed."
  return 0
}
