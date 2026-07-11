#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
source "$SCRIPT_DIR/_work_level_lib.sh"

TASK_ID=""
FORCE=false

usage() {
  echo "Usage: scripts/ai/remove_task_worktree.sh --task <TASK_ID> [--force]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task) TASK_ID="${2:-}"; shift 2 ;;
    --force) FORCE=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$TASK_ID" ]] || { usage >&2; exit 2; }
cd "$REPO_ROOT"

TASK_FILE="$(resolve_task_file "$TASK_ID" || true)"
WT_PATH=""
if [[ -n "$TASK_FILE" ]] && WT_PATH="$(extract_worktree_path "$TASK_FILE" 2>/dev/null || true)"; then
  :
else
  slug="$(task_slug_from_id "$TASK_ID")"
  WT_PATH="$(resolve_worktree_root "$REPO_ROOT")/${slug}"
fi

[[ -e "$WT_PATH" ]] || { echo "Worktree path not found: $WT_PATH" >&2; exit 4; }

if [[ "$FORCE" != true ]]; then
  if [[ -n "$(git -C "$WT_PATH" status --porcelain 2>/dev/null || true)" ]]; then
    echo "Refusing to remove dirty worktree: $WT_PATH (use --force)" >&2
    exit 6
  fi
fi

git worktree remove "$WT_PATH" --force 2>/dev/null || git worktree remove "$WT_PATH" || {
  echo "Failed to remove worktree: $WT_PATH" >&2
  exit 1
}
echo "[OK] Removed worktree: $WT_PATH"
echo "[NOTE] Remote branch not deleted; delete manually if needed."
