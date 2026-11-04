#!/bin/bash
set -euo pipefail
umask 077
readonly tq_root="${GUIYI_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
readonly tq_private="$HOME/Library/Application Support/GuiyiQuant"
# Same private dependency environment as the existing API/market services.
set -a
source "$tq_private/project.env" >/dev/null 2>&1
set +a
export REDIS_PASSWORD="${REDIS_PASSWORD:-$POSTGRES_PASSWORD}"
if [[ -z "${REDIS_URL:-}" || "$REDIS_URL" == "redis://127.0.0.1:6379/0" ]]; then
  export REDIS_URL="redis://:${REDIS_PASSWORD}@127.0.0.1:6379/0"
fi
export GUIYI_PROJECT_ROOT="$tq_root"
cd "$tq_root"
exec "$tq_root/services/tq-executor/.venv/bin/python" -m guiyi_quant.tq_simulation.worker --config "$tq_private/tqkq-simulation/config.json" "$@"
