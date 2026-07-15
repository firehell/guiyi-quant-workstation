#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel)"

TASK_ID=""
BUNDLE=""
OUTPUT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task) TASK_ID="${2:-}"; shift 2 ;;
    --bundle) BUNDLE="${2:-}"; shift 2 ;;
    --output) OUTPUT="${2:-}"; shift 2 ;;
    -h|--help)
      echo "Usage: scripts/ai/make_delivery_summary.sh --task <TASK_ID> [--bundle <json>] [--output <md>]"
      exit 0
      ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$TASK_ID" ]] || { echo "--task is required" >&2; exit 2; }

OUT_DIR="$REPO_ROOT/.ai/results/$TASK_ID"
[[ -n "$OUTPUT" ]] || OUTPUT="$OUT_DIR/delivery_summary.md"

args=(delivery --task "$TASK_ID" --repo-root "$REPO_ROOT" --output "$OUTPUT")
[[ -n "$BUNDLE" ]] && args+=(--bundle "$BUNDLE")

export PYTHONPATH="$SCRIPT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}"
python3 "$SCRIPT_DIR/lib/github_result_sync.py" "${args[@]}" >/dev/null
echo "[OK] Delivery summary: ${OUTPUT#$REPO_ROOT/}"
