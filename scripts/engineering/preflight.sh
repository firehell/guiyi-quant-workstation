#!/usr/bin/env bash
# Engineering preflight — read-only environment / branch / dirty-tree probes.
# Zero dependency on retired orchestration and model-routing components.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
STRICT=false
CI_MODE=false
JSON_OUTPUT=false

usage() {
  cat <<'USAGE'
Usage: scripts/engineering/preflight.sh [--strict] [--ci] [--json]

Read-only checks: git root, current branch, dirty status summary,
python3 availability, optional data path existence (no auto-create).

  --strict  Local gate: fail on protected branches (main/master/develop)
            and on a dirty worktree.
  --ci      Actions mode: skip "must be on feature branch" (CI may run on
            main after merge or detached HEAD). Still fails on dirty
            worktree. Does NOT weaken secret/safety checks elsewhere.
  --json    Machine-readable report.

--strict and --ci are mutually exclusive.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --strict) STRICT=true; shift ;;
    --ci) CI_MODE=true; shift ;;
    --json) JSON_OUTPUT=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$STRICT" == true && "$CI_MODE" == true ]]; then
  echo "[REJECTED] --strict and --ci are mutually exclusive" >&2
  exit 2
fi

cd "$REPO_ROOT"

python3 - "$REPO_ROOT" "$STRICT" "$CI_MODE" "$JSON_OUTPUT" <<'PY'
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

repo = Path(sys.argv[1]).resolve()
strict = sys.argv[2] == "true"
ci_mode = sys.argv[3] == "true"
json_out = sys.argv[4] == "true"
checks: list[dict[str, str]] = []


def record(name: str, status: str, detail: str = "") -> None:
    checks.append({"name": name, "status": status, "detail": detail})


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=repo, capture_output=True, text=True)


# git
if shutil.which("git"):
    r = run(["git", "--version"])
    record("git", "passed" if r.returncode == 0 else "failed", (r.stdout or r.stderr).strip())
else:
    record("git", "failed", "git not found")

# repo root consistency
r = run(["git", "rev-parse", "--show-toplevel"])
root = (r.stdout or "").strip()
record(
    "git_root",
    "passed" if r.returncode == 0 and Path(root).resolve() == repo else "failed",
    root or "unavailable",
)

# branch — local --strict rejects protected branches; CI skips this gate.
r = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
branch = (r.stdout or "").strip()
protected_branches = {"main", "master", "develop"}
if ci_mode:
    record(
        "branch_not_main",
        "passed",
        f"branch={branch} (ci mode: branch gate skipped; dirty/safety still enforced)",
    )
elif branch in {"main", "master"}:
    record("branch_not_main", "failed" if strict else "warn", f"branch={branch}")
else:
    record("branch_not_main", "passed", f"branch={branch}")

if ci_mode:
    record(
        "branch_not_protected",
        "passed",
        f"branch={branch} (ci mode: branch gate skipped; dirty/safety still enforced)",
    )
elif branch in protected_branches:
    record("branch_not_protected", "failed" if strict else "warn", f"branch={branch}")
else:
    record("branch_not_protected", "passed", f"branch={branch}")

# dirty — fail under --strict or --ci; warn otherwise
r = run(["git", "status", "--porcelain"])
dirty_lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
block_dirty = strict or ci_mode
if dirty_lines:
    record(
        "dirty_worktree",
        "failed" if block_dirty else "warn",
        f"{len(dirty_lines)} path(s) dirty",
    )
else:
    record("dirty_worktree", "passed", "clean")

# python3
if shutil.which("python3"):
    r = run(["python3", "--version"])
    record("python3", "passed" if r.returncode == 0 else "failed", (r.stdout or r.stderr).strip())
else:
    record("python3", "failed", "python3 not found")

# optional data path existence — fail-closed report only, never create
for rel in ("data", "data/parquet"):
    p = repo / rel
    if p.exists():
        record(f"path_exists:{rel}", "passed", str(p))
    else:
        record(f"path_exists:{rel}", "warn", f"missing (not auto-created): {rel}")

# never print env secret values
secret_keys = [k for k in os.environ if any(s in k.upper() for s in ("TOKEN", "PASSWORD", "SECRET", "WEBHOOK", "API_KEY"))]
record("env_secret_keys_present", "passed", f"count={len(secret_keys)} (values not printed)")

failed = sum(1 for c in checks if c["status"] == "failed")
warn = sum(1 for c in checks if c["status"] == "warn")
report = {
    "schema_version": 1,
    "tool": "scripts/engineering/preflight.sh",
    "repo_root": str(repo),
    "strict": strict,
    "ci": ci_mode,
    "summary": {"failed": failed, "warn": warn, "passed": sum(1 for c in checks if c["status"] == "passed")},
    "checks": checks,
}

if json_out:
    print(json.dumps(report, ensure_ascii=False, indent=2))
else:
    for c in checks:
        prefix = {"passed": "[OK]", "failed": "[FAIL]", "warn": "[WARN]"}.get(c["status"], "[?]")
        line = f"{prefix} {c['name']}"
        if c["detail"]:
            line = f"{line}: {c['detail']}"
        print(line)
    print(f"\nSummary: passed={report['summary']['passed']} failed={failed} warn={warn}")

sys.exit(1 if failed else 0)
PY
