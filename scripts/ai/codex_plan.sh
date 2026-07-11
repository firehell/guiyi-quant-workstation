#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
OUT_ROOT="$REPO_ROOT/.ai/results"
source "$SCRIPT_DIR/_work_level_lib.sh"
TASK_ID=""; PROMPT_FILE=""; GATE_ONLY=false
usage() { echo "Usage: scripts/ai/codex_plan.sh --task <TASK_ID> [--prompt <file>] [--gate-only]"; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --task) TASK_ID="${2:-}"; shift 2;;
    --prompt) PROMPT_FILE="${2:-}"; shift 2;;
    --gate-only) GATE_ONLY=true; shift;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2;;
  esac
done
[[ -n "$TASK_ID" ]] || { usage >&2; exit 2; }
cd "$REPO_ROOT"
TASK_FILE="$(resolve_task_file "$TASK_ID" || true)"
[[ -n "$TASK_FILE" ]] || { echo "TASK not found: $TASK_ID" >&2; exit 4; }
command -v codex >/dev/null 2>&1 || { echo "codex CLI not found" >&2; exit 3; }
check_issue_gate "$TASK_FILE" || exit $?
WORK_LEVEL="$(extract_work_level "$TASK_FILE")"
if [[ "$WORK_LEVEL" != "L0" ]]; then
  check_worktree_gate "$TASK_FILE" || exit $?
fi
ISSUE="$(extract_task_meta_field "$TASK_FILE" "GitHub Issue")"
if [[ "$GATE_ONLY" == true ]]; then
  echo "[OK] Gate checks passed for task=$TASK_ID level=$WORK_LEVEL issue=${ISSUE:-none}"
  exit 0
fi
OUT_DIR="$OUT_ROOT/$TASK_ID"; mkdir -p "$OUT_DIR"
PLAN_FILE="$OUT_DIR/plan_result.md"
PROMPT_TMP="$(mktemp)"; DIFF_BEFORE="$(mktemp)"
trap 'rm -f "$PROMPT_TMP" "$DIFF_BEFORE"' EXIT
git diff --binary HEAD > "$DIFF_BEFORE"
{
  echo "你是 Codex CLI，处于只读 Plan 模式。不得修改仓库文件。"
  echo "请基于以下完整事实输出实施 Plan，并明确范围、Gate、测试和风险。"
  echo; echo "===== AGENTS.md ====="; cat AGENTS.md
  echo; echo "===== CODEBUDDY.md ====="; cat CODEBUDDY.md
  echo; echo "===== TASK: $TASK_FILE ====="; cat "$TASK_FILE"
  echo; echo "===== CURRENT GIT STATUS ====="; git status --short --branch
  if [[ -n "$PROMPT_FILE" ]]; then
    [[ -f "$PROMPT_FILE" ]] || { echo "Prompt file not found: $PROMPT_FILE" >&2; exit 4; }
    echo; echo "===== EXTRA PLAN PROMPT ====="; cat "$PROMPT_FILE"
  fi
} > "$PROMPT_TMP"
echo "[PLAN] task=$TASK_ID issue=$ISSUE output=$PLAN_FILE"
codex exec -s read-only "$(cat "$PROMPT_TMP")" > "$PLAN_FILE" 2> "$OUT_DIR/plan.err" || {
  echo "Codex Plan failed; see $OUT_DIR/plan.err" >&2; exit 1;
}
cmp -s "$DIFF_BEFORE" <(git diff --binary HEAD) || {
  echo "Read-only Gate failed: tracked git diff changed during Plan" >&2; exit 6;
}
echo "[OK] Plan generated without tracked repository changes: $PLAN_FILE"
