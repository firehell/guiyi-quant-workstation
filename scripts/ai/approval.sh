#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || echo "$(cd "$SCRIPT_DIR/../.." && pwd)")"

usage() {
  cat <<'EOF'
Usage: scripts/ai/approval.sh <COMMAND> [OPTIONS]

COMMAND:
  create   Generate a V3 approval record with secret scanning
  verify   12-step gate check (task/plan/hash/expiry/consumed/scope)
  consume  Mark a one_time approval as consumed
  status   Report approval status (VALID|EXPIRED|CONSUMED)

Try 'scripts/ai/approval.sh <COMMAND> --help' for per-command options.
EOF
}

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 2
fi

COMMAND="$1"
shift

case "$COMMAND" in
  create|verify|consume|status)
    PYTHONPATH="$SCRIPT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}" \
      python3 -m approval_manager "$COMMAND" "$@"
    ;;
  -h|--help)
    usage
    ;;
  *)
    echo "Unknown command: $COMMAND" >&2
    usage >&2
    exit 2
    ;;
esac
