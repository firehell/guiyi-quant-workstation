#!/usr/bin/env bash
# Production write gate — fail-closed unless explicit confirmation.
# Does not perform writes; only validates that confirmation is present.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
cd "$REPO_ROOT"

CONFIRM=false
ACTION="unspecified"

usage() {
  cat <<'EOF'
Usage: scripts/engineering/production-write-check.sh --action <name> [--confirm-production-write]

Fail-closed: without --confirm-production-write, exit 3.
This script never writes production data itself.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --action) ACTION="${2:-}"; shift 2 ;;
    --confirm-production-write) CONFIRM=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$ACTION" || "$ACTION" == "unspecified" ]]; then
  echo "[FAIL] --action is required" >&2
  exit 2
fi

# Never print APP_ENV value if it looks sensitive; only pass/fail labels.
APP_ENV_LABEL="${APP_ENV:-unset}"
case "$APP_ENV_LABEL" in
  production|prod)
    ENV_IS_PROD=true
    ;;
  *)
    ENV_IS_PROD=false
    ;;
esac

if [[ "$CONFIRM" != true ]]; then
  echo "[FAIL] production write blocked: missing --confirm-production-write" >&2
  echo "action=$ACTION app_env=$APP_ENV_LABEL" >&2
  exit 3
fi

echo "[OK] production write confirmation present"
echo "action=$ACTION app_env=$APP_ENV_LABEL confirmed=true"
if [[ "$ENV_IS_PROD" == true ]]; then
  echo "[WARN] APP_ENV indicates production; proceed only with user approval"
fi
exit 0
