#!/usr/bin/env bash
# Compatibility shim — TASK env gate migrated to scripts/engineering/*.
# Behavior: fail-closed preflight; never prints secret values.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
ENG="$REPO_ROOT/scripts/engineering"

if [[ "${GUIYI_SUPPRESS_DEPRECATED_HINT:-}" != "1" ]]; then
  echo "[DEPRECATED] scripts/env/check_task_env.sh — use scripts/engineering/preflight.sh + check-secrets.sh" >&2
fi

# Accept old flags but ignore TASK-specific parsing (control plane removed).
STRICT=false
QUIET=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --task|--stage|--worktree|--repo-root|--output) shift 2 ;;
    --json) shift ;;
    --quiet) QUIET=true; shift ;;
    --strict) STRICT=true; shift ;;
    -h|--help)
      echo "Usage: scripts/env/check_task_env.sh [legacy flags ignored] → delegates to engineering/preflight.sh"
      exit 0
      ;;
    *) shift ;;
  esac
done

ARGS=()
[[ "$STRICT" == true ]] && ARGS+=(--strict)
if [[ "$QUIET" == true ]]; then
  bash "$ENG/preflight.sh" "${ARGS[@]}" >/dev/null
else
  bash "$ENG/preflight.sh" "${ARGS[@]}"
fi
bash "$ENG/check-secrets.sh" >/dev/null
