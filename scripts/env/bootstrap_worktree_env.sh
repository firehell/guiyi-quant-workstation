#!/usr/bin/env bash
# ── Bootstrap Worktree Environment (WS-V2-006 G5) ────────────────────────────
# Creates a scoped .env file for a task worktree in three modes:
#   audit   — read-only DB access, no write credentials
#   dev     — workspace-write with limited env keys (whitelisted)
#   runtime — full runtime env (requires explicit unlock)
#
# Never prints variable values. Never copies the full production .env.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || echo "$SCRIPT_DIR/..")"

WORKTREE=""
MODE="audit"
SOURCE_ENV="${GUIYI_ENV_SOURCE:-$REPO_ROOT/.env}"
APPLY=false
QUIET=false
UNLOCK_RUNTIME=false
CONFIRM_PRODUCTION=false

usage() {
  cat <<'EOF'
Usage: scripts/env/bootstrap_worktree_env.sh --worktree <path> [options]

Modes (--mode):
  audit    Read-only DB access only. No write credentials. (default)
  dev      Workspace-write with whitelisted env keys.
  runtime  Full runtime environment. Requires --unlock-runtime.

Options:
  --source <path>        Source .env file (default: REPO_ROOT/.env)
  --apply                Write the scoped .env; default is dry-run
  --quiet                Print less
  --unlock-runtime       Allow runtime mode (explicit unlock required)
  -h, --help             Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --worktree) WORKTREE="${2:-}"; shift 2 ;;
    --mode) MODE="${2:-audit}"; shift 2 ;;
    --source) SOURCE_ENV="${2:-}"; shift 2 ;;
    --apply) APPLY=true; shift ;;
    --dry-run) APPLY=false; shift ;;
    --quiet) QUIET=true; shift ;;
    --unlock-runtime) UNLOCK_RUNTIME=true; shift ;;
    --confirm-production) CONFIRM_PRODUCTION=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

# Validate mode
case "$MODE" in
  audit|dev|runtime) ;;
  *) echo "Invalid mode: $MODE (must be audit/dev/runtime)" >&2; exit 2 ;;
esac

# Runtime requires explicit unlock
if [[ "$MODE" == "runtime" && "$UNLOCK_RUNTIME" != true ]]; then
  echo "Runtime mode requires --unlock-runtime for safety." >&2
  echo "This prevents accidental full-env exposure." >&2
  exit 3
fi

if [[ -z "$WORKTREE" ]]; then
  WORKTREE="$REPO_ROOT"
fi

WORKTREE="$(cd "$WORKTREE" 2>/dev/null && pwd -P || true)"
[[ -n "$WORKTREE" && -d "$WORKTREE" ]] || { echo "Worktree missing: ${WORKTREE:-<empty>}" >&2; exit 4; }

SOURCE_ENV_EXPANDED="${SOURCE_ENV/#\~/$HOME}"
if [[ "$SOURCE_ENV_EXPANDED" != /* ]]; then
  SOURCE_ENV_EXPANDED="$(cd "$(dirname "$SOURCE_ENV_EXPANDED")" 2>/dev/null && pwd -P)/$(basename "$SOURCE_ENV_EXPANDED")"
fi
[[ -f "$SOURCE_ENV_EXPANDED" ]] || { echo "Env source missing: $SOURCE_ENV" >&2; exit 4; }

# ── Filter .env content ─────────────────────────────────────────────────────

filter_env() {
  local mode="$1"
  local allowed_keys
  # Build a pipe-delimited key list for grep matching
  case "$mode" in
    audit)
      allowed_keys="APP_ENV|GUIYI_DATA_ROOT|GUIYI_LOG_DIR|RQDATA_USERNAME|GUIYI_RQDATA_DIR|GUIYI_DUCKDB_DIR|PYTHONPATH|PATH"
      ;;
    dev)
      allowed_keys="APP_ENV|GUIYI_DATA_ROOT|GUIYI_LOG_DIR|RQDATA_USERNAME|GUIYI_RQDATA_DIR|GUIYI_DUCKDB_DIR|PYTHONPATH|PATH|RQDATA_TOKEN|GUIYI_PARQUET_DIR|GUIYI_DB_URL|GUIYI_TASK_DIR|GUIYI_WORKTREE_ROOT|GUIYI_AI_SCRIPT_DIR|GUIYI_CACHE_DIR"
      ;;
    runtime)
      allowed_keys="APP_ENV|GUIYI_DATA_ROOT|GUIYI_LOG_DIR|RQDATA_USERNAME|GUIYI_RQDATA_DIR|GUIYI_DUCKDB_DIR|PYTHONPATH|PATH|RQDATA_TOKEN|GUIYI_PARQUET_DIR|GUIYI_DB_URL|GUIYI_TASK_DIR|GUIYI_WORKTREE_ROOT|GUIYI_AI_SCRIPT_DIR|GUIYI_CACHE_DIR|GUIYI_DB_WRITE_URL|GUIYI_REDIS_URL|GUIYI_NOTIFICATION_WEBHOOK|GUIYI_LIVE_CHECKPOINT_DIR|GUIYI_AFTER_MARKET_ARCHIVE_DIR|GUIYI_MAIN_CONTRACT_MAP_DIR"
      ;;
  esac

  while IFS= read -r line; do
    local stripped="${line#"${line%%[![:space:]]*}"}"
    # Keep comments and blank lines
    if [[ -z "$stripped" || "$stripped" == \#* ]]; then
      continue
    fi
    # Parse key
    local key="${line%%=*}"
    if [[ "$key" == "export "* ]]; then
      key="${key#export }"
    fi
    key="$(printf '%s' "$key" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
    # Check if key is in the allowed set
    if printf '%s' "$key" | grep -qE "^(${allowed_keys})$"; then
      local value="${line#*=}"
      printf 'export %s=<FILTERED>\n' "$key"
    fi
  done < "$SOURCE_ENV_EXPANDED"
}

# ── Generate scoped .env ─────────────────────────────────────────────────────

TARGET="$WORKTREE/.env"

generate_scoped_env() {
  local mode="$1"
  local header
  header="# WORKTREE ENV — mode=$mode — generated $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  header+=$'\n# DO NOT EDIT MANUALLY. Use bootstrap_worktree_env.sh --apply'
  header+=$'\n# Source: $SOURCE_ENV (not copied — whitelisted keys only)'
  header+=$'\n'

  local content
  content="$header"

  case "$mode" in
    audit)
      content+="$(filter_env "audit")"
      content+=$'\n# --- Audit mode: read-only DB only ---'
      content+=$'\nexport GUIYI_DB_MODE=read_only'
      ;;
    dev)
      content+="$(filter_env "dev")"
      content+=$'\n# --- Dev mode: workspace-write allowed ---'
      content+=$'\nexport GUIYI_DB_MODE=read_only'
      ;;
    runtime)
      content+="$(filter_env "runtime")"
      content+=$'\n# --- Runtime mode: full access (UNLOCKED) ---'
      content+=$'\nexport GUIYI_DB_MODE=read_write'
      ;;
  esac

  printf '%s\n' "$content"
}

# ── Main ─────────────────────────────────────────────────────────────────────

if [[ "${APP_ENV:-}" == "production" && "$CONFIRM_PRODUCTION" != true ]]; then
  echo "Production env requires explicit --confirm-production" >&2
  exit 1
fi

if [[ -e "$TARGET" || -L "$TARGET" ]]; then
  echo "Target .env already exists: $TARGET" >&2
  echo "Remove it manually first or use a different worktree." >&2
  exit 1
fi

if [[ "$APPLY" != true ]]; then
  echo "[DRY-RUN] Would create scoped .env for mode=$MODE"
  echo "  worktree: $WORKTREE"
  echo "  source:   $SOURCE_ENV_EXPANDED"
  echo "  target:   $TARGET"
  echo "---"
  generate_scoped_env "$MODE"
  exit 0
fi

generate_scoped_env "$MODE" > "$TARGET"
chmod 600 "$TARGET"

if [[ "$QUIET" != true ]]; then
  echo "[OK] Created scoped .env: $TARGET"
  echo "  mode:     $MODE"
  echo "  worktree: $WORKTREE"

  key_count="$(grep -c '^export ' "$TARGET" 2>/dev/null || echo 0)"
  echo "  keys:     $key_count (whitelisted, values never printed)"
fi
