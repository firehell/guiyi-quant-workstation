#!/usr/bin/env bash
# Codex workspace-write development: may modify files in the working tree.
# Does NOT push, merge, tag, release, or deploy.
# Optional: set TASK_ID to write output under .ai/results/<TASK_ID>/
set -euo pipefail

TASK_FILE="${1:-}"
BRANCH_NAME="${2:-}"
ALLOW_NO_ISSUE=0

# Parse optional flags.
while [ $# -gt 0 ]; do
  case "$1" in
    --allow-no-issue)
      ALLOW_NO_ISSUE=1
      shift
      ;;
    --task-id)
      TASK_ID="${2:-}"
      shift 2
      ;;
    *)
      # positional: <task_file> <branch_name>
      if [ -z "${POS_TASK_FILE:-}" ]; then
        POS_TASK_FILE="$1"
      elif [ -z "${POS_BRANCH:-}" ]; then
        POS_BRANCH="$1"
      fi
      shift
      ;;
  esac
done

TASK_FILE="${POS_TASK_FILE:-$TASK_FILE}"
BRANCH_NAME="${POS_BRANCH:-$BRANCH_NAME}"

if [ -z "$TASK_FILE" ] || [ -z "$BRANCH_NAME" ]; then
  echo "Usage: scripts/ai/codex_dev.sh <task_file> <branch_name> [--allow-no-issue] [--task-id <id>]" >&2
  exit 1
fi

if [ ! -f "$TASK_FILE" ]; then
  echo "Task file not found: $TASK_FILE" >&2
  exit 1
fi

case "$BRANCH_NAME" in
  codex/*|feature/*)
    ;;
  *)
    echo "Branch must start with codex/ or feature/: $BRANCH_NAME" >&2
    exit 1
    ;;
esac

if ! command -v codex >/dev/null 2>&1; then
  echo "codex CLI not found in PATH" >&2
  exit 1
fi

# --- GitHub Issue linkage Gate (Dev Mode requires an Issue) ---
# Plan Mode allows no-issue; Dev Mode blocks unless explicitly authorized.
ISSUE_REF="$(grep -iE 'github issue|issue\s*[:#]|#\d+' "$TASK_FILE" 2>/dev/null | head -1 || true)"
if [ -z "$ISSUE_REF" ]; then
  if [ "$ALLOW_NO_ISSUE" -eq 1 ]; then
    echo "[WARN] No GitHub Issue linked, but --allow-no-issue passed: proceeding with explicit user authorization." >&2
  else
    echo "[ERR] No GitHub Issue linked in task file. Dev Mode requires a linked Issue." >&2
    echo "      Link one via scripts/ai/link_task_issue.sh, or re-run with --allow-no-issue (explicit user authorization)." >&2
    exit 1
  fi
fi

GIT_ROOT="$(git rev-parse --show-toplevel)"
cd "$GIT_ROOT"

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$CURRENT_BRANCH" != "main" ]; then
  echo "Current branch is $CURRENT_BRANCH, not main." >&2
  echo "Start development runs from main so the created branch has a clean base." >&2
  exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
  echo "Working tree is not clean. Commit, stash, or review changes before running dev." >&2
  git status --short
  exit 1
fi

mkdir -p .ai/results .ai/logs

git fetch origin main
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
  echo "Local main is not aligned with origin/main after fetch." >&2
  echo "Review with: git log --oneline --decorate --left-right HEAD...origin/main" >&2
  exit 1
fi

git switch -c "$BRANCH_NAME"

TS="$(date +%Y%m%d-%H%M%S)"
if [ -n "${TASK_ID:-}" ]; then
  RESULT_DIR=".ai/results/${TASK_ID}"
  mkdir -p "$RESULT_DIR"
  OUT_FILE="${RESULT_DIR}/codex_dev_${TS}.md"
  LOG_FILE=".ai/logs/codex_dev_${TASK_ID}_${TS}.log"
else
  OUT_FILE=".ai/results/codex_dev_${TS}.md"
  LOG_FILE=".ai/logs/codex_dev_${TS}.log"
fi

{
  echo "Running Codex workspace-write development"
  echo "Repository: $GIT_ROOT"
  echo "Task: $TASK_FILE"
  echo "Branch: $BRANCH_NAME"
  echo "TASK_ID: ${TASK_ID:-<none>}"
  echo "Output: $OUT_FILE"
  echo "Log: $LOG_FILE"
  echo
  git status --short --branch
  echo
} | tee "$LOG_FILE"

codex exec --sandbox workspace-write --output-last-message "$OUT_FILE" - <"$TASK_FILE" 2>&1 | tee -a "$LOG_FILE"

{
  echo
  echo "Codex dev finished"
  echo "Branch: $BRANCH_NAME"
  echo "Output: $OUT_FILE"
  echo "Log: $LOG_FILE"
  echo
  echo "Git status:"
  git status --short
  echo
  echo "Diff stat:"
  git diff --stat
} | tee -a "$LOG_FILE"
