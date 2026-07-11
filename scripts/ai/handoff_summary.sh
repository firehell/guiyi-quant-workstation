#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
source "$SCRIPT_DIR/_work_level_lib.sh"

TASK_ID=""
NEXT_ACTION=""

usage() {
  echo "Usage: scripts/ai/handoff_summary.sh --task <TASK_ID> [--next-action <text>]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task) TASK_ID="${2:-}"; shift 2 ;;
    --next-action) NEXT_ACTION="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$TASK_ID" ]] || { usage >&2; exit 2; }
cd "$REPO_ROOT"

TASK_FILE="$(resolve_task_file "$TASK_ID" || true)"
OUT_DIR=".ai/results/${TASK_ID}"
mkdir -p "$OUT_DIR"
OUT_FILE="$OUT_DIR/handoff.md"

level="L2"
status=""
if [[ -n "$TASK_FILE" ]]; then
  level="$(extract_work_level "$TASK_FILE")"
  status="$(extract_task_meta_field "$TASK_FILE" Status)"
fi
[[ -n "$NEXT_ACTION" ]] || NEXT_ACTION="manual review; see result bundle before merge"

branch="$(git branch --show-current 2>/dev/null || echo detached)"
toplevel="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
last_commit="$(git log -1 --oneline 2>/dev/null || echo none)"
git_status="$(git status --short --branch 2>/dev/null || true)"
diff_stat="$(git diff --stat HEAD 2>/dev/null || true)"
test_note="not run"
if [[ -f "$OUT_DIR/test_results.tsv" ]]; then
  test_note="$(tail -1 "$OUT_DIR/test_results.tsv" 2>/dev/null || echo recorded)"
fi

{
  echo "# Handoff — $TASK_ID"
  echo ""
  echo "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo ""
  echo "## 状态"
  echo "- Work Level: $level"
  echo "- TASK Status: ${status:-unknown}"
  echo "- Branch: \`$branch\`"
  echo "- Worktree: \`$toplevel\`"
  echo "- Last commit: $last_commit"
  echo ""
  echo "## Git status"
  echo '```'
  echo "$git_status"
  echo '```'
  echo ""
  echo "## Diff stat"
  echo '```'
  echo "$diff_stat"
  echo '```'
  echo ""
  echo "## Tests"
  echo "- $test_note"
  echo ""
  echo "## Next action"
  echo "- $NEXT_ACTION"
} > "$OUT_FILE"

echo "[OK] Handoff summary: $OUT_FILE"
