#!/usr/bin/env bash
# Fail-closed TASK environment gate. Values are never printed or persisted.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
TASK_ARG=""
STAGE=""
WORKTREE=""
JSON_OUTPUT=false
QUIET=false
OUTPUT_FILE=""

usage() {
  cat <<'EOF'
Usage: scripts/env/check_task_env.sh --task <TASK_ID_OR_FILE> [options]

Options:
  --stage <stage>       Stage name for executable checks
  --worktree <path>     Expected worktree path override
  --repo-root <path>    Repository root override
  --json               Print JSON result
  --quiet              Print nothing; use exit code only
  --output <path>      Write JSON result to path
  -h, --help           Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task) TASK_ARG="${2:-}"; shift 2 ;;
    --stage) STAGE="${2:-}"; shift 2 ;;
    --worktree) WORKTREE="${2:-}"; shift 2 ;;
    --repo-root) REPO_ROOT="${2:-}"; shift 2 ;;
    --json) JSON_OUTPUT=true; shift ;;
    --quiet) QUIET=true; shift ;;
    --output) OUTPUT_FILE="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$TASK_ARG" ]] || { usage >&2; exit 2; }

export PYTHONPATH="$REPO_ROOT/scripts/ai/lib${PYTHONPATH:+:$PYTHONPATH}"
python3 - "$REPO_ROOT" "$TASK_ARG" "$STAGE" "$WORKTREE" "$JSON_OUTPUT" "$QUIET" "$OUTPUT_FILE" <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from task_meta import TaskMetaError, parse_task_file, resolve_task_file


repo_root = Path(sys.argv[1]).resolve()
task_arg = sys.argv[2]
stage = sys.argv[3]
worktree_override = sys.argv[4]
json_output = sys.argv[5] == "true"
quiet = sys.argv[6] == "true"
output_file = sys.argv[7]


def env_file_keys(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    keys: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key = line.split("=", 1)[0].strip()
        if key.replace("_", "").isalnum() and not key[0].isdigit():
            keys.add(key)
    return keys


def safe_path(path: str) -> str:
    return str(Path(path).expanduser())


def current_branch(path: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "branch", "--show-current"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


def git_root(path: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


def executable_names(stage_name: str) -> list[str]:
    names = ["git", "python3"]
    if (repo_root / "uv.lock").exists() or (repo_root / "services" / "quant-api" / "pyproject.toml").exists():
        names.append("uv")
    if (repo_root / "pnpm-lock.yaml").exists() or (repo_root / "apps" / "quant-web" / "package.json").exists():
        names.append("pnpm")
    if stage_name in {"plan", "dev", "fix", "review"} and os.environ.get("GUIYI_SKIP_CODEX_ENV_CHECK") != "1":
        names.append("codex")
    extra = os.environ.get("GUIYI_ENV_REQUIRED_EXE", "")
    for item in extra.replace(",", " ").split():
        if item and item not in names:
            names.append(item)
    return names


def main() -> int:
    try:
        task_file = resolve_task_file(task_arg, repo_root)
        meta = parse_task_file(task_file)
    except TaskMetaError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    declared_worktree = worktree_override or meta.worktree
    worktree = Path(declared_worktree).expanduser().resolve() if declared_worktree else repo_root

    env_sources: list[Path] = []
    if os.environ.get("GUIYI_ENV_SOURCE"):
        env_sources.append(Path(os.environ["GUIYI_ENV_SOURCE"]).expanduser())
    env_sources.extend([worktree / ".env", repo_root / ".env"])
    keys_from_files: set[str] = set()
    source_names: dict[str, str] = {}
    for source in env_sources:
        for key in env_file_keys(source):
            keys_from_files.add(key)
            source_names.setdefault(key, str(source))

    env_checks = []
    for name in meta.required_env:
        present_in_process = name in os.environ and os.environ.get(name, "") != ""
        present_in_file = name in keys_from_files
        env_checks.append(
            {
                "name": name,
                "present": present_in_process or present_in_file,
                "source": "process" if present_in_process else ("env_file" if present_in_file else "missing"),
            }
        )

    mount_checks = []
    for raw_path in meta.required_mounts:
        path = Path(raw_path).expanduser()
        exists = path.exists()
        is_mount = exists and os.path.ismount(path)
        mount_checks.append({"path": safe_path(raw_path), "exists": exists, "is_mount": is_mount, "ok": is_mount})

    executable_checks = []
    for name in executable_names(stage):
        executable_checks.append({"name": name, "present": shutil.which(name) is not None})

    git_root_value = git_root(worktree)
    current = current_branch(worktree)
    expected = meta.branch.strip()
    worktree_declared = bool(declared_worktree)
    worktree_ok = meta.work_level == "L0" or (worktree_declared and worktree.exists() and git_root_value == str(worktree))
    branch_ok = meta.work_level == "L0" or not expected or current == expected

    payload: dict[str, Any] = {
        "schema_version": 1,
        "task_id": meta.task_id,
        "task_file": str(task_file),
        "stage": stage,
        "ok": True,
        "checks": {
            "env": env_checks,
            "mounts": mount_checks,
            "executables": executable_checks,
            "worktree": {
                "path": str(worktree),
                "declared": worktree_declared,
                "expected_branch": expected,
                "current_branch": current,
                "is_git_worktree": worktree_ok,
                "branch_ok": branch_ok,
            },
        },
        "failures": [],
    }

    failures: list[str] = payload["failures"]
    failures.extend(f"missing_env:{item['name']}" for item in env_checks if not item["present"])
    failures.extend(f"missing_mount:{item['path']}" for item in mount_checks if not item["ok"])
    failures.extend(f"missing_executable:{item['name']}" for item in executable_checks if not item["present"])
    if meta.work_level != "L0" and not worktree_declared:
        failures.append("worktree_missing")
    elif not worktree_ok:
        failures.append(f"worktree_invalid:{worktree}")
    if not branch_ok:
        failures.append(f"branch_mismatch:{current or '<none>'}!={expected}")
    payload["ok"] = not failures

    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if output_file:
        out = Path(output_file)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
    if json_output and not quiet:
        print(rendered, end="")
    elif not quiet:
        if payload["ok"]:
            print(f"[OK] env gate passed: task={meta.task_id}")
        else:
            for failure in failures:
                print(f"[FAIL] {failure}", file=sys.stderr)
    return 0 if payload["ok"] else 1


raise SystemExit(main())
PY
