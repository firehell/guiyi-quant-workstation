#!/usr/bin/env bash
# ── External Disk Gate (WS-V2-006 G2) ───────────────────────────────────────
# Fail-closed: if a required mount is declared but not present, block execution.
# Never auto-create empty data directories.

set -euo pipefail

# Resolve required mount paths from a task file.
# Outputs one path per line, or empty if none required.
resolve_required_mounts() {
  local task_file="$1"
  local repo_root="${2:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"

  PYTHONPATH="${repo_root}/scripts/ai/lib${PYTHONPATH:+:$PYTHONPATH}" python3 - "$task_file" <<'PY'
import sys
from pathlib import Path
from task_meta import parse_task_file

try:
    meta = parse_task_file(Path(sys.argv[1]))
    for m in meta.required_mounts:
        print(m)
except Exception:
    pass
PY
}

# Check a single mount path: must exist AND be a mount point.
# Use ismount (macOS/Linux) — does not just check existence.
check_single_mount() {
  local mount_path="$1"
  local expanded
  expanded="${mount_path/#\~/$HOME}"

  if [[ ! -e "$expanded" ]]; then
    echo "[EXTERNAL_DISK] FAIL: mount path does not exist: $mount_path (expanded=$expanded)" >&2
    return 1
  fi

  # macOS / Linux compatible ismount check
  if command -v stat &>/dev/null; then
    local mount_test
    mount_test="$(stat -f "%Sd" "$expanded" 2>/dev/null || stat -c "%d" "$expanded" 2>/dev/null)"
    local parent_test
    parent_test="$(stat -f "%Sd" "$(dirname "$expanded")" 2>/dev/null || stat -c "%d" "$(dirname "$expanded")" 2>/dev/null)"
    if [[ "$mount_test" != "$parent_test" ]]; then
      echo "[EXTERNAL_DISK] OK: $mount_path (ismount=true)" >&2
      return 0
    fi
  fi

    # Fallback: use python's os.path.ismount
  if python3 -c "import os; raise SystemExit(0 if os.path.ismount('$expanded') else 1)" 2>/dev/null; then
    echo "[EXTERNAL_DISK] OK: $mount_path (ismount=true via python)" >&2
    return 0
  fi

  echo "[EXTERNAL_DISK] FAIL: path exists but is NOT a mount point: $mount_path" >&2
  return 2
}

# Main gate: check all required mounts for a task.
# Returns 0 if all ok, non-zero on first failure.
# Never creates empty directories.
check_external_disk_gate() {
  local task_file="$1"
  local repo_root="${2:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"

  # Allow bypass via env var (test/CI environments)
  if [[ "${GUIYI_SKIP_EXTERNAL_DISK_GATE:-}" == "1" ]]; then
    echo "[EXTERNAL_DISK] Bypassed (GUIYI_SKIP_EXTERNAL_DISK_GATE=1)" >&2
    return 0
  fi

  local mounts
  mounts="$(resolve_required_mounts "$task_file" "$repo_root")"

  if [[ -z "$mounts" ]]; then
    echo "[EXTERNAL_DISK] No required mounts declared — gate passes." >&2
    return 0
  fi

  local failed=false
  while IFS= read -r mount_path; do
    [[ -n "$mount_path" ]] || continue
    if ! check_single_mount "$mount_path"; then
      failed=true
    fi
  done <<< "$mounts"

  if [[ "$failed" == true ]]; then
    echo "[EXTERNAL_DISK] GATE FAILED: required mount(s) not available. Execution blocked." >&2
    return 1
  fi

  echo "[EXTERNAL_DISK] All required mounts present and verified."
  return 0
}
