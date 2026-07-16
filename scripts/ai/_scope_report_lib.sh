#!/usr/bin/env bash
# ── Scope Violation Report (WS-V2-006 G4) ────────────────────────────────────
# Post-dev: git diff HEAD to detect out-of-scope file modifications.
# Compares changed files against allowed_paths. Out-of-scope changes block
# subsequent phases (test/result/close).

set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"

# Generate a scope report JSON.
# {
#   "task_id": "...",
#   "total_changes": N,
#   "in_scope": [...],
#   "out_of_scope": [...],
#   "violations": [...],
#   "ok": true|false,
#   "blocked_phases": [...]
# }
generate_scope_report() {
  local task_file="$1"
  local task_id="${2:-unknown}"
  local output_file="${3:-}"
  local repo_root="${4:-$REPO_ROOT}"

  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$repo_root/scripts/ai/lib${PYTHONPATH:+:$PYTHONPATH}" python3 - \
    "$task_file" "$task_id" "${output_file:-}" "$repo_root" <<'PY'
from __future__ import annotations

import fnmatch, json, os, subprocess, sys
from pathlib import Path
from typing import List, Set


def run_git_diff(repo_root: Path) -> List[str]:
    """Get files changed since branching point (merge-base with main)."""
    try:
        base = subprocess.check_output(
            ["git", "merge-base", "origin/main", "HEAD"],
            cwd=str(repo_root), text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        try:
            base = subprocess.check_output(
                ["git", "merge-base", "main", "HEAD"],
                cwd=str(repo_root), text=True, stderr=subprocess.DEVNULL,
            ).strip()
        except Exception:
            base = "HEAD~1"

    try:
        output = subprocess.check_output(
            ["git", "diff", "--name-only", base, "HEAD"],
            cwd=str(repo_root), text=True, stderr=subprocess.DEVNULL,
        )
        return [f.strip() for f in output.splitlines() if f.strip()]
    except Exception:
        return []


def match_any(file_path: str, patterns: Set[str]) -> bool:
    for pattern in patterns:
        if pattern and fnmatch.fnmatch(file_path, pattern):
            return True
    return False


def main():
    task_path = Path(sys.argv[1])
    task_id = sys.argv[2]
    output = sys.argv[3]
    repo_root = Path(sys.argv[4]).resolve()

    # Parse task
    try:
        from task_meta import parse_task_file
        meta = parse_task_file(task_path)
    except Exception as e:
        report = {"task_id": task_id, "error": str(e), "ok": False}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(1)

    allowed = set(meta.allowed_paths)
    forbidden = set(meta.forbidden_paths)

    # Always add common allowed paths for dev artifacts
    default_allowed = {
        ".ai/*", ".ai/results/*", ".ai/results/**", ".ai/tasks/*",
        ".ai/approvals/*", ".ai/approvals/**",
        "docs/tasks/*", "docs/tasks/**", "workstation/**",
    }
    allowed.update(default_allowed)

    changed_files = run_git_diff(repo_root)

    in_scope: list[str] = []
    out_of_scope: list[str] = []
    violations: list[str] = []

    for f in changed_files:
        if match_any(f, forbidden):
            violations.append(f)
        elif match_any(f, allowed):
            in_scope.append(f)
        else:
            out_of_scope.append(f)

    ok = len(violations) == 0 and len(out_of_scope) == 0
    blocked_phases: list[str] = []

    if not ok:
        blocked_phases = ["test", "review", "result", "close"]

    report = {
        "schema_version": 1,
        "task_id": task_id,
        "total_changes": len(changed_files),
        "in_scope": in_scope,
        "out_of_scope": out_of_scope,
        "violations": violations,
        "allowed_patterns": sorted(allowed),
        "forbidden_patterns": sorted(forbidden),
        "ok": ok,
        "blocked_phases": blocked_phases,
    }

    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"

    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")

    print(rendered, end="")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
PY
}

# Validate scope report and optionally block.
# Returns 0 if scope is clean.
check_scope_gate() {
  local task_file="$1"
  local task_id="$2"
  local out_dir="$3"
  local repo_root="${4:-$REPO_ROOT}"

  # Allow bypass via env var (test/CI environments)
  if [[ "${GUIYI_SKIP_SCOPE_GATE:-}" == "1" ]]; then
    echo "[SCOPE] Bypassed (GUIYI_SKIP_SCOPE_GATE=1)" >&2
    return 0
  fi

  local report_file="$out_dir/scope_report.json"

  echo "[SCOPE] Generating scope violation report..." >&2
  local rc=0
  set +e
  generate_scope_report "$task_file" "$task_id" "$report_file" "$repo_root"
  rc=$?
  set -e

  if [[ $rc -ne 0 ]]; then
    echo "[SCOPE] FAIL: scope violations detected. See $report_file" >&2
    # Print summary
    python3 -c "
import json
report = json.loads(open('$report_file').read())
print(f'  In scope: {len(report[\"in_scope\"])}')
print(f'  Out of scope: {len(report[\"out_of_scope\"])}')
if report.get('out_of_scope'):
    for f in report['out_of_scope']:
        print(f'    - {f}')
print(f'  Violations: {len(report[\"violations\"])}')
if report.get('violations'):
    for f in report['violations']:
        print(f'    - {f} (FORBIDDEN)')
print(f'  Blocked phases: {report.get(\"blocked_phases\", [])}')
" >&2
    return 1
  fi

  echo "[SCOPE] Gate passes — all changes within allowed boundaries."
  return 0
}
