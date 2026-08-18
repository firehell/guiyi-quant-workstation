#!/usr/bin/env bash
set -euo pipefail

PINNED_COMMIT="981bd14e238302b2a0e206cb5f28e8e2505bb874"
UPSTREAM_URL="https://github.com/bladydora/WeChat-Courier-macOS.git"
MODE="${1:-}"
ROOT="${GUIYI_WECHAT_COURIER_ROOT:-}"
GIT_BIN="/usr/bin/git"
PYTHON_BIN="/usr/bin/python3"

if [[ "${GUIYI_WECHAT_COURIER_TESTING:-0}" == "1" ]]; then
  GIT_BIN="${GUIYI_WECHAT_COURIER_GIT_BIN:-$GIT_BIN}"
  PYTHON_BIN="${GUIYI_WECHAT_COURIER_PYTHON_BIN:-$PYTHON_BIN}"
fi

[[ "$MODE" == "--check" || "$MODE" == "--confirm-install" ]] || {
  printf 'usage: %s [--check|--confirm-install]\n' "$0" >&2
  exit 2
}

check_installation() {
  local commit dirty
  if [[ -z "$ROOT" || ! -e "$ROOT" ]]; then
    printf 'status=not_installed\n'
    return 0
  fi
  if [[ "$ROOT" != /* || ! -d "$ROOT/source/.git" \
    || ! -f "$ROOT/source/wechat_courier.py" \
    || ! -x "$ROOT/venv/bin/python" \
    || ! -d "$ROOT/runtime" || ! -d "$ROOT/tmp" \
    || ! -d "$ROOT/cache/clang" ]]; then
    printf 'commit=%s\nstatus=invalid\n' "$PINNED_COMMIT"
    return 1
  fi
  commit="$($GIT_BIN -C "$ROOT/source" rev-parse HEAD 2>/dev/null || true)"
  dirty="$($GIT_BIN -C "$ROOT/source" status --porcelain 2>/dev/null || printf 'invalid')"
  if [[ "$commit" != "$PINNED_COMMIT" || -n "$dirty" ]]; then
    printf 'commit=%s\nstatus=invalid\n' "$PINNED_COMMIT"
    return 1
  fi
  printf 'commit=%s\nstatus=ready\n' "$PINNED_COMMIT"
}

if [[ "$MODE" == "--check" ]]; then
  check_installation
  exit $?
fi

if [[ "$ROOT" != /Volumes/* ]]; then
  printf 'status=invalid_root\n' >&2
  exit 2
fi
parent="$(dirname "$ROOT")"
name="$(basename "$ROOT")"
if [[ ! -d "$parent" ]]; then
  printf 'status=invalid_root\n' >&2
  exit 2
fi
resolved_parent="$(cd "$parent" && pwd -P)"
if [[ "$resolved_parent" != /Volumes/* || "$name" == '.' || "$name" == '..' ]]; then
  printf 'status=invalid_root\n' >&2
  exit 2
fi
ROOT="$resolved_parent/$name"

mkdir -p "$ROOT" "$ROOT/runtime" "$ROOT/tmp" "$ROOT/cache/clang"
if [[ ! -e "$ROOT/source" ]]; then
  "$GIT_BIN" clone "$UPSTREAM_URL" "$ROOT/source"
else
  [[ -d "$ROOT/source/.git" ]] || { printf 'status=invalid_source\n' >&2; exit 1; }
  origin="$($GIT_BIN -C "$ROOT/source" remote get-url origin 2>/dev/null || true)"
  [[ "$origin" == "$UPSTREAM_URL" ]] || { printf 'status=invalid_source\n' >&2; exit 1; }
fi
"$GIT_BIN" -C "$ROOT/source" fetch origin "$PINNED_COMMIT"
"$GIT_BIN" -C "$ROOT/source" checkout --detach "$PINNED_COMMIT"
"$PYTHON_BIN" -m venv "$ROOT/venv"
"$ROOT/venv/bin/python" -m pip install --disable-pip-version-check Pillow==11.3.0
printf 'commit=%s\nstatus=installed\n' "$PINNED_COMMIT"
