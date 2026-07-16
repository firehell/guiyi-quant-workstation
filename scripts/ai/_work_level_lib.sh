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
  local value yaml_value table_value

  if task_meta_python_available; then
    if value="$(task_meta_value "$task_file" "$field" 2>/dev/null)"; then
      if [[ -n "$value" ]]; then
        printf '%s\n' "$value"
        return 0
      fi
    elif task_has_yaml_frontmatter "$task_file"; then
      return 1
    fi
  fi

  if task_has_yaml_frontmatter "$task_file"; then
    yaml_value="$(task_yaml_frontmatter_value "$task_file" "$field" 2>/dev/null || true)"
    if [[ -n "$yaml_value" ]]; then
      table_value="$(task_legacy_table_value "$task_file" "$field" 2>/dev/null || true)"
      if [[ -n "$table_value" && "$table_value" != "$yaml_value" ]]; then
        echo "[WARN] TASK metadata conflict: field=$field YAML frontmatter wins over legacy table" >&2
      fi
      printf '%s\n' "$yaml_value"
      return 0
    fi
  fi

  value="$(task_legacy_table_value "$task_file" "$field" 2>/dev/null || true)"
  if [[ -n "$value" ]]; then
    printf '%s\n' "$value"
    return 0
  fi

  return 1
}

task_meta_python_available() {
  local lib_dir
  lib_dir="${SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}/lib"
  [[ -f "$lib_dir/task_meta.py" && -f "$lib_dir/task_runtime.py" && -f "$lib_dir/compat_reader.py" && -f "$lib_dir/risk_resolver.py" && -f "$lib_dir/status_machine.py" ]]
}

task_has_yaml_frontmatter() {
  local task_file="$1"
  python3 - "$task_file" <<'PY'
from pathlib import Path
import sys

text = Path(sys.argv[1]).read_text(encoding="utf-8")
raise SystemExit(0 if text.startswith("---\n") else 1)
PY
}

task_yaml_frontmatter_value() {
  local task_file="$1" field="$2"
  python3 - "$task_file" "$field" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

field = sys.argv[2]
mapping = {
    "Task ID": "task_id",
    "Work Level": "work_level",
    "GitHub Issue": "github_issue",
    "GitHub PR": "github_pr",
    "Branch": "branch",
    "Worktree": "worktree",
    "Status": "status",
    "Critical": "critical",
    "Production Write Requested": "production_write_requested",
    "Production Write Approved": "production_write_approved",
    "Required Env": "required_env",
    "Required Mounts": "required_mounts",
    "Allowed Paths": "allowed_paths",
    "Forbidden Paths": "forbidden_paths",
    "Required Tests": "required_tests",
    "Risk Level": "risk_level",
    "Approval Scope": "approval_scope",
    "Depends On": "depends_on",
    "Resource Locks": "resource_locks",
    "Model Profile": "model_profile",
    "Base": "base_branch",
    "Base Branch": "base_branch",
    "Created At": "created_at",
    "Updated At": "updated_at",
}
key = mapping.get(field, field.lower().replace(" ", "_"))
text = Path(sys.argv[1]).read_text(encoding="utf-8")
if not text.startswith("---\n"):
    raise SystemExit(1)
end = text.find("\n---", 4)
if end == -1:
    raise SystemExit(1)


def clean_scalar(raw: str) -> str:
    value = raw.strip()
    if " #" in value:
        value = value.split(" #", 1)[0].strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    return value


def parse_inline_list(raw: str) -> list[str]:
    inner = raw.strip()[1:-1].strip()
    if not inner:
        return []
    return [clean_scalar(item) for item in inner.split(",") if clean_scalar(item)]


data: dict[str, str | list[str]] = {}
current_key = ""
for line in text[4:end].splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        continue
    if line[:1].isspace() and current_key:
        if stripped.startswith("- "):
            existing = data.setdefault(current_key, [])
            if isinstance(existing, list):
                existing.append(clean_scalar(stripped[2:]))
        continue
    if ":" not in line:
        current_key = ""
        continue
    raw_key, raw_value = line.split(":", 1)
    current_key = raw_key.strip()
    raw_value = raw_value.strip()
    if raw_value == "":
        data[current_key] = []
    elif raw_value.startswith("[") and raw_value.endswith("]"):
        data[current_key] = parse_inline_list(raw_value)
        current_key = ""
    else:
        data[current_key] = clean_scalar(raw_value)
        current_key = ""

value = data.get(key)
if isinstance(value, list):
    print(",".join(value))
elif value is not None:
    print(value)
else:
    raise SystemExit(1)
PY
}

task_legacy_table_value() {
  local task_file="$1" field="$2"
  python3 - "$task_file" "$field" <<'PY'
from pathlib import Path
import re
import sys

text = Path(sys.argv[1]).read_text(encoding="utf-8")
field = sys.argv[2]
match = re.search(r"^##\s+0\..*?\n(?P<body>.*?)(?=\n##\s+|\Z)", text, re.M | re.S)
if not match:
    raise SystemExit(1)
for line in match.group("body").splitlines():
    if not line.startswith("|"):
        continue
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if len(cells) >= 2 and cells[0] == field:
        print(cells[1])
        raise SystemExit(0)
raise SystemExit(1)
PY
}

task_meta_value() {
  local task_file="$1" field="$2"
  local lib_dir
  lib_dir="${SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}/lib"
  PYTHONPATH="$lib_dir${PYTHONPATH:+:$PYTHONPATH}" python3 - "$task_file" "$field" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

from task_meta import parse_task_file

field = sys.argv[2]
mapping = {
    "Task ID": "task_id",
    "Work Level": "work_level",
    "GitHub Issue": "github_issue",
    "GitHub PR": "github_pr",
    "Branch": "branch",
    "Worktree": "worktree",
    "Status": "status",
    "Critical": "critical",
    "Production Write Requested": "production_write_requested",
    "Production Write Approved": "production_write_approved",
    "Required Env": "required_env",
    "Required Mounts": "required_mounts",
    "Allowed Paths": "allowed_paths",
    "Forbidden Paths": "forbidden_paths",
    "Required Tests": "required_tests",
    "Risk Level": "risk_level",
    "Approval Scope": "approval_scope",
    "Depends On": "depends_on",
    "Resource Locks": "resource_locks",
    "Model Profile": "model_profile",
    "Base Branch": "base_branch",
    "Created At": "created_at",
    "Updated At": "updated_at",
}
attr = mapping.get(field, field.lower().replace(" ", "_"))
try:
    meta = parse_task_file(Path(sys.argv[1]))
    value = getattr(meta, attr, "")
except Exception as exc:
    print(f"Task metadata failed: {exc}", file=sys.stderr)
    raise SystemExit(1)
if isinstance(value, bool):
    print("true" if value else "false")
elif isinstance(value, (tuple, list)):
    print(",".join(str(item) for item in value))
elif value is not None:
    print(value)
PY
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

# ── Branch Gate (WS-V2-006 G1) ──────────────────────────────────────────────

extract_base_branch() {
  local task_file="$1" raw
  raw="$(extract_task_meta_field "$task_file" "Base Branch")"
  raw="$(printf '%s' "$raw" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
  if [[ -z "$raw" || "$raw" == "-" || "$raw" == "无" || "$raw" == "N/A" || "$raw" == "n/a" ]]; then
    printf '%s\n' "main"
  else
    printf '%s\n' "$raw"
  fi
}

extract_task_branch() {
  local task_file="$1" raw
  raw="$(extract_task_meta_field "$task_file" "Branch")"
  raw="$(printf '%s' "$raw" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
  if [[ -z "$raw" || "$raw" == "feature/{{slug}}" ]]; then
    local task_id
    task_id="$(extract_task_meta_field "$task_file" "Task ID")"
    [[ -n "$task_id" ]] || task_id="$(basename "$task_file" .md)"
    printf 'feature/%s\n' "$(task_slug_from_id "$task_id")"
  else
    printf '%s\n' "$raw"
  fi
}

# Verify current branch matches task declaration.
check_branch() {
  local task_file="$1" expected current repo_root
  repo_root="${2:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"

  local work_level
  work_level="$(extract_work_level "$task_file")"
  [[ "$work_level" == "L0" ]] && return 0

  expected="$(extract_task_branch "$task_file")"
  [[ -n "$expected" ]] || return 0

  current="$(git -C "$repo_root" branch --show-current 2>/dev/null || true)"
  if [[ "$current" != "$expected" ]]; then
    echo "Branch Gate failed: current=$current expected=$expected" >&2
    return 8
  fi
  echo "[OK] Branch Gate: $current" >&2
  return 0
}

# Verify base_branch is valid and not main for workspace-write operations.
check_base_branch() {
  local task_file="$1" base
  local work_level
  work_level="$(extract_work_level "$task_file")"
  [[ "$work_level" == "L0" ]] && return 0

  base="$(extract_base_branch "$task_file")"

  if [[ "$base" == "main" || "$base" == "master" ]]; then
    echo "Base Branch Gate warning: base_branch=$base — workspace-write will be prohibited" >&2
    # Still returns 0 — the write prohibition is enforced by check_main_write_protection
  fi

  echo "[OK] Base Branch Gate: base=$base" >&2
  return 0
}

# Main/master branch write protection.
# For stages that write (dev/fix/apply), refuse to run on main/master.
check_main_write_protection() {
  local stage="$1"
  local repo_root="${2:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"

  case "$stage" in
    dev|fix|apply) ;;
    *) return 0 ;;
  esac

  local current
  current="$(git -C "$repo_root" branch --show-current 2>/dev/null || true)"

  case "$current" in
    main|master)
      echo "Write Protection Gate FAILED: stage=$stage is forbidden on branch=$current" >&2
      echo "Use a feature/ or fix/ branch via init_task_worktree.sh" >&2
      return 10
      ;;
  esac

  echo "[OK] Write Protection Gate: branch=$current allows $stage" >&2
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

set_task_meta_field_if_present() {
  local task_file="$1" field="$2" value="$3"
  if grep -qE "^\\| ${field} \\|" "$task_file"; then
    set_task_meta_field "$task_file" "$field" "$value"
  fi
}

# ── WS-V2-006: Branch / Base Branch Gate ──────────────────────────────

extract_base_branch() {
  local task_file="$1" raw
  raw="$(extract_task_meta_field "$task_file" "Base Branch" 2>/dev/null || true)"
  raw="$(printf '%s' "$raw" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
  if [[ -z "$raw" || "$raw" == "-" ]]; then
    printf '%s\n' "main"
  else
    printf '%s\n' "$raw"
  fi
}

check_base_branch() {
  local task_file="$1" base_branch repo_root current_branch
  repo_root="${REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
  base_branch="$(extract_base_branch "$task_file")"
  current_branch="$(git -C "$repo_root" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
  # Warn if the current branch is the base branch during write stages
  if [[ "$current_branch" == "$base_branch" ]]; then
    echo "[WARN] Base Branch Gate: operating on base_branch=$base_branch directly" >&2
  fi
  echo "[OK] Base Branch Gate: base_branch=$base_branch" >&2
  return 0
}
