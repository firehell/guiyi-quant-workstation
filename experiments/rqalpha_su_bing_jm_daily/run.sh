#!/usr/bin/env bash
# 苏冰 JM 日线 EMA21+MACD+量能 — RQAlpha Plus 回测
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

ENV_FILE="$ROOT/../../.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source <(grep -E '^(RQDATA_LICENSE_KEY|RQSDK_LICENSE|RQDATAC_CONF|RQDATAC2_CONF)=' "$ENV_FILE" | sed 's/^/export /')
  set +a
fi

VENV="$ROOT/../rqalpha_jm_buy_hold/.venv"
if [[ ! -d "$VENV" ]]; then
  VENV="$ROOT/.venv"
fi
if [[ ! -d "$VENV" ]]; then
  echo "未找到 RQAlpha 虚拟环境。请先按 README.md 初始化 experiments/rqalpha_jm_buy_hold/.venv"
  exit 1
fi

if [[ -z "${RQSDK_LICENSE:-}" && -n "${RQDATA_LICENSE_KEY:-}" ]]; then
  export RQSDK_LICENSE RQDATAC_CONF
  RQSDK_LICENSE="$("$VENV/bin/python" - <<'PY'
from rqsdk.license_helper import format_rqdatac_uri
import os
print(format_rqdatac_uri(os.environ["RQDATA_LICENSE_KEY"]))
PY
)"
  export RQSDK_LICENSE RQDATAC_CONF="$RQSDK_LICENSE"
fi

START_DATE="${START_DATE:-2023-01-03}"
END_DATE="${END_DATE:-2025-12-31}"
CAPITAL="${CAPITAL:-1000000}"

mkdir -p "$ROOT/output"

"$VENV/bin/python" "$ROOT/../rqalpha_jm_buy_hold/check_bundle.py"

PLOT="${PLOT:-0}"
PLOT_ARGS=()
if [[ "$PLOT" == "1" ]]; then
  PLOT_ARGS+=(--plot --plot-save "$ROOT/output/backtest_plot.png")
fi

"$VENV/bin/rqalpha-plus" run \
  -f "$ROOT/su_bing_jm_daily_ema21_macd_volume.py" \
  -s "$START_DATE" \
  -e "$END_DATE" \
  -fq 1d \
  --account future "$CAPITAL" \
  --report "$ROOT/output" \
  -o "$ROOT/output/result.pkl" \
  "${PLOT_ARGS[@]}"

echo "回测完成，报告目录: $ROOT/output"
if [[ "$PLOT" == "1" ]]; then
  echo "收益曲线图: $ROOT/output/backtest_plot.png"
fi
