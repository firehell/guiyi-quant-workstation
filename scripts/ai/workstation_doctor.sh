#!/usr/bin/env bash
# Aggregate preflight checks for the local AI workstation control plane.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"

JSON_OUTPUT=false
STRICT=false
SKIP_INSTALLED_PROFILES=false

usage() {
  cat <<'EOF'
Usage: scripts/ai/workstation_doctor.sh [options]

Options:
  --json                    Emit structured JSON report
  --strict                  Exit 1 on any failed check (warnings included)
  --skip-installed-profiles Skip codex installed profile checks
  -h, --help                Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json) JSON_OUTPUT=true; shift ;;
    --strict) STRICT=true; shift ;;
    --skip-installed-profiles) SKIP_INSTALLED_PROFILES=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

cd "$REPO_ROOT"

export PYTHONPATH="$SCRIPT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}"
export REPO_ROOT STRICT SKIP_INSTALLED_PROFILES JSON_OUTPUT

python3 - <<'PY'
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(os.environ["REPO_ROOT"]).resolve()
SCRIPT_DIR = REPO_ROOT / "scripts" / "ai"
STRICT = os.environ.get("STRICT", "false") == "true"
SKIP_INSTALLED = os.environ.get("SKIP_INSTALLED_PROFILES", "false") == "true"
JSON_OUTPUT = os.environ.get("JSON_OUTPUT", "false") == "true"

SECRET_PATTERN = re.compile(
    r"(?i)(DATABASE_URL|QYWX_WEBHOOK|token|webhook|password|secret|api[_-]?key)\s*[:=]\s*[^\s\]]+"
)
KNOWN_PROFILES = {
    "no-model",
    "plan-readonly",
    "review-readonly",
    "dev-workspace-write",
    "high-readonly",
    "high-workspace-write",
}
checks: list[dict[str, object]] = []
output_lines: list[str] = []


def record(name: str, status: str, detail: str = "") -> None:
    checks.append({"name": name, "status": status, "detail": detail})
    prefix = {"passed": "[OK]", "failed": "[FAIL]", "warn": "[WARN]", "skipped": "[SKIP]"}.get(status, "[?]")
    line = f"{prefix} {name}"
    if detail:
        line = f"{line}: {detail}"
    output_lines.append(line)


def run_cmd(args: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd or REPO_ROOT,
        env=env or os.environ.copy(),
        capture_output=True,
        text=True,
    )


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return f"{result.stdout}\n{result.stderr}"


# 1. git
if shutil.which("git"):
    result = run_cmd(["git", "--version"])
    record("git", "passed" if result.returncode == 0 else "failed", (result.stdout or result.stderr).strip())
else:
    record("git", "failed", "git not found in PATH")

# 2. codex version only
if SKIP_INSTALLED:
    record("codex", "skipped", "--skip-installed-profiles")
else:
    codex = shutil.which("codex")
    if codex:
        result = run_cmd(["codex", "--version"])
        detail = (result.stdout or result.stderr).strip().splitlines()[0] if result.returncode == 0 else "codex --version failed"
        record("codex", "passed" if result.returncode == 0 else "failed", detail)
    else:
        record("codex", "warn", "codex not found in PATH")

# 3. Python and project tools
for tool, required in [("python3", True), ("uv", False), ("pnpm", False)]:
    path = shutil.which(tool)
    if path:
        result = run_cmd([tool, "--version"])
        detail = (result.stdout or result.stderr).strip().splitlines()[0]
        record(tool, "passed" if result.returncode == 0 else "failed", detail)
    elif required:
        record(tool, "failed", "not found in PATH")
    else:
        record(tool, "warn", "optional tool not found")

# 4. TASK parser
try:
    from task_meta import parse_task_file, resolve_task_file
    from route_task import resolve_route

    fixture = REPO_ROOT / "tests" / "workstation" / "fixtures" / "FAST_DOC.md"
    if fixture.is_file():
        meta = parse_task_file(fixture)
        route = resolve_route(str(fixture), "plan", repo_root=REPO_ROOT)
        record("task_parser", "passed", f"{meta.task_id} tier={route['routing_tier']}")
    else:
        record("task_parser", "warn", "fixture FAST_DOC.md missing; import only")
except Exception as exc:
    record("task_parser", "failed", str(exc))

# 5. four profile templates
template_dir = REPO_ROOT / "configs" / "ai" / "profile_templates"
expected_tiers = {"fast", "standard", "deep", "critical"}
found_tiers: set[str] = set()
template_errors: list[str] = []
for path in sorted(template_dir.glob("*.json")):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        template_errors.append(f"{path.name}: {exc}")
        continue
    tier = payload.get("tier")
    if tier not in expected_tiers:
        template_errors.append(f"{path.name}: unknown tier {tier!r}")
        continue
    found_tiers.add(tier)
    defaults = payload.get("default_profiles", {})
    for profile in defaults.values():
        if profile not in KNOWN_PROFILES:
            template_errors.append(f"{path.name}: unknown profile {profile!r}")
if template_errors or found_tiers != expected_tiers:
    detail = "; ".join(template_errors or [f"missing tiers: {sorted(expected_tiers - found_tiers)}"])
    record("profile_templates", "failed", detail)
else:
    record("profile_templates", "passed", f"{len(found_tiers)} templates")

# 6. installed profiles optional
if SKIP_INSTALLED:
    record("installed_profiles", "skipped", "--skip-installed-profiles")
elif shutil.which("codex"):
    record("installed_profiles", "passed", "codex executable present")
else:
    record("installed_profiles", "warn", "codex not installed")

# 7. router
fixture = REPO_ROOT / "tests" / "workstation" / "fixtures" / "STANDARD_API.md"
if fixture.is_file():
    result = run_cmd(["bash", str(SCRIPT_DIR / "route_task.sh"), str(fixture), "route", "--json"])
    if result.returncode == 0:
        route = json.loads(result.stdout)
        record("router", "passed", f"tier={route.get('routing_tier')}")
    else:
        record("router", "failed", combined_output(result).strip())
else:
    record("router", "warn", "STANDARD_API fixture missing")

# 8. dispatcher dry-run
if fixture.is_file():
    env = os.environ.copy()
    env["GUIYI_AI_DRY_RUN"] = "1"
    env["GUIYI_SKIP_CODEX_ENV_CHECK"] = "1"
    result = run_cmd(
        ["bash", str(SCRIPT_DIR / "dispatch_task.sh"), str(fixture), "route", "--dry-run", "--json"],
        env=env,
    )
    record("dispatcher_dry_run", "passed" if result.returncode == 0 else "failed", combined_output(result).strip()[:200])
else:
    record("dispatcher_dry_run", "warn", "STANDARD_API fixture missing")

# 9. writer lock
result = run_cmd(["bash", str(SCRIPT_DIR / "writer_lock.sh"), "status", "--worktree", str(REPO_ROOT), "--json"])
record("writer_lock", "passed" if result.returncode == 0 else "failed", "status ok" if result.returncode == 0 else combined_output(result).strip()[:120])

# 10. env check
smoke_fixture = REPO_ROOT / "tests" / "workstation" / "fixtures" / "FAST_DOC.md"
if smoke_fixture.is_file():
    env = os.environ.copy()
    env["GUIYI_SKIP_CODEX_ENV_CHECK"] = "1"
    result = run_cmd(
        [
            "bash",
            str(REPO_ROOT / "scripts" / "env" / "check_task_env.sh"),
            "--task",
            str(smoke_fixture),
            "--stage",
            "route",
            "--worktree",
            str(REPO_ROOT),
            "--quiet",
        ],
        env=env,
    )
    record("env_check", "passed" if result.returncode == 0 else "failed", combined_output(result).strip()[:120])
else:
    record("env_check", "warn", "FAST_DOC fixture missing")

# 11. results writable
results_dir = REPO_ROOT / ".ai" / "results"
results_dir.mkdir(parents=True, exist_ok=True)
probe = results_dir / ".doctor_write_test"
try:
    probe.write_text("ok\n", encoding="utf-8")
    probe.unlink()
    record("results_writable", "passed", str(results_dir))
except OSError as exc:
    record("results_writable", "failed", str(exc))

# 12. not main/master write scenario
branch = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
if branch in {"main", "master"}:
    record("branch_not_main", "failed" if STRICT else "warn", f"current branch={branch}")
else:
    record("branch_not_main", "passed", f"branch={branch}")

# 13. no credential output
leaks = [line for line in output_lines if SECRET_PATTERN.search(line)]
record("no_credential_output", "failed" if leaks else "passed", leaks[0] if leaks else "redaction ok")

summary = {
    "passed": sum(1 for item in checks if item["status"] == "passed"),
    "failed": sum(1 for item in checks if item["status"] == "failed"),
    "warn": sum(1 for item in checks if item["status"] == "warn"),
    "skipped": sum(1 for item in checks if item["status"] == "skipped"),
}
report = {
    "schema_version": 1,
    "repo_root": str(REPO_ROOT),
    "strict": STRICT,
    "summary": summary,
    "checks": checks,
}

if JSON_OUTPUT:
    print(json.dumps(report, ensure_ascii=False, indent=2))
else:
    print("\n".join(output_lines))
    print(
        f"\nSummary: passed={summary['passed']} failed={summary['failed']} "
        f"warn={summary['warn']} skipped={summary['skipped']}"
    )

exit_code = 0
if summary["failed"] > 0:
    exit_code = 1
elif STRICT and summary["warn"] > 0:
    exit_code = 1
raise SystemExit(exit_code)
PY
