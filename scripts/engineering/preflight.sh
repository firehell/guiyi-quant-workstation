#!/usr/bin/env bash
# Engineering preflight — read-only environment / branch / dirty-tree probes.
# Zero dependency on WorkBuddy / CodeBuddy / dispatcher / model router.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
STRICT=false
JSON_OUTPUT=false

usage() {
  cat <<'EOF'
Usage: scripts/engineering/preflight.sh [--strict] [--json]

Read-only checks: git root, current branch, dirty status summary,
python3 availability, optional data path existence (no auto-create).
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --strict) STRICT=true; shift ;;
    --json) JSON_OUTPUT=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

cd "$REPO_ROOT"

python3 - "$REPO_ROOT" "$STRICT" "$JSON_OUTPUT" <<'PY'
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

repo = Path(sys.argv[1]).resolve()
strict = sys.argv[2] == "true"
json_out = sys.argv[3] == "true"
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

# branch
r = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
branch = (r.stdout or "").strip()
if branch in {"main", "master"}:
    record("branch_not_main", "failed" if strict else "warn", f"branch={branch}")
else:
    record("branch_not_main", "passed", f"branch={branch}")

# dirty summary (informational; does not block unless --strict and dirty)
r = run(["git", "status", "--porcelain"])
dirty_lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
if dirty_lines:
    record(
        "dirty_worktree",
        "warn" if not strict else "failed",
        f"{len(dirty_lines)} path(s) dirty (informational)",
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
