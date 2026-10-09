#!/usr/bin/env bash
# Stable Git-external launcher: select the exact root declared by the supervised job.
set -euo pipefail
root="${GUIYI_PROJECT_ROOT:-}"
[[ "$root" == /* && -d "$root" ]] || { printf 'RUNTIME_ROOT_INVALID\n' >&2; exit 78; }
physical_root="$(cd -P "$root" && pwd)"
[[ "$root" == "$physical_root" ]] || { printf 'RUNTIME_ROOT_INVALID\n' >&2; exit 78; }
launcher="$root/scripts/ops/macos/run-local-service.sh"
[[ -f "$launcher" && ! -L "$launcher" ]] || { printf 'RUNTIME_LAUNCHER_INVALID\n' >&2; exit 78; }
exec /bin/bash "$launcher" "$@"
