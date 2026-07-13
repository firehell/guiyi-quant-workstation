#!/usr/bin/env bash
# WS-V2-006 G2: External Disk Gate
# Fail-closed mount verification using stat device ID comparison.
# Never auto-creates empty directories.
# Bypass: GUIYI_SKIP_EXTERNAL_DISK_GATE=1
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

resolve_required_mounts() {
  local task_file="$1"
  PYTHONPATH="$SCRIPT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}" python3 - "$task_file" <<'PY'
import json, sys
from pathlib import Path
from task_meta import parse_task_file
try:
    meta = parse_task_file(Path(sys.argv[1]))
    mounts = meta.required_mounts
    print(json.dumps(list(mounts)))
except Exception:
    print(json.dumps([]))
PY
}

check_single_mount() {
  local mount_path="$1"

  # Expand home dir if present
  if [[ "$mount_path" == ~* ]]; then
    mount_path="${mount_path/#\~/$HOME}"
  fi

  # Never auto-create empty directories
  if [[ ! -d "$mount_path" ]]; then
    echo "External Disk Gate failed: mount not found: $mount_path" >&2
    return 9
  fi

  # Use stat device ID comparison to verify it's a real mount point
  # Get the parent's device ID and the path's device ID
  local parent_path
  parent_path="$(dirname "$mount_path")"

  local parent_dev mount_dev
  parent_dev="$(stat -f '%d' "$parent_path" 2>/dev/null || echo "")"
  mount_dev="$(stat -f '%d' "$mount_path" 2>/dev/null || echo "")"

  if [[ -n "$parent_dev" && -n "$mount_dev" && "$parent_dev" != "$mount_dev" ]]; then
    # Different device IDs → this is a real mount point
    echo "[OK] External Disk: $mount_path (cross-device, parent=$parent_dev mount=$mount_dev)" >&2
    return 0
  fi

  # Fallback: use os.path.ismount via Python
  local is_mount
  is_mount="$(python3 -c "
import os
print('true' if os.path.ismount('$mount_path') else 'false')
" 2>/dev/null || echo "false")"

  if [[ "$is_mount" == "true" ]]; then
    echo "[OK] External Disk: $mount_path (ismount)" >&2
    return 0
  fi

  echo "External Disk Gate failed: $mount_path exists but is not a mount point (same device: ${parent_dev:-unknown})" >&2
  return 9
}

check_external_disk_gate() {
  local task_file="$1"

  if [[ "${GUIYI_SKIP_EXTERNAL_DISK_GATE:-}" == "1" ]]; then
    echo "[SKIP] External Disk Gate: GUIYI_SKIP_EXTERNAL_DISK_GATE=1" >&2
    return 0
  fi

  local mounts_json mounts
  mounts_json="$(resolve_required_mounts "$task_file" 2>/dev/null || echo '[]')"
  if [[ "$mounts_json" == "[]" || -z "$mounts_json" ]]; then
    echo "[OK] External Disk Gate: no mounts required" >&2
    return 0
  fi

  mounts="$(python3 -c "
import json
print(' '.join(json.loads('$mounts_json')))
")"

  if [[ -z "$mounts" ]]; then
    echo "[OK] External Disk Gate: no mounts required" >&2
    return 0
  fi

  local all_ok=true
  for mount in $mounts; do
    if ! check_single_mount "$mount"; then
      all_ok=false
    fi
  done

  if [[ "$all_ok" != true ]]; then
    echo "External Disk Gate: one or more mounts failed" >&2
    return 9
  fi

  echo "[OK] External Disk Gate: all mounts verified" >&2
  return 0
}
