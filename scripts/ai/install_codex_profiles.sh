#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
PROFILE_DIR="$REPO_ROOT/config/codex/profiles"
CODEX_TARGET_HOME="${CODEX_HOME:-$HOME/.codex}"

DRY_RUN=false
VERIFY=false
BACKUP_AND_INSTALL=false

usage() {
  cat <<'EOF'
Usage:
  scripts/ai/install_codex_profiles.sh [--dry-run] [--backup-and-install] [--verify]

Options:
  --dry-run              Show what would be installed without writing files.
  --backup-and-install   Back up existing profile files before installing.
  --verify               Verify templates and installed files match.
  -h, --help             Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --verify)
      VERIFY=true
      shift
      ;;
    --backup-and-install)
      BACKUP_AND_INSTALL=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$VERIFY" == true && "$DRY_RUN" == true ]]; then
  echo "--verify cannot be combined with --dry-run" >&2
  exit 2
fi

if [[ "$VERIFY" == true && "$BACKUP_AND_INSTALL" == true ]]; then
  echo "--verify cannot be combined with --backup-and-install" >&2
  exit 2
fi

expected_profiles=(
  "guiyi-fast.config.toml"
  "guiyi-standard.config.toml"
  "guiyi-deep.config.toml"
  "guiyi-critical.config.toml"
)

blocked_terms=(
  'api[_-]?''key'
  'to''ken'
  'pass''word'
  'sec''ret'
  'lic''ense'
  'coo''kie'
  'cred''ential'
  'auth[_-]?''to''ken'
  'web''hook'
)
blocked_pattern="$(IFS='|'; echo "${blocked_terms[*]}")"

check_template() {
  local src="$1"
  local name
  name="$(basename "$src")"

  [[ -f "$src" ]] || {
    echo "[FAIL] missing template: $name" >&2
    return 1
  }

  if grep -Eiq "($blocked_pattern)" "$src"; then
    echo "[FAIL] sensitive field detected in template: $name" >&2
    return 1
  fi
}

verify_profiles() {
  local failed=false
  for name in "${expected_profiles[@]}"; do
    local src="$PROFILE_DIR/$name"
    local dst="$CODEX_TARGET_HOME/$name"

    check_template "$src" || failed=true
    if [[ ! -f "$dst" ]]; then
      echo "[FAIL] not installed: $name"
      failed=true
      continue
    fi
    if cmp -s "$src" "$dst"; then
      echo "[OK] verified: $name"
    else
      echo "[FAIL] differs: $name"
      failed=true
    fi
  done

  [[ "$failed" == false ]]
}

install_profiles() {
  local timestamp
  timestamp="$(date +%Y%m%d%H%M%S)"

  if [[ "$DRY_RUN" == false ]]; then
    mkdir -p "$CODEX_TARGET_HOME"
  fi

  for name in "${expected_profiles[@]}"; do
    local src="$PROFILE_DIR/$name"
    local dst="$CODEX_TARGET_HOME/$name"

    check_template "$src"

    if [[ "$DRY_RUN" == true ]]; then
      if [[ -e "$dst" && "$BACKUP_AND_INSTALL" == true ]]; then
        echo "[DRY-RUN] would back up and install: $name"
      elif [[ -e "$dst" ]]; then
        echo "[DRY-RUN] would refuse existing file: $name"
      else
        echo "[DRY-RUN] would install: $name"
      fi
      continue
    fi

    if [[ -e "$dst" ]]; then
      if [[ "$BACKUP_AND_INSTALL" != true ]]; then
        echo "[FAIL] exists, refusing to overwrite: $name" >&2
        echo "       rerun with --backup-and-install to back up and replace" >&2
        exit 5
      fi
      local backup="$dst.bak.$timestamp"
      cp "$dst" "$backup"
      echo "[OK] backed up: $(basename "$backup")"
    fi

    cp "$src" "$dst"
    echo "[OK] installed: $name"
  done
}

[[ -d "$PROFILE_DIR" ]] || {
  echo "Profile template directory not found: config/codex/profiles" >&2
  exit 4
}

if [[ "$VERIFY" == true ]]; then
  verify_profiles
else
  install_profiles
fi
