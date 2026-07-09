#!/usr/bin/env bash
# Codex read-only plan: inspects files and proposes work; must NOT modify repository files.
# Fixed output:
#   plan:  .ai/results/<TASK_ID>/plan.md
#   log:   .ai/logs/<TASK_ID>/codex_plan.log
# scripts/ai/.out/ is only a temp dir and is NOT a formal deliverable.
#
# Gate policy (per TASK-2026-07-09-001 fix):
#   - Plan Mode is ALLOWED even if no GitHub Issue is linked (only a warning).
#   - Dev Mode requires a linked GitHub Issue (handled in codex_dev.sh).
#   - push / PR / merge / deploy requires a linked GitHub Issue (handled elsewhere).
set -euo pipefail

TASK_FILE="${1:-}"

if [ -z "$TASK_FILE" ]; then
  echo "Usage: scripts/ai/codex_plan.sh <task_file>" >&2
  echo "Optional: TASK_ID=<id> scripts/ai/codex_plan.sh <task_file>" >&2
  exit 1
fi

if [ ! -f "$TASK_FILE" ]; then
  echo "Task file not found: $TASK_FILE" >&2
  exit 1
fi

if ! command -v codex >/dev/null 2>&1; then
  echo "codex CLI not found in PATH" >&2
  exit 1
fi

GIT_ROOT="$(git rev-parse --show-toplevel)"
cd "$GIT_ROOT"

# Default TASK_ID from filename if not provided.
if [ -z "${TASK_ID:-}" ]; then
  TASK_ID="$(basename "$TASK_FILE" | sed -E 's/\.md$//')"
fi

RESULT_DIR=".ai/results/${TASK_ID}"
LOG_DIR=".ai/logs/${TASK_ID}"
mkdir -p "$RESULT_DIR" "$LOG_DIR"

PLAN_FILE="${RESULT_DIR}/plan.md"
LOG_FILE="${LOG_DIR}/codex_plan.log"

# --- GitHub Issue linkage check (warning only for plan mode) ---
# Only a concrete Issue number/link counts as "linked". Negation contexts
# (e.g. "未关联 GitHub Issue", "no issue", "without issue") must NOT be
# treated as linked; they fall through to the [WARN] branch.
#
# Linked patterns (positive):
#   GitHub Issue: #123 | Issue: #123 | 关联 Issue: #123 | GH-123 | /issues/123
LINKED_REF="$(grep -inE '(github\s+issue|关联\s*issue|issue)\s*[:#]\s*#?[0-9]+|GH-[0-9]+|/issues/[0-9]+' "$TASK_FILE" 2>/dev/null | grep -viE '未关联|不关联|no issue|without issue|not linked|未链接' | head -1 || true)"

if [ -z "$LINKED_REF" ]; then
  echo "[WARN] No GitHub Issue linked in task file (or only negation text found). Plan Mode is allowed; Dev Mode will be blocked until an Issue is linked (or you pass explicit authorization)." | tee "$LOG_FILE"
else
  echo "[INFO] GitHub Issue reference found: ${LINKED_REF}" | tee "$LOG_FILE"
fi

{
  echo "Running Codex read-only plan"
  echo "Repository: $GIT_ROOT"
  echo "Task: $TASK_FILE"
  echo "TASK_ID: $TASK_ID"
  echo "Plan output: $PLAN_FILE"
  echo "Log: $LOG_FILE"
  echo
  echo "Working tree BEFORE plan:"
  git status --short --branch
  echo
} | tee -a "$LOG_FILE"

# Run Codex in read-only (sandbox read-only) mode.
# Plan must not modify files; if Codex tries, the sandbox blocks it.
set +e
codex exec --sandbox read-only --ephemeral --output-last-message "$PLAN_FILE" - <"$TASK_FILE" >"${LOG_DIR}/codex_stdout.log" 2>&1
CODEX_RC=$?
set -e

{
  echo
  echo "Codex exit code: $CODEX_RC"
  echo "Working tree AFTER plan:"
  git status --short --branch
  echo
} | tee -a "$LOG_FILE"

# Capture any Codex stdout/stderr into the main log for diagnostics.
if [ -s "${LOG_DIR}/codex_stdout.log" ]; then
  echo "--- Codex stdout/stderr (tail) ---" >>"$LOG_FILE"
  tail -40 "${LOG_DIR}/codex_stdout.log" >>"$LOG_FILE"
fi

# --- Failure detection: no plan.md generated or empty ---
if [ ! -s "$PLAN_FILE" ]; then
  echo "[ERR] Codex plan failed: no plan.md generated" | tee -a "$LOG_FILE"
  exit 2
fi

if [ "$CODEX_RC" -ne 0 ]; then
  echo "[ERR] Codex exited non-zero ($CODEX_RC); plan.md may be incomplete." | tee -a "$LOG_FILE"
  exit 2
fi

echo "[OK] Plan generated: $PLAN_FILE" | tee -a "$LOG_FILE"
exit 0
