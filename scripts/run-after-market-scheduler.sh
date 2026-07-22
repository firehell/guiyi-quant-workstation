#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${GUIYI_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
RUNTIME_DIR="${GUIYI_RUNTIME_DIR:-$HOME/Library/Application Support/GuiyiQuant}"
RUNTIME_ENV="${GUIYI_RUNTIME_ENV:-$RUNTIME_DIR/project.env}"

[[ -d "$PROJECT_ROOT/services/quant-api" ]] || { printf '{"status":"blocked","error_type":"project_root_unavailable"}\n' >&2; exit 78; }
[[ -f "$RUNTIME_ENV" ]] || { printf '{"status":"blocked","error_type":"runtime_env_missing"}\n' >&2; exit 78; }

set -a
# shellcheck disable=SC1090
source "$RUNTIME_ENV"
set +a

[[ -n "${POSTGRES_PASSWORD:-}" ]] || { printf '{"status":"blocked","error_type":"postgres_password_missing"}\n' >&2; exit 78; }
export REDIS_PASSWORD="${REDIS_PASSWORD:-$POSTGRES_PASSWORD}"
if [[ -z "${REDIS_URL:-}" || "$REDIS_URL" == "redis://127.0.0.1:6379/0" ]]; then
  export REDIS_URL="redis://:${REDIS_PASSWORD}@127.0.0.1:6379/0"
fi

[[ "${GUIYI_AFTER_MARKET_AUTOMATION_ENABLED:-0}" =~ ^(1|true|yes|on)$ ]] || { printf '{"status":"disabled","error_type":"automation_disabled"}\n' >&2; exit 78; }
[[ -n "${GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_PACKET:-}" ]] || { printf '{"status":"blocked","error_type":"approval_packet_missing"}\n' >&2; exit 78; }
[[ -f "$GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_PACKET" ]] || { printf '{"status":"blocked","error_type":"approval_packet_unavailable"}\n' >&2; exit 78; }
[[ "${GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_HASH:-}" =~ ^[0-9a-f]{64}$ ]] || { printf '{"status":"blocked","error_type":"approval_hash_invalid"}\n' >&2; exit 78; }

export PYTHONPATH="$PROJECT_ROOT/services/quant-api:$PROJECT_ROOT/packages/quant-core${PYTHONPATH:+:$PYTHONPATH}"
cd "$PROJECT_ROOT/services/quant-api"
exec uv run --frozen python -m app.after_market_scheduler \
  --run \
  --confirm-after-market-automation \
  --approval-packet "$GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_PACKET" \
  --approval-hash "$GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_HASH"
