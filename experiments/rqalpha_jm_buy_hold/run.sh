#!/usr/bin/env bash
# 焦煤 JM 一年日线买入持有回测（RQAlpha Plus）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# 加载项目 .env（若存在）
ENV_FILE="$ROOT/../../.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source <(grep -E '^(RQDATA_LICENSE_KEY|RQSDK_LICENSE|RQDATAC_CONF|RQDATAC2_CONF)=' "$ENV_FILE" | sed 's/^/export /')
  set +a
fi

PYTHON="${PYTHON:-python3}"
VENV="$ROOT/.venv"

if [[ ! -d "$VENV" ]]; then
  echo "未找到 .venv，请先按 README.md 完成环境初始化。"
  exit 1
fi

# rqsdk license 写入的是 shell profile；运行前显式导出 URI
if [[ -z "${RQSDK_LICENSE:-}" && -n "${RQDATA_LICENSE_KEY:-}" ]]; then
  export RQSDK_LICENSE
  export RQDATAC_CONF
  RQSDK_LICENSE="$("$VENV/bin/python" - <<'PY'
from rqsdk.license_helper import format_rqdatac_uri
import os
print(format_rqdatac_uri(os.environ["RQDATA_LICENSE_KEY"]))
PY
)"
  export RQSDK_LICENSE RQDATAC_CONF="$RQSDK_LICENSE"
fi

START_DATE="${START_DATE:-2018-01-01}"
END_DATE="${END_DATE:-2018-12-31}"
CAPITAL="${CAPITAL:-1000000}"

mkdir -p "$ROOT/output"

if ! "$VENV/bin/python" "$ROOT/check_bundle.py"; then
  echo ""
  echo "bundle 未就绪，请先执行: rqsdk update-data --base"
  exit 1
fi

"$VENV/bin/rqalpha-plus" run \
  -f "$ROOT/buy_and_hold_jm.py" \
  -s "$START_DATE" \
  -e "$END_DATE" \
  -fq 1d \
  --account future "$CAPITAL" \
  --report "$ROOT/output" \
  -o "$ROOT/output/result.pkl"

echo "回测完成，报告目录: $ROOT/output"
