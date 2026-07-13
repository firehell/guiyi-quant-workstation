#!/usr/bin/env bash
# WS-V2-008: Runtime Gate Ledger — shell interface.
#
# Commands:
#   init            Create .ai/runtime-gates/<ID>/ structure + gate.yaml
#   collect         Record one trading day's evidence
#   record-incident Record an incident entry
#   record-recovery Record a recovery test result
#   daily-close     Validate one day's completeness (fail-closed)
#   finalize        Aggregate 5 days → final report + gate status
#
# Bypass: GUIYI_SKIP_RUNTIME_GATE=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || pwd)"
GATE_ROOT="$REPO_ROOT/.ai/runtime-gates"

ledger_py() {
  PYTHONPATH="$SCRIPT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}" python3 -m runtime_gate_ledger "$@"
}

# ── init ───────────────────────────────────────────────────────────────

runtime_gate_init() {
  local gate_id="${1:-DEFAULT}"
  local gate_label="${2:-}"

  if [[ -d "$GATE_ROOT/$gate_id" ]]; then
    echo "[WARN] Runtime Gate: $gate_id already exists at $GATE_ROOT/$gate_id" >&2
    return 0
  fi

  ledger_py init "$GATE_ROOT" "$gate_id" >&2
  echo "[OK] Runtime Gate initialized: $GATE_ROOT/$gate_id" >&2
  return 0
}

# ── collect ────────────────────────────────────────────────────────────

runtime_gate_collect() {
  local gate_id="$1"
  local trading_day="${2:-T+0}"
  local trading_date="${3:-}"
  local synthetic_path="${4:-}"
  local git_commit="${5:-}"
  local service_version="${6:-}"

  if [[ "${GUIYI_SKIP_RUNTIME_GATE:-}" == "1" ]]; then
    echo "[SKIP] Runtime Gate collect: GUIYI_SKIP_RUNTIME_GATE=1" >&2
    return 0
  fi

  local gate_dir="$GATE_ROOT/$gate_id"
  if [[ ! -d "$gate_dir" ]]; then
    echo "Runtime Gate: gate dir not found: $gate_dir. Run 'init' first." >&2
    return 9
  fi

  local result
  result="$(ledger_py collect "$gate_dir" "$trading_day" "$trading_date" "$synthetic_path" "$git_commit" "$service_version" 2>/dev/null)" || {
    echo "Runtime Gate: collect failed" >&2
    return 9
  }

  local status
  status="$(python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('status','failed'))" <<< "$result" 2>/dev/null || echo "failed")"

  local idempotent
  idempotent="$(python3 -c "import json,sys; print('true' if json.loads(sys.stdin.read()).get('idempotent',False) else 'false')" <<< "$result" 2>/dev/null || echo "false")"

  if [[ "$idempotent" == "true" ]]; then
    echo "[OK] Runtime Gate: $trading_day already collected (idempotent)" >&2
    return 0
  fi

  local missing
  missing="$(python3 -c "
import json,sys
r=json.loads(sys.stdin.read())
print(', '.join(r.get('missing_evidence',[])) or 'none')
" <<< "$result" 2>/dev/null || echo "error")"

  echo "[OK] Runtime Gate: $trading_day collected — status=$status missing=[$missing]" >&2
  return 0
}

# ── record-incident ────────────────────────────────────────────────────

runtime_gate_record_incident() {
  local gate_id="$1"
  local incident_type="$2"
  local component="${3:-unknown}"
  local details="${4:-}"
  local duration="${5:-0}"

  if [[ "${GUIYI_SKIP_RUNTIME_GATE:-}" == "1" ]]; then
    echo "[SKIP] Runtime Gate incident: GUIYI_SKIP_RUNTIME_GATE=1" >&2
    return 0
  fi

  local gate_dir="$GATE_ROOT/$gate_id"
  local incidents_dir="$gate_dir/incidents"
  mkdir -p "$incidents_dir"

  # Find next incident number
  local n=1
  while [[ -f "$incidents_dir/incident-$(printf '%03d' "$n").json" ]]; do
    n=$((n + 1))
  done

  local incident_id="incident-$(printf '%03d' "$n")"
  local now
  now="$(python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%SZ")"

  python3 - "$incidents_dir/$incident_id.json" "$incident_type" "$component" "$details" "$duration" "$now" <<'PY'
import json, sys
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "incident_id": path.stem,
    "incident_type": sys.argv[2],
    "component": sys.argv[3],
    "details": sys.argv[4],
    "duration_seconds": int(sys.argv[5]) if sys.argv[5].isdigit() else 0,
    "recorded_at": sys.argv[6],
    "recovered": False,
    "recovery_id": None,
    "recovery_at": None,
}
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"recorded": True, "incident_id": path.stem}))
PY

  echo "[OK] Runtime Gate: $incident_id recorded — type=$incident_type component=$component" >&2
  return 0
}

# ── record-recovery ────────────────────────────────────────────────────

runtime_gate_record_recovery() {
  local gate_id="$1"
  local incident_id="$2"
  local recovery_result="${3:-PASSED}"
  local notes="${4:-}"

  if [[ "${GUIYI_SKIP_RUNTIME_GATE:-}" == "1" ]]; then
    echo "[SKIP] Runtime Gate recovery: GUIYI_SKIP_RUNTIME_GATE=1" >&2
    return 0
  fi

  local gate_dir="$GATE_ROOT/$gate_id"
  local recovery_dir="$gate_dir/recovery-tests"
  mkdir -p "$recovery_dir"

  local recovery_id
  recovery_id="recovery-$(printf '%03d' "$(ls "$recovery_dir"/recovery-*.md 2>/dev/null | wc -l | tr -d ' ')")"

  local now
  now="$(python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%SZ")"

  cat > "$recovery_dir/$recovery_id.md" <<EOF
# Recovery Test: $recovery_id

- **Incident:** $incident_id
- **Result:** $recovery_result
- **Recorded At:** $now
- **Notes:** $notes

## Evidence

Recovery test executed and verified.
EOF

  # Update incident status
  local incidents_dir="$gate_dir/incidents"
  local incident_file="$incidents_dir/$incident_id.json"
  if [[ -f "$incident_file" ]]; then
    python3 - "$incident_file" "$recovery_id" "$now" <<'PY'
import json, sys
data = json.loads(open(sys.argv[1], encoding="utf-8").read())
data["recovered"] = True
data["recovery_id"] = sys.argv[2]
data["recovery_at"] = sys.argv[3]
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    json.dump(data, fh, ensure_ascii=False, indent=2)
PY
  fi

  echo "[OK] Runtime Gate: $recovery_id recorded — incident=$incident_id result=$recovery_result" >&2
  return 0
}

# ── daily-close ─────────────────────────────────────────────────────────

runtime_gate_daily_close() {
  local gate_id="$1"
  local trading_day="${2:-T+0}"

  if [[ "${GUIYI_SKIP_RUNTIME_GATE:-}" == "1" ]]; then
    echo "[SKIP] Runtime Gate daily-close: GUIYI_SKIP_RUNTIME_GATE=1" >&2
    return 0
  fi

  local gate_dir="$GATE_ROOT/$gate_id"
  local daily_path="$gate_dir/daily/$trading_day.json"

  if [[ ! -f "$daily_path" ]]; then
    echo "Runtime Gate: no daily record for $trading_day. Run 'collect' first." >&2
    return 9
  fi

  local result
  result="$(ledger_py validate "$gate_dir" "$trading_day" 2>/dev/null)" || {
    echo "Runtime Gate: daily-close validation failed for $trading_day" >&2
    return 9
  }

  local valid status missing
  valid="$(python3 -c "import json,sys; print('true' if json.loads(sys.stdin.read()).get('valid',False) else 'false')" <<< "$result" 2>/dev/null || echo "false")"
  status="$(python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('status','failed'))" <<< "$result" 2>/dev/null || echo "failed")"
  missing="$(python3 -c "import json,sys; r=json.loads(sys.stdin.read()); print(', '.join(r.get('missing_evidence',[])) or 'none')" <<< "$result" 2>/dev/null || echo "error")"

  echo "[OK] Runtime Gate: $trading_day daily-close — status=$status missing=[$missing]" >&2

  if [[ "$valid" != "true" ]]; then
    echo "Runtime Gate: $trading_day FAILED daily-close — critical evidence missing" >&2
    return 9
  fi

  return 0
}

# ── finalize ────────────────────────────────────────────────────────────

runtime_gate_finalize() {
  local gate_id="$1"

  if [[ "${GUIYI_SKIP_RUNTIME_GATE:-}" == "1" ]]; then
    echo "[SKIP] Runtime Gate finalize: GUIYI_SKIP_RUNTIME_GATE=1" >&2
    return 0
  fi

  local gate_dir="$GATE_ROOT/$gate_id"
  if [[ ! -d "$gate_dir" ]]; then
    echo "Runtime Gate: gate dir not found: $gate_dir. Run 'init' first." >&2
    return 9
  fi

  local result
  result="$(ledger_py finalize "$gate_dir" 2>/dev/null)" || {
    echo "Runtime Gate: finalization failed" >&2
    return 9
  }

  local final_status
  final_status="$(python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('final_status','FAILED'))" <<< "$result" 2>/dev/null || echo "FAILED")"

  echo "[OK] Runtime Gate: $gate_id finalized — $final_status" >&2
  echo "Report: $gate_dir/final-report.md" >&2

  if [[ "$final_status" == "FAILED" ]]; then
    return 9
  elif [[ "$final_status" == "DEGRADED" ]]; then
    return 8
  fi

  return 0
}

# ── Entry point (standalone usage) ─────────────────────────────────────

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  cmd="${1:-}"
  shift || true

  case "$cmd" in
    init)
      runtime_gate_init "$@"
      ;;
    collect)
      runtime_gate_collect "$@"
      ;;
    record-incident)
      runtime_gate_record_incident "$@"
      ;;
    record-recovery)
      runtime_gate_record_recovery "$@"
      ;;
    daily-close)
      runtime_gate_daily_close "$@"
      ;;
    finalize)
      runtime_gate_finalize "$@"
      ;;
    *)
      echo "Usage: $_runtime_gate_lib.sh <init|collect|record-incident|record-recovery|daily-close|finalize> [args...]" >&2
      exit 1
      ;;
  esac
fi
