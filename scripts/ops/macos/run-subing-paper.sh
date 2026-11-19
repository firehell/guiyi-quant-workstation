#!/bin/bash
set -euo pipefail
readonly paper_root="${1:?PAPER_SOURCE_ROOT_REQUIRED}"
[[ "$paper_root" == /Volumes/* && -d "$paper_root" && ! -L "$paper_root" ]] || exit 64
exec /usr/bin/env -i HOME="$HOME" USER="$USER" LOGNAME="$LOGNAME" \
 PATH='/usr/bin:/bin:/usr/sbin:/sbin' \
 PYTHONPATH="$paper_root:$paper_root/services/quant-api:$paper_root/packages/quant-core" \
 /bin/bash -euo pipefail -c '
  cd "$1"
  umask 077
  exec "$1/services/quant-api/.venv/bin/python" -m app.subing_portfolio_worker --start 16 --refresh-facts
 ' bash "$paper_root"
