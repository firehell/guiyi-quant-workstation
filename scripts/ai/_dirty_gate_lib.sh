#!/usr/bin/env bash
# WS-V2-006 G3: Dirty Workspace Gate
# Pre-dev scan of uncommitted changes classified as allowed/unknown/violation.
# Strict mode blocks unknown changes.
# Bypass: GUIYI_SKIP_DIRTY_GATE=1
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

get_allowed_patterns() {
  local task_file="$1"
  PYTHONPATH="$SCRIPT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}" python3 - "$task_file" <<'PY'
import json, sys
from pathlib import Path
from task_meta import parse_task_file
try:
    meta = parse_task_file(Path(sys.argv[1]))
    patterns = list(meta.allowed_paths) if meta.allowed_paths else []
    # Add default allowed patterns for AI workspace artifacts
    default_patterns = [".ai/**", "workstation/**", ".workbuddy/**", "**/__pycache__/**", "stubs/**"]
    for dp in default_patterns:
        if dp not in patterns:
            patterns.append(dp)
    print(json.dumps(patterns))
except Exception:
    print(json.dumps([]))
PY
}

get_forbidden_patterns() {
  local task_file="$1"
  PYTHONPATH="$SCRIPT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}" python3 - "$task_file" <<'PY'
import json, sys
from pathlib import Path
from task_meta import parse_task_file
try:
    meta = parse_task_file(Path(sys.argv[1]))
    patterns = list(meta.forbidden_paths) if meta.forbidden_paths else []
    print(json.dumps(patterns))
except Exception:
    print(json.dumps([]))
PY
}

_classify_path() {
  local path="$1" allowed_json="$2" forbidden_json="$3"

  python3 - "$path" "$allowed_json" "$forbidden_json" <<'PY'
import fnmatch
import json
import sys

path = sys.argv[1]
allowed = json.loads(sys.argv[2])
forbidden = json.loads(sys.argv[3])

# Forbidden takes precedence
for pattern in forbidden:
    if fnmatch.fnmatch(path, pattern):
        print("violation")
        raise SystemExit(0)

for pattern in allowed:
    if fnmatch.fnmatch(path, pattern):
        print("allowed")
        raise SystemExit(0)

print("unknown")
PY
}

check_dirty_workspace_gate() {
  local task_file="$1" repo_root="${2:-}"

  if [[ "${GUIYI_SKIP_DIRTY_GATE:-}" == "1" ]]; then
    echo "[SKIP] Dirty Workspace Gate: GUIYI_SKIP_DIRTY_GATE=1" >&2
    return 0
  fi

  if [[ -z "$repo_root" ]]; then
    repo_root="${REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
  fi

  local allowed_json forbidden_json
  allowed_json="$(get_allowed_patterns "$task_file" 2>/dev/null || echo '[]')"
  forbidden_json="$(get_forbidden_patterns "$task_file" 2>/dev/null || echo '[]')"

  # Get uncommitted changes: modified + untracked (excluding gitignore'd)
  local dirty_files
  dirty_files="$(cd "$repo_root" && git ls-files --modified --others --exclude-standard 2>/dev/null || true)"

  if [[ -z "$dirty_files" ]]; then
    echo "[OK] Dirty Workspace Gate: clean" >&2
    return 0
  fi

  local violations=()
  local unknowns=()
  local allowed_count=0

  while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    local classification
    classification="$(_classify_path "$f" "$allowed_json" "$forbidden_json" 2>/dev/null || echo "unknown")"
    case "$classification" in
      violation) violations+=("$f") ;;
      unknown) unknowns+=("$f") ;;
      allowed) ((allowed_count++)) ;;
    esac
  done <<< "$dirty_files"

  local failed=false

  if [[ ${#violations[@]} -gt 0 ]]; then
    echo "Dirty Workspace Gate: VIOLATION — forbidden paths modified:" >&2
    for f in "${violations[@]}"; do
      echo "  - $f" >&2
    done
    failed=true
  fi

  if [[ ${#unknowns[@]} -gt 0 ]]; then
    echo "Dirty Workspace Gate: UNKNOWN changes detected (strict mode):" >&2
    for f in "${unknowns[@]}"; do
      echo "  - $f" >&2
    done
    failed=true
  fi

  if [[ "$failed" == true ]]; then
    local dirty_count
    dirty_count="$(echo "$dirty_files" | wc -l | tr -d ' ')"
    echo "Dirty Workspace Gate: blocked dirty=$dirty_count allowed=$allowed_count violation=${#violations[@]} unknown=${#unknowns[@]}" >&2
    return 9
  fi

  echo "[OK] Dirty Workspace Gate: $(echo "$dirty_files" | wc -l | tr -d ' ') uncommitted change(s), all allowed" >&2
  return 0
}
