#!/usr/bin/env bash
# Runtime health — read-only probes; never starts services or writes data.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
cd "$REPO_ROOT"

JSON_OUTPUT=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --json) JSON_OUTPUT=true; shift ;;
    -h|--help)
      echo "Usage: scripts/engineering/runtime-health.sh [--json]"
      exit 0
      ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

python3 - "$REPO_ROOT" "$JSON_OUTPUT" <<'PY'
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

repo = Path(sys.argv[1]).resolve()
json_out = sys.argv[2] == "true"
checks: list[dict[str, str]] = []


def record(name: str, status: str, detail: str = "") -> None:
    checks.append({"name": name, "status": status, "detail": detail})


def port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# Prefer existing local healthcheck if present (read-only flags).
health_script = repo / "scripts" / "dev-healthcheck.sh"
if health_script.is_file():
    env = os.environ.copy()
    # Do not start services from this entrypoint.
    result = subprocess.run(
        ["bash", str(health_script), "--json", "--no-start"],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    # Never echo full stdout if it might contain secrets; summarize only.
    if result.returncode == 0:
        record("dev_healthcheck", "passed", "dev-healthcheck.sh --json --no-start")
    else:
        record(
            "dev_healthcheck",
            "warn",
            f"exit={result.returncode} (services may be down; read-only probe)",
        )
else:
    record("dev_healthcheck", "warn", "scripts/dev-healthcheck.sh missing")

api_up = port_open("127.0.0.1", 8000)
web_up = port_open("127.0.0.1", 5173)
record("api_port_8000", "passed" if api_up else "warn", "open" if api_up else "closed")
record("web_port_5173", "passed" if web_up else "warn", "open" if web_up else "closed")

if api_up:
    try:
        with urlopen("http://127.0.0.1:8000/health", timeout=1.5) as resp:
            code = getattr(resp, "status", 200)
            record("api_health_http", "passed" if 200 <= int(code) < 300 else "warn", f"http={code}")
    except URLError as exc:
        # Fallback common paths
        try:
            with urlopen("http://127.0.0.1:8000/api/health", timeout=1.5) as resp:
                code = getattr(resp, "status", 200)
                record("api_health_http", "passed" if 200 <= int(code) < 300 else "warn", f"http={code}")
        except URLError:
            record("api_health_http", "warn", f"unreachable ({type(exc).__name__})")
else:
    record("api_health_http", "warn", "skipped (port closed)")

failed = sum(1 for c in checks if c["status"] == "failed")
report = {
    "schema_version": 1,
    "tool": "scripts/engineering/runtime-health.sh",
    "readonly": True,
    "summary": {
        "failed": failed,
        "warn": sum(1 for c in checks if c["status"] == "warn"),
        "passed": sum(1 for c in checks if c["status"] == "passed"),
    },
    "checks": checks,
}

if json_out:
    print(json.dumps(report, ensure_ascii=False, indent=2))
else:
    for c in checks:
        prefix = {"passed": "[OK]", "failed": "[FAIL]", "warn": "[WARN]"}.get(c["status"], "[?]")
        detail = f": {c['detail']}" if c["detail"] else ""
        print(f"{prefix} {c['name']}{detail}")
    print(
        f"\nSummary: passed={report['summary']['passed']} "
        f"failed={failed} warn={report['summary']['warn']}"
    )

# Read-only health never fails the build solely because services are down.
sys.exit(1 if failed else 0)
PY
