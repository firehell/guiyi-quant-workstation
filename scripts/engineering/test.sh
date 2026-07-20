#!/usr/bin/env bash
# Engineering test runner — allowlisted commands only; never push/merge/deploy.
# Zero dependency on WorkBuddy / dispatcher stage machine.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
cd "$REPO_ROOT"

usage() {
  cat <<'EOF'
Usage: scripts/engineering/test.sh [command ...]

With no args, runs a safe default suite:
  git diff --check
  bash -n scripts/engineering/*.sh
  python3 -m pytest -q tests/engineering

Additional args must each be an allowlisted command (no pipes/redirection).
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

is_safe_command() {
  local command="$1"
  [[ "$command" =~ ^[[:space:]]*(git|bash|grep|rg)[[:space:]] || "$command" =~ ^[[:space:]]*python3?[[:space:]]+-m[[:space:]]+pytest[[:space:]] ]] || return 1
  [[ ! "$command" =~ (^|[[:space:]])(rm|sudo|ssh|scp)([[:space:]]|$) ]] || return 1
  [[ ! "$command" =~ git[[:space:]]+(push|merge|reset|checkout|clean|commit) ]] || return 1
  [[ ! "$command" =~ (danger-full-access|dangerously-bypass-approvals-and-sandbox) ]] || return 1
  [[ ! "$command" =~ (^|[^[:alnum:]_])(curl|wget|nc|netcat)([^[:alnum:]_]|$) ]] || return 1
  [[ ! "$command" =~ (\>\>|>|<|\;|\&\&|\|\||\$\() ]] || return 1
  [[ "$command" != *'`'* ]] || return 1
  return 0
}

CMDS=()
if [[ $# -eq 0 ]]; then
  CMDS=(
    "git diff --check"
    "bash -n scripts/engineering/preflight.sh"
    "bash -n scripts/engineering/test.sh"
    "bash -n scripts/engineering/check-secrets.sh"
    "bash -n scripts/engineering/runtime-health.sh"
    "bash -n scripts/engineering/production-write-check.sh"
    "python3 -m pytest -q tests/engineering"
  )
else
  for arg in "$@"; do
    CMDS+=("$arg")
  done
fi

overall=0
index=0
for command in "${CMDS[@]}"; do
  index=$((index + 1))
  if ! is_safe_command "$command"; then
    echo "[REJECTED] unsafe test command: $command" >&2
    overall=1
    continue
  fi
  echo "[TEST $index] $command"
  set +e
  bash --noprofile --norc -c "$command"
  rc=$?
  set -e
  if [[ $rc -ne 0 ]]; then
    echo "[FAIL] exit=$rc" >&2
    overall=1
  else
    echo "[OK]"
  fi
done

[[ $overall -eq 0 ]] && echo "[OK] engineering tests passed" || echo "[FAIL] engineering tests failed" >&2
exit "$overall"
