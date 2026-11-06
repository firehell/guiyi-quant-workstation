#!/bin/bash
# Independent development model; no Broker or standard Runtime binding.
set -euo pipefail
readonly model_root="${1:?MODEL_SOURCE_ROOT_REQUIRED}"
[[ "$model_root" == /Volumes/* && -d "$model_root" && ! -L "$model_root" ]] || exit 64
exec /usr/bin/env -i HOME="$HOME" USER="$USER" LOGNAME="$LOGNAME" \
 PATH='/usr/bin:/bin:/usr/sbin:/sbin' \
 PYTHONPATH="$model_root:$model_root/services/quant-api:$model_root/packages/quant-core" \
 /bin/bash -euo pipefail -c '
  cd "$1"
  umask 077
  exec "$1/services/quant-api/.venv/bin/python" -m app.subing_model_service
 ' bash "$model_root"
