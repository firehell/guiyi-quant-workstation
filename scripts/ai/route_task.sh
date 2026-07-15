#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
source "$SCRIPT_DIR/_work_level_lib.sh"

usage() {
  cat <<'EOF'
Usage:
  scripts/ai/route_task.sh <TASK_FILE> <STAGE> [--json] [--explain]
  scripts/ai/route_task.sh --task <TASK_ID> <STAGE> [--json] [--explain]

Stages: plan, dev, fix, test, review, result
EOF
}

TASK_ID=""
TASK_FILE=""
STAGE=""
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task)
      TASK_ID="${2:-}"
      shift 2
      ;;
    --json|--explain)
      EXTRA_ARGS+=("$1")
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [[ -z "$TASK_FILE" && -z "$TASK_ID" ]]; then
        TASK_FILE="$1"
      elif [[ -z "$STAGE" ]]; then
        STAGE="$1"
      else
        echo "Unexpected argument: $1" >&2
        usage >&2
        exit 2
      fi
      shift
      ;;
  esac
done

cd "$REPO_ROOT"

if [[ -n "$TASK_ID" ]]; then
  TASK_FILE="$(resolve_task_file "$TASK_ID" || true)"
  [[ -n "$TASK_FILE" ]] || { echo "TASK not found: $TASK_ID" >&2; exit 4; }
elif [[ -n "$TASK_FILE" && ! -f "$TASK_FILE" ]]; then
  RESOLVED_TASK_FILE="$(resolve_task_file "$TASK_FILE" || true)"
  if [[ -n "$RESOLVED_TASK_FILE" ]]; then
    TASK_FILE="$RESOLVED_TASK_FILE"
  fi
fi

[[ -n "$TASK_FILE" && -n "$STAGE" ]] || { usage >&2; exit 2; }
[[ -f "$TASK_FILE" ]] || { echo "TASK file not found: $TASK_FILE" >&2; exit 4; }

python3 "$SCRIPT_DIR/lib/route_task.py" "$TASK_FILE" "$STAGE" "${EXTRA_ARGS[@]}"
