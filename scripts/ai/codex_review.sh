#!/usr/bin/env bash
# Run a read-only Codex review for a TASK and write structured Markdown output.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
OUT_ROOT="$REPO_ROOT/.ai/results"

source "$SCRIPT_DIR/_work_level_lib.sh"

TASK_ID=""
TARGET_KIND=""
TARGET_VALUE=""
PROMPT_FILE=""

usage() {
  cat <<'EOF'
Usage: scripts/ai/codex_review.sh --task <TASK_ID> [--uncommitted | --base <ref> | --commit <sha>] [--prompt <file>]

Review targets:
  --uncommitted       Review uncommitted working tree changes.
  --base <ref>        Review current HEAD relative to base ref.
  --commit <sha>      Review a single commit.

If no target is provided, the script reviews HEAD relative to the TASK base ref when
available, then GUIYI_REVIEW_BASE_BRANCH, then main/master.
EOF
}

set_target() {
  local kind="$1" value="${2:-}"
  if [[ -n "$TARGET_KIND" ]]; then
    echo "Review target conflict: choose only one of --uncommitted, --base, --commit" >&2
    exit 2
  fi
  TARGET_KIND="$kind"
  TARGET_VALUE="$value"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task)
      TASK_ID="${2:-}"
      [[ -n "$TASK_ID" ]] || { echo "--task requires a value" >&2; exit 2; }
      shift 2
      ;;
    --uncommitted)
      set_target "uncommitted"
      shift
      ;;
    --base)
      [[ -n "${2:-}" ]] || { echo "--base requires a value" >&2; exit 2; }
      set_target "base" "$2"
      shift 2
      ;;
    --commit)
      [[ -n "${2:-}" ]] || { echo "--commit requires a value" >&2; exit 2; }
      set_target "commit" "$2"
      shift 2
      ;;
    --prompt)
      PROMPT_FILE="${2:-}"
      [[ -n "$PROMPT_FILE" ]] || { echo "--prompt requires a value" >&2; exit 2; }
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[[ -n "$TASK_ID" ]] || { usage >&2; exit 2; }

cd "$REPO_ROOT"

TASK_FILE="$(resolve_task_file "$TASK_ID" || true)"
[[ -n "$TASK_FILE" ]] || { echo "TASK not found: $TASK_ID" >&2; exit 4; }

command -v codex >/dev/null 2>&1 || { echo "codex CLI not found" >&2; exit 3; }

check_issue_gate "$TASK_FILE" >/dev/null || exit $?
WORK_LEVEL="$(extract_work_level "$TASK_FILE")"
if [[ "$WORK_LEVEL" != "L0" ]]; then
  check_worktree_gate "$TASK_FILE" >/dev/null || exit $?
fi

OUT_DIR="$OUT_ROOT/$TASK_ID"
mkdir -p "$OUT_DIR"

if [[ -z "$TARGET_KIND" ]]; then
  base_from_task="$(extract_task_meta_field "$TASK_FILE" "Base" | sed -E 's/`//g; s/^[[:space:]]+|[[:space:]]+$//g')"
  if [[ -n "$base_from_task" ]] && git rev-parse --verify --quiet "$base_from_task^{commit}" >/dev/null; then
    TARGET_KIND="base"
    TARGET_VALUE="$base_from_task"
  elif [[ -n "${GUIYI_REVIEW_BASE_BRANCH:-}" ]] && git rev-parse --verify --quiet "${GUIYI_REVIEW_BASE_BRANCH}^{commit}" >/dev/null; then
    TARGET_KIND="base"
    TARGET_VALUE="$GUIYI_REVIEW_BASE_BRANCH"
  elif git rev-parse --verify --quiet "main^{commit}" >/dev/null; then
    TARGET_KIND="base"
    TARGET_VALUE="main"
  elif git rev-parse --verify --quiet "master^{commit}" >/dev/null; then
    TARGET_KIND="base"
    TARGET_VALUE="master"
  else
    echo "No review target provided and no default base ref found" >&2
    exit 2
  fi
fi

case "$TARGET_KIND" in
  uncommitted)
    TARGET_LABEL="uncommitted"
    DIFF_CONTEXT="$(git diff --stat -- . && printf '\n===== DIFF =====\n' && git diff -- .)"
    ;;
  base)
    git rev-parse --verify --quiet "$TARGET_VALUE^{commit}" >/dev/null || { echo "Base ref not found: $TARGET_VALUE" >&2; exit 2; }
    TARGET_LABEL="base:$TARGET_VALUE"
    DIFF_CONTEXT="$(git diff --stat "$TARGET_VALUE"...HEAD -- . && printf '\n===== DIFF =====\n' && git diff "$TARGET_VALUE"...HEAD -- .)"
    ;;
  commit)
    git rev-parse --verify --quiet "$TARGET_VALUE^{commit}" >/dev/null || { echo "Commit not found: $TARGET_VALUE" >&2; exit 2; }
    TARGET_LABEL="commit:$TARGET_VALUE"
    DIFF_CONTEXT="$(git show --stat --format=medium "$TARGET_VALUE" && printf '\n===== DIFF =====\n' && git show --format= --patch "$TARGET_VALUE")"
    ;;
  *)
    echo "Unsupported review target: $TARGET_KIND" >&2
    exit 2
    ;;
esac

PROMPT_TMP="$(mktemp)"
DIFF_BEFORE="$(mktemp)"
trap 'rm -f "$PROMPT_TMP" "$DIFF_BEFORE"' EXIT

git diff --binary HEAD > "$DIFF_BEFORE"

{
  echo "你是 Codex CLI，处于只读 Review 模式。不得修改仓库文件。"
  echo "请输出结构化 Markdown，并优先列出 findings；没有问题时明确说明未发现阻断问题。"
  echo
  echo "Review focus:"
  echo "- 功能正确性"
  echo "- 回归风险"
  echo "- 数据和时间序列一致性"
  echo "- look-ahead / 数据泄露"
  echo "- 异常处理"
  echo "- 测试缺口"
  echo "- allowed_paths 越界"
  echo "- 安全、凭据和生产访问"
  echo
  echo "Critical rule:"
  echo "- critical TASK 不能仅靠 Codex review 关闭 external_review_required。"
  echo
  echo "===== TASK: $TASK_FILE ====="
  sed -E 's/(token|webhook|password|secret|api[_-]?key|access[_-]?key|DATABASE_URL)([[:space:]]*[:=][[:space:]]*)[^[:space:]]+/\1\2[REDACTED]/Ig' "$TASK_FILE"
  echo
  echo "===== REVIEW TARGET ====="
  echo "$TARGET_LABEL"
  echo
  echo "===== CURRENT GIT STATUS ====="
  git status --short --branch | sed -E 's/(token|webhook|password|secret|api[_-]?key|access[_-]?key|DATABASE_URL)([[:space:]]*[:=][[:space:]]*)[^[:space:]]+/\1\2[REDACTED]/Ig'
  echo
  echo "===== DIFF CONTEXT ====="
  printf '%s\n' "$DIFF_CONTEXT" | sed -E 's/(token|webhook|password|secret|api[_-]?key|access[_-]?key|DATABASE_URL)([[:space:]]*[:=][[:space:]]*)[^[:space:]]+/\1\2[REDACTED]/Ig'
  if [[ -n "$PROMPT_FILE" ]]; then
    [[ -f "$PROMPT_FILE" ]] || { echo "Prompt file not found: $PROMPT_FILE" >&2; exit 4; }
    echo
    echo "===== EXTRA REVIEW PROMPT ====="
    sed -E 's/(token|webhook|password|secret|api[_-]?key|access[_-]?key|DATABASE_URL)([[:space:]]*[:=][[:space:]]*)[^[:space:]]+/\1\2[REDACTED]/Ig' "$PROMPT_FILE"
  fi
} > "$PROMPT_TMP"

REVIEW_FILE="$OUT_DIR/review.md"
{
  echo "<!-- review_target: $TARGET_LABEL -->"
  echo "<!-- generated_at: $(date -u +%Y-%m-%dT%H:%M:%SZ) -->"
  echo
  codex exec -s read-only "$(cat "$PROMPT_TMP")"
} > "$REVIEW_FILE" 2> "$OUT_DIR/review.err" || {
  echo "Codex Review failed; see $OUT_DIR/review.err" >&2
  exit 1
}

cmp -s "$DIFF_BEFORE" <(git diff --binary HEAD) || {
  echo "Read-only Gate failed: tracked git diff changed during Review" >&2
  exit 6
}

echo "[OK] Review generated without tracked repository changes: $REVIEW_FILE"
