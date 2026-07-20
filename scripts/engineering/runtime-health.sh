#!/usr/bin/env bash
# Runtime health — read-only probes; validates /health JSON contract.
# Never starts services or writes data. Never prints sensitive payload fields.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
cd "$REPO_ROOT"

JSON_OUTPUT=false
STRICT=false
HOST="127.0.0.1"
PORT="8000"

usage() {
  cat <<'EOF'
Usage: scripts/engineering/runtime-health.sh [--json] [--strict] [--host HOST] [--port PORT]

Probes /health (then /api/health). Validates JSON contract:
  status == "ok", readonly is true, service is non-empty.

API reachable but contract wrong → failed.
API not started → warn (default); --strict → failed.
Top-level report readonly does NOT substitute for API payload readonly.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json) JSON_OUTPUT=true; shift ;;
    --strict) STRICT=true; shift ;;
    --host)
      [[ $# -ge 2 ]] || { echo "Missing value for --host" >&2; exit 2; }
      HOST="$2"; shift 2
      ;;
    --port)
      [[ $# -ge 2 ]] || { echo "Missing value for --port" >&2; exit 2; }
      PORT="$2"; shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

export RUNTIME_HEALTH_HOST="$HOST"
export RUNTIME_HEALTH_PORT="$PORT"
export RUNTIME_HEALTH_STRICT="$STRICT"
export RUNTIME_HEALTH_JSON="$JSON_OUTPUT"
export RUNTIME_HEALTH_REPO="$REPO_ROOT"

python3 - <<'PY'
from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

repo = Path(os.environ["RUNTIME_HEALTH_REPO"]).resolve()
host = os.environ.get("RUNTIME_HEALTH_HOST", "127.0.0.1")
port = int(os.environ.get("RUNTIME_HEALTH_PORT", "8000"))
strict = os.environ.get("RUNTIME_HEALTH_STRICT", "false") == "true"
json_out = os.environ.get("RUNTIME_HEALTH_JSON", "false") == "true"
checks: list[dict[str, str]] = []


def record(name: str, status: str, detail: str = "") -> None:
    checks.append({"name": name, "status": status, "detail": detail})


def port_open(timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def safe_detail_from_payload(payload: dict) -> str:
    # Only surface contract fields — never dump arbitrary keys/values.
    status = payload.get("status")
    service = payload.get("service")
    readonly = payload.get("readonly")
    return f"status={status!r} service_set={bool(service)} readonly={readonly!r}"


def validate_payload(payload: object) -> tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "payload_not_object"
    status = payload.get("status")
    service = payload.get("service")
    readonly = payload.get("readonly")
    if status != "ok":
        return False, f"status_not_ok ({safe_detail_from_payload(payload)})"
    if not isinstance(service, str) or not service.strip():
        return False, f"service_empty ({safe_detail_from_payload(payload)})"
    if readonly is not True:
        return False, f"readonly_not_true ({safe_detail_from_payload(payload)})"
    return True, safe_detail_from_payload(payload)


def fetch_json(url: str) -> tuple[object | None, str]:
    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=1.5) as resp:
            code = getattr(resp, "status", 200)
            raw = resp.read(4096).decode("utf-8", errors="replace")
            if not (200 <= int(code) < 300):
                return None, f"http={code}"
            try:
                return json.loads(raw), f"http={code}"
            except json.JSONDecodeError:
                return None, f"http={code}; non_json_body"
    except HTTPError as exc:
        return None, f"http_error={exc.code}"
    except URLError as exc:
        return None, f"url_error={type(exc).__name__}"
    except OSError as exc:
        return None, f"os_error={type(exc).__name__}"


api_up = port_open()
down_status = "failed" if strict else "warn"
record(
    "api_port",
    "passed" if api_up else down_status,
    f"{host}:{port} {'open' if api_up else 'closed'}",
)

if not api_up:
    record("api_health_contract", down_status, "skipped (port closed)")
else:
    paths = ("/health", "/api/health")
    last_detail = ""
    validated = False
    for path in paths:
        url = f"http://{host}:{port}{path}"
        payload, meta = fetch_json(url)
        if payload is None:
            last_detail = f"{path}: {meta}"
            continue
        ok, detail = validate_payload(payload)
        if ok:
            record("api_health_contract", "passed", f"{path}; {meta}; {detail}")
            validated = True
            break
        last_detail = f"{path}: contract_failed; {meta}; {detail}"
        # Reachable but wrong contract → failed (not warn), even without --strict.
        record("api_health_contract", "failed", last_detail)
        validated = True  # recorded failure; stop
        break
    if not validated:
        # Tried paths but none returned parseable JSON object with contract.
        record("api_health_contract", "failed", last_detail or "unreachable_or_non_json")

failed = sum(1 for c in checks if c["status"] == "failed")
# Top-level readonly is about THIS tool being read-only; it must NOT substitute
# for API payload.readonly (validated separately above).
report = {
    "schema_version": 1,
    "tool": "scripts/engineering/runtime-health.sh",
    "readonly": True,
    "strict": strict,
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

sys.exit(1 if failed else 0)
PY
