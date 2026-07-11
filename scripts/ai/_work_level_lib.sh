#!/usr/bin/env bash
# Shared helpers for L0/L1/L2 work levels and worktree gates.
# shellcheck disable=SC2034

normalize_work_level() {
  local raw="${1:-L2}"
  raw="$(printf '%s' "$raw" | tr '[:lower:]' '[:upper:]' | tr -d ' ')"
  case "$raw" in
    L0|L1|L2) printf '%s\n' "$raw" ;;
    *) printf '%s\n' "L2" ;;
  esac
}

extract_task_meta_field() {
  local task_file="$1" field="$2"
  sed -nE "/^## 0\\./,/^## /s/^\\| ${field} \\| (.*) \\|$/\\1/p" "$task_file" | head -1
}

extract_work_level() {
  local task_file="$1" raw
  raw="$(extract_task_meta_field "$task_file" "Work Level")"
  normalize_work_level "${raw:-L2}"
}

extract_worktree_path() {
  local task_file="$1" raw
  raw="$(extract_task_meta_field "$task_file" "Worktree")"
  raw="$(printf '%s' "$raw" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
  case "$raw" in
    ""|"待 init_task_worktree.sh 回填"|"待创建"|"待 init"*) return 1 ;;
    *) printf '%s\n' "$raw" ;;
  esac
}

resolve_worktree_root() {
  local repo_root="${1:-}"
  if [[ -n "${GUIYI_WORKTREE_ROOT:-}" ]]; then
    printf '%s\n' "$GUIYI_WORKTREE_ROOT"
    return 0
  fi
  if [[ -z "$repo_root" ]]; then
    repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  fi
  printf '%s\n' "$(cd "$repo_root/.." && pwd)/guiyi-parallel"
}

task_slug_from_id() {
  local task_id="$1"
  printf '%s\n' "$task_id" | sed -E 's/^TASK-//; s/[^A-Za-z0-9]+/-/g; s/^-+|-+$//g' | tr '[:upper:]' '[:lower:]'
}

default_branch_for_task() {
  local task_file="$1" branch
  branch="$(extract_task_meta_field "$task_file" "Branch")"
  branch="$(printf '%s' "$branch" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
  if [[ -n "$branch" && "$branch" != "feature/{{slug}}" ]]; then
    printf '%s\n' "$branch"
    return 0
  fi
  local task_id
  task_id="$(extract_task_meta_field "$task_file" "Task ID")"
  [[ -n "$task_id" ]] || task_id="$(basename "$task_file" .md)"
  printf 'feature/%s\n' "$(task_slug_from_id "$task_id")"
}

resolve_task_file() {
  local task_id="$1" candidate
  for candidate in "docs/tasks/${task_id}.md" ".ai/tasks/${task_id}.md" "docs/tasks/examples/${task_id}.md"; do
    if [[ -f "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

check_issue_gate() {
  local task_file="$1" level issue
  level="$(extract_work_level "$task_file")"
  issue="$(extract_task_meta_field "$task_file" "GitHub Issue")"
  issue="$(printf '%s' "$issue" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
  case "$level" in
    L0)
      return 0
      ;;
    L1)
      if [[ "$issue" =~ ^#[0-9]+$ ]]; then
        echo "[OK] L1 Issue Gate: $issue"
        return 0
      fi
      echo "[WARN] L1: Issue Gate skipped (no GitHub Issue); upgrade to L2 before merge" >&2
      return 0
      ;;
    L2)
      if [[ "$issue" =~ ^#[0-9]+$ ]]; then
        echo "[OK] L2 Issue Gate: $issue"
        return 0
      fi
      echo "Issue Gate failed: L2 TASK must contain GitHub Issue #N" >&2
      return 5
      ;;
  esac
}

check_worktree_gate() {
  local task_file="$1" level expected current
  level="$(extract_work_level "$task_file")"
  case "$level" in
    L0) return 0 ;;
  esac
  if ! expected="$(extract_worktree_path "$task_file")"; then
    echo "Worktree Gate failed: TASK Worktree not set; run init_task_worktree.sh --task <ID>" >&2
    return 7
  fi
  current="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  if [[ -z "$current" ]]; then
    echo "Worktree Gate failed: not inside a git worktree" >&2
    return 7
  fi
  expected="$(cd "$expected" 2>/dev/null && pwd -P || printf '%s' "$expected")"
  current="$(cd "$current" && pwd -P)"
  if [[ "$current" != "$expected" ]]; then
    echo "Worktree Gate failed: current=$current expected=$expected" >&2
    return 7
  fi
  echo "[OK] Worktree Gate: $current"
  return 0
}

set_task_meta_field() {
  local task_file="$1" field="$2" value="$3"
  python3 - "$task_file" "$field" "$value" <<'PY'
import re, sys
path, field, value = sys.argv[1:4]
text = open(path, encoding="utf-8").read()
pattern = re.compile(rf"(^\| {re.escape(field)} \| ).*( \|$)", re.M)
if not pattern.search(text):
    raise SystemExit(f"field not found: {field}")
text = pattern.sub(rf"\1{value}\2", text, count=1)
with open(path, "w", encoding="utf-8") as fh:
    fh.write(text)
PY
}
