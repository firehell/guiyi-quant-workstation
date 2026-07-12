#!/usr/bin/env bash
# Link a TASK worktree to an existing env file. Defaults to dry-run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
WORKTREE=""
SOURCE_ENV="${GUIYI_ENV_SOURCE:-}"
APPLY=false
REPLACE_LINK=false
CONFIRM_PRODUCTION=false
QUIET=false

usage() {
  cat <<'EOF'
Usage: scripts/env/bootstrap_worktree_env.sh --worktree <path> [options]

Options:
  --source <path>          Existing env file to link (default: GUIYI_ENV_SOURCE)
  --apply                  Perform the symlink change; default is dry-run
  --replace-link           Replace an existing .env symlink only
  --confirm-production     Allow running when APP_ENV=production is already set
  --quiet                  Print less
  -h, --help               Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --worktree) WORKTREE="${2:-}"; shift 2 ;;
    --source) SOURCE_ENV="${2:-}"; shift 2 ;;
    --apply) APPLY=true; shift ;;
    --dry-run) APPLY=false; shift ;;
    --replace-link) REPLACE_LINK=true; shift ;;
    --confirm-production) CONFIRM_PRODUCTION=true; shift ;;
    --quiet) QUIET=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$WORKTREE" ]]; then
  WORKTREE="$REPO_ROOT"
fi
if [[ -z "$SOURCE_ENV" ]]; then
  SOURCE_ENV="$REPO_ROOT/.env"
fi

WORKTREE="$(cd "$WORKTREE" 2>/dev/null && pwd -P || true)"
[[ -n "$WORKTREE" && -d "$WORKTREE" ]] || { echo "Worktree missing: ${WORKTREE:-<empty>}" >&2; exit 4; }

SOURCE_ENV_EXPANDED="${SOURCE_ENV/#\~/$HOME}"
if [[ "$SOURCE_ENV_EXPANDED" != /* ]]; then
  SOURCE_ENV_EXPANDED="$(cd "$(dirname "$SOURCE_ENV_EXPANDED")" 2>/dev/null && pwd -P)/$(basename "$SOURCE_ENV_EXPANDED")"
fi
[[ -f "$SOURCE_ENV_EXPANDED" ]] || { echo "Env source missing: $SOURCE_ENV" >&2; exit 4; }

if [[ "${APP_ENV:-}" == "production" && "$CONFIRM_PRODUCTION" != true ]]; then
  echo "Production env requires explicit --confirm-production" >&2
  exit 1
fi

TARGET="$WORKTREE/.env"
if [[ -e "$TARGET" || -L "$TARGET" ]]; then
  if [[ -L "$TARGET" && "$REPLACE_LINK" == true ]]; then
    :
  else
    echo "Target .env already exists; refusing to overwrite: $TARGET" >&2
    exit 1
  fi
fi

if [[ "$APPLY" != true ]]; then
  if [[ "$QUIET" != true ]]; then
    printf '[DRY-RUN] would link worktree .env\n'
    printf '  worktree: %s\n' "$WORKTREE"
    printf '  source:   %s\n' "$SOURCE_ENV_EXPANDED"
    printf '  target:   %s\n' "$TARGET"
  fi
  exit 0
fi

if [[ -L "$TARGET" && "$REPLACE_LINK" == true ]]; then
  rm "$TARGET"
fi
ln -s "$SOURCE_ENV_EXPANDED" "$TARGET"
chmod 600 "$SOURCE_ENV_EXPANDED" 2>/dev/null || true

if [[ "$QUIET" != true ]]; then
  printf '[OK] linked worktree .env\n'
  printf '  worktree: %s\n' "$WORKTREE"
  printf '  source:   %s\n' "$SOURCE_ENV_EXPANDED"
  printf '  target:   %s\n' "$TARGET"
fi
