#!/usr/bin/env bash
# Bootstrap a local workstation task from a GitHub Issue, Issue URL, or TASK_ID.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"

ISSUE_ARG=""
DRY_RUN=false
JSON_OUTPUT=false
WORKTREE_ROOT=""
REMOTE="origin"

usage() {
  cat <<'EOF'
Usage: scripts/ai/bootstrap_github_task.sh --issue <#N|N|issue-url|TASK_ID> [options]

Options:
  --issue <value>          Issue number, #N, GitHub Issue URL, or TASK_ID.
  --dry-run                Resolve and validate only; do not fetch, create branch/worktree, or write runtime.
  --json                   Print JSON result.
  --worktree-root <path>   Override GUIYI worktree root.
  --remote <name>          Git remote name for task branch fetch (default: origin).
  -h, --help               Show help.

This command reads only firehell/guiyi-quant-workstation through gh.
It never writes main, merges, deploys, closes Issues, or enables auto-merge.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --issue) ISSUE_ARG="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --json) JSON_OUTPUT=true; shift ;;
    --worktree-root) WORKTREE_ROOT="${2:-}"; [[ -n "$WORKTREE_ROOT" ]] || { echo "--worktree-root requires a value" >&2; exit 2; }; shift 2 ;;
    --remote) REMOTE="${2:-}"; [[ -n "$REMOTE" ]] || { echo "--remote requires a value" >&2; exit 2; }; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$ISSUE_ARG" ]] || { usage >&2; exit 2; }

args=(
  --issue "$ISSUE_ARG"
  --repo-root "$REPO_ROOT"
  --remote "$REMOTE"
)

[[ "$DRY_RUN" == true ]] && args+=(--dry-run)
[[ "$JSON_OUTPUT" == true ]] && args+=(--json)
[[ -n "$WORKTREE_ROOT" ]] && args+=(--worktree-root "$WORKTREE_ROOT")

export PYTHONPATH="$SCRIPT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}"
python3 "$SCRIPT_DIR/lib/github_task_resolver.py" "${args[@]}"
