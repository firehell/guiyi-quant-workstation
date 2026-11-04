#!/bin/bash
# Installed byte-for-byte in AppSupport; the exact root remains in config/tag.
set -euo pipefail
readonly tq_root="${GUIYI_PROJECT_ROOT:?TQ_ROOT_REQUIRED}"
exec /usr/bin/env -i HOME="$HOME" USER="$USER" LOGNAME="$LOGNAME" \
  GUIYI_PROJECT_ROOT="$tq_root" PATH='/usr/bin:/bin:/usr/sbin:/sbin' \
  /bin/bash -euo pipefail -c '
    umask 077
    readonly tq_root="$GUIYI_PROJECT_ROOT"
    readonly tq_private="$HOME/Library/Application Support/GuiyiQuant"
    set -a
    source "$tq_private/project.env" >/dev/null 2>&1
    set +a
    export REDIS_PASSWORD="${REDIS_PASSWORD:-$POSTGRES_PASSWORD}"
    if [[ -z "${REDIS_URL:-}" || "$REDIS_URL" == "redis://127.0.0.1:6379/0" ]]; then
      export REDIS_URL="redis://:${REDIS_PASSWORD}@127.0.0.1:6379/0"
    fi
    export GUIYI_PROJECT_ROOT="$tq_root"
    exec "$tq_root/services/tq-executor/.venv/bin/python" -m guiyi_quant.tq_simulation.worker --config "$tq_private/tqkq-simulation/config.json" "$@"
  ' bash "$@"
